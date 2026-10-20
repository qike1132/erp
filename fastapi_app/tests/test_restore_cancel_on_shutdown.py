"""P1-10：异步恢复任务被取消/停机时必须落失败终态并释放还原锁。

否则进度键停在中间态，is_stale_restore_lock 判不了陈旧锁，还原锁要占满 TTL。
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from fastapi_app.api.v1.endpoints.backup import _deps
from fastapi_app.api.v1.endpoints.backup import restore as restore_mod


async def test_cancel_background_restore_tasks_cancels_and_waits() -> None:
    cancelled_flags: list[int] = []
    started = asyncio.Event()
    started_count = 0

    async def _victim(idx: int) -> None:
        nonlocal started_count
        started_count += 1
        if started_count == 2:
            started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled_flags.append(idx)
            raise

    t1 = asyncio.create_task(_victim(1))
    t2 = asyncio.create_task(_victim(2))
    _deps._background_tasks.update({t1, t2})
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        count = await _deps.cancel_background_restore_tasks(timeout=5.0)
        assert count == 2
        assert t1.cancelled() and t2.cancelled()
        assert sorted(cancelled_flags) == [1, 2]
    finally:
        for t in (t1, t2):
            if not t.done():
                t.cancel()
        await asyncio.gather(t1, t2, return_exceptions=True)
        _deps._background_tasks.difference_update({t1, t2})


async def test_cancelled_restore_writes_failed_progress_and_releases_lock(monkeypatch) -> None:
    from fastapi_app.core import backup_progress, database

    entered = asyncio.Event()

    @asynccontextmanager
    async def fake_db_ctx():
        yield AsyncMock()

    async def blocking_pre(db, allowed, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    fail_calls: list[tuple[str, str]] = []

    async def fake_fail(task_id: str, error: str) -> None:
        fail_calls.append((task_id, error))

    async def fake_update(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(database, 'get_async_db_context', fake_db_ctx)
    monkeypatch.setattr(backup_progress, 'fail_progress', fake_fail)
    monkeypatch.setattr(backup_progress, 'update_progress', fake_update)
    monkeypatch.setattr(restore_mod, '_pre_restore_info_or_fail', blocking_pre)
    monkeypatch.setattr(restore_mod.backup_service, 'renew_restore_lock', AsyncMock(return_value=True))
    release = AsyncMock()
    monkeypatch.setattr(restore_mod.backup_service, 'release_restore_lock', release)

    task = asyncio.create_task(
        restore_mod._run_async_file_restore('task-cancel', b'', False, 'f.zip')
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    assert any('中断' in err for _, err in fail_calls), fail_calls
    release.assert_awaited_with('task-cancel')
