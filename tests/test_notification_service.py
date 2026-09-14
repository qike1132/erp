"""
notification_service 模块单元测试

覆盖：ConnectionManager 连接/断开/广播/定向发送、publish_stock_event
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.notification_service import (
    EVENT_DISPLAY_MESSAGES,
    ConnectionManager,
    StockEvent,
    publish_stock_event,
)

# ============================================================
# ConnectionManager — 连接管理
# ============================================================

class TestConnectionManager:
    def setup_method(self):
        self.mgr = ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_accepts_and_registers(self):
        ws = AsyncMock()
        await self.mgr.connect(ws, user_id=1)
        assert 1 in self.mgr.active_connections
        assert ws in self.mgr.active_connections[1]
        ws.accept.assert_awaited_once()

    def test_connect_existing_does_not_accept(self):
        ws = MagicMock()
        self.mgr.connect_existing(ws, user_id=2)
        assert 2 in self.mgr.active_connections
        assert ws in self.mgr.active_connections[2]
        # connect_existing should NOT call accept
        assert not hasattr(ws, 'accept') or not ws.accept.called

    def test_disconnect_removes_ws(self):
        ws = MagicMock()
        self.mgr.active_connections[1] = [ws]
        self.mgr.disconnect(ws, user_id=1)
        assert 1 not in self.mgr.active_connections

    def test_disconnect_keeps_other_connections(self):
        ws1 = MagicMock()
        ws2 = MagicMock()
        self.mgr.active_connections[1] = [ws1, ws2]
        self.mgr.disconnect(ws1, user_id=1)
        assert ws2 in self.mgr.active_connections[1]

    def test_disconnect_nonexistent_user_no_error(self):
        ws = MagicMock()
        self.mgr.disconnect(ws, user_id=999)  # should not raise


# ============================================================
# ConnectionManager — 广播和定向发送
# ============================================================

class TestConnectionManagerBroadcast:
    def setup_method(self):
        self.mgr = ConnectionManager()

    @pytest.mark.asyncio
    async def test_broadcast_sends_to_all(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        self.mgr.active_connections[1] = [ws1]
        self.mgr.active_connections[2] = [ws2]

        event = {"type": "test", "data": {}}
        await self.mgr.broadcast_event(event)

        ws1.send_json.assert_awaited_once_with(event)
        ws2.send_json.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_broadcast_disconnects_failed_ws(self):
        ws_good = AsyncMock()
        ws_bad = AsyncMock()
        ws_bad.send_json.side_effect = RuntimeError('Cannot call "send" once a close message has been sent.')
        self.mgr.active_connections[1] = [ws_good, ws_bad]

        await self.mgr.broadcast_event({"type": "test"})
        assert ws_bad not in self.mgr.active_connections.get(1, [])

    @pytest.mark.asyncio
    async def test_send_to_user(self):
        ws = AsyncMock()
        self.mgr.active_connections[5] = [ws]

        event = {"type": "stock_changed", "data": {"product_id": 1}}
        await self.mgr.send_to_user(5, event)
        ws.send_json.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_send_to_user_no_connections(self):
        """无连接时不报错"""
        await self.mgr.send_to_user(999, {"type": "test"})


# ============================================================
# publish_stock_event
# ============================================================

class TestPublishStockEvent:
    @pytest.mark.asyncio
    async def test_publishes_to_redis(self):
        mock_redis = AsyncMock()
        await publish_stock_event(
            StockEvent.STOCK_CHANGED,
            {"product_id": 1, "delta": 10},
            redis_client=mock_redis,
        )
        mock_redis.publish.assert_awaited_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "erp:stock_events"
        payload = json.loads(call_args[0][1])
        assert payload["type"] == StockEvent.STOCK_CHANGED
        assert payload["data"]["product_id"] == 1

    @pytest.mark.asyncio
    async def test_no_redis_does_not_raise(self):
        """Redis 不可用时静默跳过"""
        with patch("fastapi_app.services.notification_service._get_async_redis_client",
                    return_value=None):
            await publish_stock_event("test_event", {"key": "val"})


# ============================================================
# 常量完整性检查
# ============================================================

class TestEventConstants:
    def test_stock_event_constants(self):
        assert StockEvent.STOCK_CHANGED == "stock_changed"
        assert StockEvent.SHIPMENT_PLAN_UPLOADED == "shipment_plan_uploaded"
        assert StockEvent.ORDER_LOCKED == "order_locked"

    def test_display_messages_keys(self):
        assert "stock_changed" in EVENT_DISPLAY_MESSAGES
        assert "shipment_plan_uploaded" in EVENT_DISPLAY_MESSAGES
