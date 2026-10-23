"""P1-04 回归：还原锁的陈旧判定要看心跳，而不只看进度终态。

还原任务挂在 API 进程内；进程崩溃时进度停在 running，旧逻辑永远判不出陈旧，
锁要等 3600s TTL。现在 update_progress 写 heartbeat，超过 30 分钟未更新即视为
崩溃残留。
"""
import time
from unittest.mock import AsyncMock, patch

from fastapi_app.services.backup import restore as svc

_PATCH = 'fastapi_app.core.backup_progress.get_progress'


async def test_running_with_fresh_heartbeat_is_not_stale():
    with patch(_PATCH, AsyncMock(return_value={'status': 'running', 'heartbeat': time.time()})):
        assert await svc.is_stale_restore_lock('t1') is False


async def test_running_with_old_heartbeat_is_stale():
    with patch(_PATCH, AsyncMock(return_value={'status': 'running', 'heartbeat': time.time() - 3600})):
        assert await svc.is_stale_restore_lock('t2') is True


async def test_terminal_status_is_stale():
    with patch(_PATCH, AsyncMock(return_value={'status': 'completed'})):
        assert await svc.is_stale_restore_lock('t3') is True


async def test_missing_heartbeat_stays_conservative():
    with patch(_PATCH, AsyncMock(return_value={'status': 'running'})):
        assert await svc.is_stale_restore_lock('t4') is False
