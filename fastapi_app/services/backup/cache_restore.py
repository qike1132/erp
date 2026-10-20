"""Redis/Meilisearch 恢复。"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil

from ._constants import MEILI_HOST, MEILI_MASTER_KEY, REDIS_DUMP
from ._proc import run_proc

logger = logging.getLogger(__name__)


async def _reload_redis() -> bool:
    """尝试重新加载 Redis 数据"""
    redis_cli = shutil.which('redis-cli')
    if not redis_cli:
        logger.warning('未找到 redis-cli，无法自动重新加载 Redis')
        return False
    try:
        from fastapi_app.core.config import settings
        cmd = [redis_cli]
        cli_env = os.environ.copy()
        redis_url = settings.REDIS_URL
        if redis_url:
            from urllib.parse import urlparse
            parsed = urlparse(redis_url)
            if parsed.hostname:
                cmd.extend(['-h', parsed.hostname])
            if parsed.port:
                cmd.extend(['-p', str(parsed.port)])
            if parsed.password:
                cli_env['REDISCLI_AUTH'] = parsed.password
        cmd.extend(['DEBUG', 'RELOAD'])
        try:
            proc = await run_proc(cmd, env=cli_env, timeout=10)
        except TimeoutError:
            logger.warning('Redis DEBUG RELOAD 超时')
            return False
        if proc.returncode == 0:
            logger.info('Redis DEBUG RELOAD 成功')
            return True
        stderr_text = (proc.stderr or b'').decode(errors='replace')
        logger.warning('Redis DEBUG RELOAD 失败: %s', stderr_text)
        try:
            shutdown_cmd = [*cmd[:-2], 'SHUTDOWN', 'NOSAVE']
            # SHUTDOWN 会让 Redis 断开连接，超时属预期行为
            with contextlib.suppress(TimeoutError):
                await run_proc(shutdown_cmd, env=cli_env, timeout=5)
            logger.info('Redis SHUTDOWN NOSAVE 已发送，等待自动重启')
            await asyncio.sleep(2)
            ping_cmd = [*cmd[:-2], 'PING']
            for _ in range(5):
                try:
                    ping_proc = await run_proc(ping_cmd, env=cli_env, timeout=3)
                except TimeoutError:
                    await asyncio.sleep(1)
                    continue
                if ping_proc.returncode == 0:
                    logger.info('Redis 已重启成功')
                    return True
                await asyncio.sleep(1)
            logger.warning('Redis 重启后未能响应 PING')
            return False
        except (TimeoutError, OSError) as e2:
            logger.warning('Redis SHUTDOWN 尝试失败: %s', e2)
            return False
    except (TimeoutError, OSError) as e:
        logger.warning('Redis 重新加载失败: %s', e)
        return False


async def restore_redis_rdb(zf) -> dict:
    """恢复 Redis RDB 文件"""
    try:
        rdb_data = zf.read('redis/dump.rdb')
        if REDIS_DUMP.is_file():
            backup_path = REDIS_DUMP.with_suffix('.rdb.bak')
            shutil.copy2(REDIS_DUMP, backup_path)
        REDIS_DUMP.write_bytes(rdb_data)
        reload_result = await _reload_redis()
        if reload_result:
            return {'status': 'ok', 'message': 'Redis RDB 已恢复并重新加载'}
        return {'status': 'ok', 'message': 'Redis RDB 已恢复，需手动重启 Redis 生效', 'auto_reload_failed': True}
    except (OSError, ValueError) as e:
        return {'status': 'error', 'error': f'Redis RDB 恢复失败: {e}'}


async def restore_meilisearch(zf) -> dict:
    """恢复 MeiliSearch 索引"""
    try:
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
                # 已删除的文档作为「幽灵」残留（Redis RDB 恢复同样是整体替换）。
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
