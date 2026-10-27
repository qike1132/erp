"""WebSocket 授权、撤销与慢客户端隔离回归。"""
from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from fastapi_app.api import ws as ws_module
from fastapi_app.services import notification_service
from fastapi_app.services.notification_service import ConnectionManager, StockEvent


class _Principal:
    def __init__(self, *codes: str, factory: str | None = None, is_super: bool = False):
        self.codes = frozenset(codes)
        self.factory = factory
        self.is_super = is_super

    def has_permission(self, code: str) -> bool:
        return self.is_super or code in self.codes


@pytest.mark.asyncio
async def test_broadcast_enforces_permission_and_factory_scope():
    manager = ConnectionManager()
    allowed = AsyncMock()
    wrong_permission = AsyncMock()
    wrong_factory = AsyncMock()
    superuser = AsyncMock()
    manager.connect_existing(allowed, 1, principal=_Principal('stock_view', factory='湖北'))
    manager.connect_existing(wrong_permission, 2, principal=_Principal('case_manage', factory='湖北'))
    manager.connect_existing(wrong_factory, 3, principal=_Principal('stock_view', factory='东莞'))
    manager.connect_existing(superuser, 4, principal=_Principal(factory='东莞', is_super=True))

    event = {
        'type': StockEvent.STOCK_CHANGED,
        'data': {'product_id': 7, 'factory': '湖北', 'current_stock': 3},
    }
    await manager.broadcast_event(event)

    allowed.send_json.assert_awaited_once_with(event)
    wrong_permission.send_json.assert_not_awaited()
    wrong_factory.send_json.assert_not_awaited()
    superuser.send_json.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_unknown_event_is_denied_by_default():
    manager = ConnectionManager()
    ws = AsyncMock()
    manager.connect_existing(ws, 1, principal=_Principal('stock_view'))

    await manager.broadcast_event({'type': 'unregistered-event', 'data': {}})

    ws.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_slow_client_does_not_block_other_recipients(monkeypatch):
    manager = ConnectionManager()
    slow = AsyncMock()
    fast = AsyncMock()
    async def _hang(_event):
        await asyncio.Event().wait()

    slow.send_json.side_effect = _hang
    manager.connect_existing(slow, 1, principal=_Principal('stock_view'))
    manager.connect_existing(fast, 2, principal=_Principal('stock_view'))
    monkeypatch.setattr(notification_service, '_WS_SEND_TIMEOUT_SECONDS', 0.02)

    await asyncio.wait_for(
        manager.broadcast_event({'type': StockEvent.STOCK_CHANGED, 'data': {}}),
        timeout=0.5,
    )

    fast.send_json.assert_awaited_once()
    assert 1 not in manager.active_connections


@pytest.mark.asyncio
async def test_revoked_or_expired_auth_context_is_rejected(monkeypatch):
    revoked = AsyncMock(return_value=True)
    monkeypatch.setattr('fastapi_app.core.deps.is_token_revoked', revoked)

    assert not await ws_module._token_auth_valid({'jti': 'revoked', 'exp': time.time() + 60})
    assert not await ws_module._token_auth_valid({'jti': 'valid', 'exp': time.time() - 1})


@pytest.mark.asyncio
async def test_ws_ticket_preserves_session_revocation_context(monkeypatch):
    ws_module._WS_PENDING_TICKETS.clear()
    monkeypatch.setattr('fastapi_app.core.redis_wrapper.safe_set', AsyncMock())
    monkeypatch.setattr('fastapi_app.core.redis_wrapper.safe_delete', AsyncMock())
    auth = {'jti': 'session-jti', 'exp': int(time.time()) + 60}

    ticket = await ws_module._issue_ws_ticket(1, auth)
    consumed = await ws_module._consume_ws_ticket(ticket)

    assert consumed == (1, auth)
    ws_module._WS_PENDING_TICKETS.clear()


@pytest.mark.asyncio
async def test_redis_only_ticket_restores_auth_context(monkeypatch):
    """另一 worker 只有 Redis 副本时，也必须继承同一会话撤销上下文。"""
    ws_module._WS_PENDING_TICKETS.clear()
    auth = {'jti': 'shared-jti', 'exp': int(time.time()) + 60}
    monkeypatch.setattr(
        'fastapi_app.core.redis_wrapper.safe_get',
        AsyncMock(return_value=json.dumps({'user_id': 9, 'auth': auth})),
    )
    monkeypatch.setattr('fastapi_app.core.redis_wrapper.safe_delete', AsyncMock())

    assert await ws_module._consume_ws_ticket('shared-ticket') == (9, auth)
