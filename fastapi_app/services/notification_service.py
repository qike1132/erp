"""
WebSocket 实时通知服务

基于 FastAPI WebSocket + Redis Pub/Sub 实现实时库存变更通知和操作冲突预警。
浏览器端通过 WebSocket 连接接收推送，轮询作为降级方案。
"""
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ==================== Redis Pub/Sub 事件定义 ====================

class StockEvent:
    """库存事件类型常量"""
    STOCK_CHANGED = "stock_changed"          # 库存变更
    ORDER_LOCKED = "order_locked"            # 订单锁定
    ORDER_UNLOCKED = "order_unlocked"        # 订单解锁
    APPROVAL_REQUESTED = "approval_requested"  # 审批请求
    APPROVAL_RESOLVED = "approval_resolved"    # 审批处理


def publish_stock_event(event_type: str, data: dict, redis_client=None):
    """
    发布库存事件到 Redis Pub/Sub 频道。

    供 service 层在库存/订单变更后调用。

    Args:
        event_type: 事件类型（StockEvent 常量）
        data: 事件数据字典
        redis_client: Redis 客户端（可选，默认从 utils.redis_cache 获取）
    """
    try:
        if redis_client is None:
            from utils.redis_cache import redis_client as _rc
            redis_client = _rc

        if redis_client is None:
            logger.debug("Redis 不可用，跳过事件发布")
            return

        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        redis_client.publish("erp:stock_events", json.dumps(event, ensure_ascii=False))
        logger.debug(f"事件已发布: {event_type}")
    except Exception as e:
        # 事件发布失败不应阻断业务流程
        logger.warning(f"事件发布失败: {e}")


# ==================== WebSocket 连接管理 ====================

class ConnectionManager:
    """
    WebSocket 连接管理器。

    管理所有活跃的 WebSocket 连接，支持按用户分组。
    当收到 Redis Pub/Sub 消息时，广播给所有连接的客户端。
    """

    def __init__(self):
        # user_id -> list[WebSocket]
        self.active_connections: dict[int, list] = {}
        self._redis_task = None

    async def connect(self, websocket, user_id: int):
        """接受新的 WebSocket 连接"""
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket 连接: user_id={user_id}, 当前连接数={len(self.active_connections)}")

    def disconnect(self, websocket, user_id: int):
        """断开 WebSocket 连接"""
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket 断开: user_id={user_id}, 当前连接数={len(self.active_connections)}")

    async def broadcast_event(self, event: dict):
        """向所有连接广播事件"""
        disconnected = []
        for user_id, connections in self.active_connections.items():
            for ws in connections:
                try:
                    await ws.send_json(event)
                except Exception:
                    disconnected.append((user_id, ws))

        for user_id, ws in disconnected:
            self.disconnect(ws, user_id)

    async def send_to_user(self, user_id: int, event: dict):
        """向特定用户发送事件"""
        connections = self.active_connections.get(user_id, [])
        for ws in list(connections):
            try:
                await ws.send_json(event)
            except Exception:
                self.disconnect(ws, user_id)


# 全局连接管理器实例
manager = ConnectionManager()
