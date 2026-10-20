"""P1-9：同步恢复必须先取到还原锁，再做安全备份。

旧顺序下并发恢复会先撞 create_pre_restore_backup 的 BackupLockError，
被吞成「无回滚点」428，诱导用户带 allow_missing 跳过回滚点。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from fastapi_app.api.v1.endpoints.backup import restore as restore_mod


def _zip_result() -> dict:
    return {
        'verification': {'overall_pass': True},
        '_manifest_tables': {},
    }


async def test_import_backup_concurrent_lock_returns_409_without_pre_backup(monkeypatch) -> None:
    monkeypatch.setattr(
        restore_mod, '_read_backup_file',
        AsyncMock(return_value=(b'PK\x03\x04zip', True, 'x.zip')),
    )
    monkeypatch.setattr(restore_mod, '_get_encryption_password', lambda *a, **k: None)
    monkeypatch.setattr(
        restore_mod, '_acquire_sync_restore_lock',
        AsyncMock(side_effect=HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')),
    )
    pre = AsyncMock(return_value={'success': True})
    monkeypatch.setattr(restore_mod, '_pre_restore_info_or_fail', pre)
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await restore_mod.import_backup(
            file=object(), confirm=True, confirm_sensitive=False,
            allow_missing_pre_restore_backup=False, x_backup_password=None,
            user=SimpleNamespace(), db=AsyncMock(),
        )

    assert exc.value.status_code == 409
    assert pre.await_count == 0, '取锁失败时不得先做安全备份（那是 428 误报的来源）'


async def test_import_backup_pre_backup_runs_after_lock(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        restore_mod, '_read_backup_file',
        AsyncMock(return_value=(b'PK\x03\x04zip', True, 'x.zip')),
    )
    monkeypatch.setattr(restore_mod, '_get_encryption_password', lambda *a, **k: None)

    async def fake_lock(purpose: str) -> str:
        calls.append('lock')
        return 'owner-1'

    async def fake_pre(db, allowed, **kwargs):
        calls.append('pre')
        return {'success': True}

    monkeypatch.setattr(restore_mod, '_acquire_sync_restore_lock', fake_lock)
    monkeypatch.setattr(restore_mod, '_pre_restore_info_or_fail', fake_pre)
    monkeypatch.setattr(
        restore_mod.backup_service, 'restore_from_zip',
        AsyncMock(return_value=_zip_result()),
    )
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', AsyncMock())

    result = await restore_mod.import_backup(
        file=object(), confirm=True, confirm_sensitive=False,
        allow_missing_pre_restore_backup=False, x_backup_password=None,
        user=SimpleNamespace(), db=AsyncMock(),
    )

    assert calls == ['lock', 'pre']
    assert result['success'] is True


async def test_restore_by_name_zip_lock_first(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(restore_mod.backup_service, 'BACKUP_DIR', tmp_path)
    (tmp_path / 'b.zip').write_bytes(b'PK\x03\x04zip')
    monkeypatch.setattr(restore_mod, '_get_encryption_password', lambda *a, **k: None)
    monkeypatch.setattr(
        restore_mod, '_sniff_server_backup_format',
        AsyncMock(return_value=(b'PK\x03\x04zip', True)),
    )
    monkeypatch.setattr(
        restore_mod, '_acquire_sync_restore_lock',
        AsyncMock(side_effect=HTTPException(status_code=409, detail='另一个恢复操作正在执行中')),
    )
    pre = AsyncMock(return_value={'success': True})
    monkeypatch.setattr(restore_mod, '_pre_restore_info_or_fail', pre)
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await restore_mod.restore_server_backup(
            filename='b.zip', confirm=True, confirm_sensitive=False,
            allow_missing_pre_restore_backup=False, password=None, x_backup_password=None,
            user=SimpleNamespace(), db=AsyncMock(),
        )

    assert exc.value.status_code == 409
    assert pre.await_count == 0


async def test_restore_by_name_json_lock_first(monkeypatch, tmp_path: Path) -> None:
    calls: list[str] = []
    monkeypatch.setattr(restore_mod.backup_service, 'BACKUP_DIR', tmp_path)
    (tmp_path / 'b.json').write_bytes(b'{"tables": {}}')
    monkeypatch.setattr(restore_mod, '_get_encryption_password', lambda *a, **k: None)
    monkeypatch.setattr(
        restore_mod, '_sniff_server_backup_format',
        AsyncMock(return_value=(b'{"tables": {}}', False)),
    )

    async def fake_lock(purpose: str) -> str:
        calls.append('lock')
        return 'owner-2'

    async def fake_pre(db, allowed, **kwargs):
        calls.append('pre')
        return {'success': True}

    @asynccontextmanager
    async def fake_tx(db, **kwargs):
        yield None

    monkeypatch.setattr(restore_mod, '_acquire_sync_restore_lock', fake_lock)
    monkeypatch.setattr(restore_mod, '_pre_restore_info_or_fail', fake_pre)
    monkeypatch.setattr(restore_mod, 'db_transaction', fake_tx)
    monkeypatch.setattr(
        restore_mod.backup_service, 'restore_legacy_json',
        AsyncMock(return_value={
            'verification': {'overall_pass': True},
            'total_inserted': 0, 'results': {}, 'errors': [],
        }),
    )
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', AsyncMock())

    result = await restore_mod.restore_server_backup(
        filename='b.json', confirm=True, confirm_sensitive=False,
        allow_missing_pre_restore_backup=False, password=None, x_backup_password=None,
        user=SimpleNamespace(), db=AsyncMock(),
    )

    assert calls == ['lock', 'pre']
    assert result['success'] is True
