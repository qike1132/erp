"""Redis 组件：本仓不做备份/恢复（审计批次4：P1-11，口径 A）。

## 拦哪种出错

原先 `restore_redis_rdb()` 把包内 `redis/dump.rdb` 覆盖到 `<repo>/dump.rdb` 再发
`DEBUG RELOAD`，而打包侧只有「项目根恰好有 dump.rdb」时才打包（生产 Redis 的 RDB
在 Redis 自己的数据目录）⇒ 通道几乎永不触发；**一旦触发，reload 失败仍返回
status=ok**（假成功），运维会以为缓存/队列语义已回到备份点。

而 Redis 里放的是缓存、ARQ 队列与进度键：恢复到旧快照反而会把陈旧队列任务带回来。

## 定口径（A）

- 打包：**不再**放 `redis/dump.rdb`，`manifest.includes` 也不再自述 `redis_rdb`；
- 恢复：老包里真带了 RDB 也不恢复，如实上报 `status=skipped / reason=not_implemented`；
- 检查：`zip_contents.redis_restore` 直说「本仓不做 Redis 恢复，重建后缓存/队列需自愈」；
- 组件通道不再为「撤销黑名单随 RDB 回滚」而全员登出（风险面随通道一起消失）。

## 变异检查

把「恢复侧 redis 分支」改回写盘/返回 ok → 用例 2 变红；把 RDB 打包加回去 →
用例 1 变红；把常量/死函数留一个残骸 → 用例 3 变红；去掉检查说明 → 用例 4 变红。
"""
from __future__ import annotations

import io
import json
import zipfile

from fastapi_app.services.backup import records
from fastapi_app.services.backup import restore as restore_mod
from fastapi_app.services.backup.orchestration import core as orch


async def test_package_has_no_redis_member(monkeypatch, tmp_path):
    """打包产物不得含 redis/，manifest 也不得再自述 redis_rdb。"""
    monkeypatch.setattr(orch, 'pack_config_files', lambda zf, include: ([], []))
    monkeypatch.setattr(orch, 'record_config_includes', lambda *a, **kw: None)

    async def _noop_meili(_zf, _manifest):
        return None

    monkeypatch.setattr(orch, '_export_meilisearch', _noop_meili)

    db_dir = tmp_path / 'database'
    db_dir.mkdir()
    (db_dir / 'dump.json').write_text('{}', encoding='utf-8')
    zip_path = tmp_path / 'backup.zip'
    manifest: dict = {'includes': {}}

    await orch._pack_backup_zip(
        zip_path, tmp_path, False, db_dir / 'dump.sql.gz', manifest, False, None,
    )

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    assert not any(n.startswith('redis/') for n in names), f'包里仍有 Redis 快照：{names}'
    assert 'redis_rdb' not in manifest['includes'], 'manifest 仍自述含 Redis RDB'


async def test_restore_reports_redis_skipped_for_legacy_member(monkeypatch):
    """老包带 redis/dump.rdb：如实登记「已跳过」，绝不返回 ok（假成功）。"""

    class _Zip:
        def namelist(self):
            return ['manifest.json', 'redis/dump.rdb']

    result = await restore_mod.restore_non_dependent_components(
        _Zip(), confirm_sensitive=False,
    )

    redis_res = result['redis']
    assert redis_res['status'] == 'skipped', f'Redis 仍报「已恢复」：{redis_res}'
    assert redis_res['reason'] == 'not_implemented'
    assert redis_res['legacy_member_present'] is True
    assert result['errors'] == []


def test_redis_dead_path_is_really_gone():
    """死路径必须真的删掉 —— 留着任何残骸都还是「看起来做了」。"""
    from fastapi_app.services import backup as backup_pkg
    from fastapi_app.services.backup import cache_restore

    assert not hasattr(cache_restore, 'restore_redis_rdb')
    assert not hasattr(cache_restore, '_reload_redis')
    assert not hasattr(backup_pkg, 'REDIS_DUMP')


def test_inspect_explains_redis_is_not_restored():
    """检查报告直说「不做 Redis 恢复」，避免「包里有 RDB」被误读成缓存能回滚。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        zf.writestr('manifest.json', json.dumps({'version': '2.0', 'tables': {}}))
        zf.writestr('database/dump.json', '{}')
        zf.writestr('redis/dump.rdb', b'x')  # 老包

    info = records.validate_backup_file(buf.getvalue(), 'erp_backup_20260101_000000.zip')

    contents = info['zip_contents']
    assert contents['has_redis'] is True
    assert 'Redis' in contents['redis_restore'], contents
