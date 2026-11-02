"""B3/NV-1（2026-11-02 审计核实）：恢复路径必须失效已撤销会话。

背景：Legacy JSON 整库恢复会把 user 表整表回滚（token_version/status/password_hash
随行回到备份时点），备份后被 bump_token_version 撤销的凭据将重新通过 tv 相等判定
（core/deps.py `_verify_user_active`）；含 redis/dump.rdb 的组件-only 包会把撤销
黑名单回滚（restore_redis_rdb 整体替换 RDB），登出 token 在 tv 不变的情况下重新
有效。zip 整库路径此前已在 restore_from_zip 末尾统一 revoke；本文件钉住其余四条
漏接路径的接线：
- POST /import 的 JSON 分支（db_transaction 提交后）
- POST /restore-by-name/{filename} 的 JSON 分支（db_transaction 提交后）
- _run_async_file_restore 的 JSON 分支（get_async_db_context 提交后）
- _restore_components_only 的 redis/dump.rdb 通道（RDB 落盘成功即失效）

接线用 spy 断言（monkeypatch revoke 为 AsyncMock）而非端到端旧 token 请求——
标准 harness 的 autouse override_deps 会把鉴权依赖整体 stub，HTTP 级「旧 token
→401」观察在该 harness 下不可达。变异检查：注释掉任一 revoke 接线，对应用例
必须变红。
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fastapi_app.core.backup_progress as backup_progress_mod
import fastapi_app.core.cache as core_cache_mod
import fastapi_app.core.database as core_database_mod
from fastapi_app.api.v1.endpoints.backup import restore as restore_mod
from fastapi_app.services.backup import restore as restore_svc
from fastapi_app.services.backup.exceptions import RestoreError


def _json_result() -> dict:
    return {
        'verification': {'overall_pass': True},
        'total_inserted': 0, 'results': {}, 'errors': [],
    }


def _revoke_spy(calls: list[str], label: str = 'revoke') -> AsyncMock:
    async def _fake_revoke() -> None:
        calls.append(label)

    return AsyncMock(side_effect=_fake_revoke)


# ---------------------------------------------------------------------------
# 1) POST /import 的 JSON 分支
# ---------------------------------------------------------------------------
async def test_import_json_revokes_sessions_after_commit(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        restore_mod, '_read_backup_file',
        AsyncMock(return_value=(b'{"tables": {}}', False, 'b.json')),
    )
    monkeypatch.setattr(restore_mod, '_get_encryption_password', lambda *a, **k: None)
    monkeypatch.setattr(
        restore_mod, '_acquire_sync_restore_lock', AsyncMock(return_value='owner-1'),
    )
    monkeypatch.setattr(
        restore_mod, '_pre_restore_info_or_fail', AsyncMock(return_value={'success': True}),
    )

    async def fake_restore_legacy_json(backup_data, db, task_id=None):
        calls.append('restore')
        return _json_result()

    monkeypatch.setattr(
        restore_mod.backup_service, 'restore_legacy_json', fake_restore_legacy_json,
    )

    @asynccontextmanager
    async def fake_tx(db, **kwargs):
        yield None
        calls.append('tx-commit')  # asynccontextmanager 正常退出 = db_transaction 提交

    monkeypatch.setattr(restore_mod, 'db_transaction', fake_tx)
    monkeypatch.setattr(restore_mod, 'revoke_all_sessions_after_restore', _revoke_spy(calls))
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', AsyncMock())

    result = await restore_mod.import_backup(
        file=object(), confirm=True, confirm_sensitive=False,
        allow_missing_pre_restore_backup=False, x_backup_password=None,
        user=SimpleNamespace(), db=AsyncMock(),
    )

    assert result['success'] is True
    # 时序断言：revoke 必须发生在 db_transaction 提交之后（提交前调用会与
    # 外层事务的 user 表行锁在同一事件循环内互等死锁）。
    assert calls == ['restore', 'tx-commit', 'revoke'], (
        f'JSON 恢复后未按「提交→revoke」次序失效会话: {calls}'
    )


# ---------------------------------------------------------------------------
# 2) POST /restore-by-name/{filename} 的 JSON 分支
# ---------------------------------------------------------------------------
async def test_restore_by_name_json_revokes_sessions_after_commit(
    monkeypatch, tmp_path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(restore_mod.backup_service, 'BACKUP_DIR', tmp_path)
    (tmp_path / 'b.json').write_bytes(b'{"tables": {}}')
    monkeypatch.setattr(restore_mod, '_get_encryption_password', lambda *a, **k: None)
    monkeypatch.setattr(
        restore_mod, '_sniff_server_backup_format',
        AsyncMock(return_value=(b'{"tables": {}}', False)),
    )
    monkeypatch.setattr(
        restore_mod, '_acquire_sync_restore_lock', AsyncMock(return_value='owner-2'),
    )
    monkeypatch.setattr(
        restore_mod, '_pre_restore_info_or_fail', AsyncMock(return_value={'success': True}),
    )

    async def fake_restore_legacy_json(backup_data, db, task_id=None):
        calls.append('restore')
        return _json_result()

    monkeypatch.setattr(
        restore_mod.backup_service, 'restore_legacy_json', fake_restore_legacy_json,
    )

    @asynccontextmanager
    async def fake_tx(db, **kwargs):
        yield None
        calls.append('tx-commit')

    monkeypatch.setattr(restore_mod, 'db_transaction', fake_tx)
    monkeypatch.setattr(restore_mod, 'revoke_all_sessions_after_restore', _revoke_spy(calls))
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', AsyncMock())

    result = await restore_mod.restore_server_backup(
        filename='b.json', confirm=True, confirm_sensitive=False,
        allow_missing_pre_restore_backup=False, password=None, x_backup_password=None,
        user=SimpleNamespace(), db=AsyncMock(),
    )

    assert result['success'] is True
    assert calls == ['restore', 'tx-commit', 'revoke'], (
        f'/restore-by-name JSON 恢复后未按「提交→revoke」次序失效会话: {calls}'
    )


# ---------------------------------------------------------------------------
# 3) _run_async_file_restore 的 JSON 分支
# ---------------------------------------------------------------------------
async def _run_async_json_restore(content: bytes, monkeypatch, calls: list[str]) -> None:
    """共用装配：跑一次异步 JSON 恢复，revoke 记入 calls。"""
    monkeypatch.setattr(
        restore_mod, '_pre_restore_info_or_fail',
        AsyncMock(return_value={'success': True}),
    )
    monkeypatch.setattr(backup_progress_mod, 'update_progress', AsyncMock())
    monkeypatch.setattr(backup_progress_mod, 'fail_progress', AsyncMock())
    monkeypatch.setattr(backup_progress_mod, 'touch_progress', AsyncMock())
    monkeypatch.setattr(restore_mod, '_report_restore_outcome', AsyncMock())
    monkeypatch.setattr(restore_mod.backup_service, 'renew_restore_lock', AsyncMock(return_value=True))
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', AsyncMock())

    @asynccontextmanager
    async def fake_db_ctx():
        calls.append('tx-begin')
        yield AsyncMock(name='db')
        calls.append('tx-commit')  # get_async_db_context 正常退出 = commit

    monkeypatch.setattr(core_database_mod, 'get_async_db_context', fake_db_ctx)
    monkeypatch.setattr(restore_mod, 'revoke_all_sessions_after_restore', _revoke_spy(calls))

    await restore_mod._run_async_file_restore(
        'task-1', content, is_zip=False, filename='b.json',
        confirm_sensitive=False, decrypt_password=None,
        allow_missing_pre_restore_backup=False,
    )


async def test_async_json_restore_revokes_sessions_after_commit(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_restore_legacy_json(backup_data, db, task_id=None):
        calls.append('restore')
        return _json_result()

    monkeypatch.setattr(
        restore_mod.backup_service, 'restore_legacy_json', fake_restore_legacy_json,
    )

    await _run_async_json_restore(b'{"tables": {}}', monkeypatch, calls)

    assert calls == ['tx-begin', 'restore', 'tx-commit', 'revoke'], (
        f'异步 JSON 恢复后未按「提交→revoke」次序失效会话: {calls}'
    )


async def test_async_json_restore_failure_skips_revoke(monkeypatch) -> None:
    """恢复失败（内部已 rollback）不得 revoke——那是全员无谓登出。"""
    calls: list[str] = []

    async def failing_restore(backup_data, db, task_id=None):
        calls.append('restore')
        raise RestoreError('恢复过程中出错: 表数据不完整')

    monkeypatch.setattr(restore_mod.backup_service, 'restore_legacy_json', failing_restore)

    await _run_async_json_restore(b'{"tables": {}}', monkeypatch, calls)

    assert calls == ['tx-begin', 'restore', 'tx-commit'], (
        f'恢复失败后不应 revoke: {calls}'
    )


# ---------------------------------------------------------------------------
# 4) _restore_components_only 的 redis/dump.rdb 通道
# ---------------------------------------------------------------------------
class _FakeZip:
    """最小 ZipFile 替身：只提供 namelist / read('manifest.json')。"""

    def namelist(self) -> list[str]:
        return ['manifest.json', 'redis/dump.rdb']

    def read(self, name: str) -> bytes:
        assert name == 'manifest.json'
        return json.dumps({'version': '1.0', 'tables': {}}).encode('utf-8')


async def _run_components_only(monkeypatch, components: dict) -> tuple[dict, list[str]]:
    calls: list[str] = []
    monkeypatch.setattr(
        restore_svc, 'restore_non_dependent_components',
        AsyncMock(return_value=components),
    )
    monkeypatch.setattr(restore_svc, 'verify_restore', AsyncMock(return_value={'overall_pass': True}))
    monkeypatch.setattr(core_cache_mod, 'invalidate_related_caches', AsyncMock())
    monkeypatch.setattr(restore_svc, 'revoke_all_sessions_after_restore', _revoke_spy(calls))

    result = await restore_svc._restore_components_only(
        _FakeZip(), AsyncMock(name='db'), AsyncMock(name='_prog'), confirm_sensitive=False,
    )
    return result, calls


async def test_components_only_with_redis_rdb_revokes_sessions(monkeypatch) -> None:
    """RDB 落盘成功（含 auto_reload_failed 变体）→ 黑名单回滚 → 必须 revoke。"""
    for variant in (
        {'redis': {'status': 'ok', 'message': 'Redis RDB 已恢复并重新加载'}},
        {'redis': {'status': 'ok', 'message': 'Redis RDB 已恢复，需手动重启 Redis 生效', 'auto_reload_failed': True}},
    ):
        _, calls = await _run_components_only(monkeypatch, variant)
        assert calls == ['revoke'], (
            f'含 redis/dump.rdb 的组件包恢复后未失效会话: {variant} -> {calls}'
        )


async def test_components_only_without_redis_skips_revoke(monkeypatch) -> None:
    """无 redis 组件 / RDB 恢复失败：撤销状态未被回滚，不得全员登出。"""
    for components in (
        {'filestore': {'status': 'ok'}},  # 包不含 redis
        {'redis': {'status': 'error', 'error': 'Redis RDB 恢复失败: disk full'}},
    ):
        _, calls = await _run_components_only(monkeypatch, components)
        assert calls == [], (
            f'不涉及撤销状态回滚的组件恢复不应 revoke: {components} -> {calls}'
        )
