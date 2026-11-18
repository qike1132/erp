"""组件恢复：Meilisearch 索引 + Redis 的明确口径（Redis 不做恢复）。

P1-11（2026-11-17 上线前审计）定口径：**本仓不做 Redis 恢复**。

原先 `restore_redis_rdb()` 会把包内 `redis/dump.rdb` 覆盖到 `<repo>/dump.rdb` 再发
`DEBUG RELOAD`，但这条链路从来名不副实：
- 打包侧只在「项目根恰好有 dump.rdb」时才把 RDB 放进包（生产 Redis 的 RDB 在
  Redis 自己的数据目录，项目根通常没有）→ 产物里几乎永远没有 `redis/`；
- 恢复侧因此要么不触发，要么落盘后 reload 失败**仍返回 status=ok**（「假成功」），
  运维会以为缓存/队列语义已回到备份点。

而 Redis 里放的是缓存、ARQ 队列与进度键：恢复到旧快照反而会把陈旧队列任务带回来。
所以口径改为：不打包 RDB、不恢复 RDB，重建后缓存/队列按自愈处理；若拿到含
`redis/dump.rdb` 的老包，如实上报「已跳过」，绝不假装恢复成功。
"""
from __future__ import annotations

import json
import logging

from ._constants import MEILI_HOST, MEILI_MASTER_KEY

logger = logging.getLogger(__name__)

# Redis 恢复的对外口径：restore 结果、检查报告都引用这三个常量，避免两处不一致。
REDIS_RESTORE_STATUS = 'skipped'
REDIS_RESTORE_REASON = 'not_implemented'
REDIS_RESTORE_MESSAGE = (
    '本仓不做 Redis 恢复：备份包不再包含 Redis 快照，重建后缓存/ARQ 队列按自愈处理'
)


def redis_restore_note(*, legacy_member: bool = False) -> dict:
    """Redis 组件的恢复结果：显式「不做 / 已跳过」。

    ``legacy_member=True`` 表示老包里确实带了 ``redis/dump.rdb`` —— 仍然不恢复
    （口径见模块 docstring），但要把「包里有什么」如实说出来，避免运维误以为
    缓存已回到备份点。
    """
    return {
        'status': REDIS_RESTORE_STATUS,
        'reason': REDIS_RESTORE_REASON,
        'message': REDIS_RESTORE_MESSAGE,
        'legacy_member_present': legacy_member,
    }


async def restore_meilisearch(zf) -> dict:
    """恢复 MeiliSearch 索引"""
    try:
        _meili_info = zf.getinfo('meilisearch/dump.json')
        if _meili_info.file_size > 512 * 1024 * 1024:
            return {'status': 'error', 'error': 'meilisearch/dump.json 成员超过 512MB 上限，疑似构造包，已拒绝'}
        meili_data = json.loads(zf.read('meilisearch/dump.json'))
    except (json.JSONDecodeError, KeyError, OSError) as e:
        return {'status': 'error', 'error': f'MeiliSearch 数据读取失败: {e}'}
    try:
        import httpx
    except ImportError:
        return {'status': 'error', 'error': 'httpx 未安装，无法恢复 MeiliSearch'}
    restored_indexes = []
    errors = []
    async with httpx.AsyncClient() as meili_client:
        for key, data in meili_data.items():
            if key.endswith('__settings'):
                continue
            idx_name = key
            if not idx_name.replace('_', '').replace('-', '').isalnum():
                errors.append(f'{idx_name}: 索引名不合法，已跳过')
                continue
            settings_key = f'{idx_name}__settings'
            try:
                create_resp = await meili_client.post(
                    f'{MEILI_HOST}/indexes',
                    headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                    json={'uid': idx_name, 'primaryKey': 'id'}, timeout=10
                )
                if create_resp.status_code not in (200, 201, 409):
                    errors.append(f'{idx_name}: 创建索引失败 ({create_resp.status_code})')
                    continue
                if settings_key in meili_data:
                    await meili_client.patch(
                        f'{MEILI_HOST}/indexes/{idx_name}/settings',
                        headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                        json=meili_data[settings_key], timeout=10
                    )
                # Z05-R16：恢复是整体替换语义——先清空索引内文档，避免备份点之后
                # 已删除的文档作为「幽灵」残留。
                clear_resp = await meili_client.delete(
                    f'{MEILI_HOST}/indexes/{idx_name}/documents',
                    headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'}, timeout=30
                )
                if clear_resp.status_code not in (200, 202, 204, 404):
                    errors.append(f'{idx_name}: 清空旧文档失败 ({clear_resp.status_code})')
                    continue
                if data:
                    docs_resp = await meili_client.post(
                        f'{MEILI_HOST}/indexes/{idx_name}/documents',
                        headers={'Authorization': f'Bearer {MEILI_MASTER_KEY}'},
                        json=data, timeout=60
                    )
                    if docs_resp.status_code in (200, 201, 202):
                        restored_indexes.append(idx_name)
                    else:
                        errors.append(f'{idx_name}: 文档导入失败 ({docs_resp.status_code})')
                else:
                    restored_indexes.append(idx_name)
            except (OSError, ValueError) as e:
                errors.append(f'{idx_name}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored_indexes': restored_indexes, 'errors': errors}
