"""
WebSocket 实时通知服务 - 全异步版本

基于 FastAPI WebSocket + Redis Pub/Sub 实现实时库存变更通知和操作冲突预警。
所有 Redis 操作均使用 redis.asyncio，消除事件循环阻塞。
"""
import asyncio
import contextlib
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class StockEvent:
    STOCK_CHANGED = "stock_changed"
    SHIPMENT_PLAN_UPLOADED = "shipment_plan_uploaded"
    ORDER_LOCKED = "order_locked"
    ORDER_UNLOCKED = "order_unlocked"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    ORDER_CREATED = "order_created"
    ORDER_UPDATED = "order_updated"
    ORDER_DELETED = "order_deleted"
    PURCHASE_ORDER_CREATED = "purchase_order_created"


EVENT_DISPLAY_MESSAGES = {
    "stock_changed": "库存数据已更新",
    "shipment_plan_uploaded": "新的出货计划已上传",
    "order_created": "新订单已创建",
    "order_updated": "订单信息已更新",
    "order_deleted": "订单已删除",
    "purchase_order_created": "新采购订单已生成",
}

_async_redis_client = None


async def _get_async_redis_client():
    """获取或创建模块级共享异步 Redis 客户端"""
    global _async_redis_client
    if _async_redis_client is not None:
        return _async_redis_client

    try:
        import redis.asyncio as aioredis

        from fastapi_app.core.config import settings
        url = settings.REDIS_URL
        if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
            url = url.replace("redis://", f"redis://:{settings.REDIS_PASSWORD}@")
        _async_redis_client = aioredis.from_url(url)
        return _async_redis_client
    except (ImportError, OSError, ValueError) as e:
        logger.warning("异步 Redis 客户端初始化失败: %s", e)
        return None


async def _warmup_async_redis():
    """预热异步 Redis 客户端"""
    global _async_redis_client
    try:
        client = await _get_async_redis_client()
        if client:
            await client.ping()
            logger.info("异步 Redis 客户端预热成功")
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning("异步 Redis 客户端预热失败: %s", e)
        _async_redis_client = None


async def publish_stock_event(event_type: str, data: dict, redis_client=None):
    """发布库存事件到 Redis Pub/Sub 频道（异步）"""
    try:
        if redis_client is None:
            redis_client = await _get_async_redis_client()

        if redis_client is None:
            logger.debug("Redis 不可用，跳过事件发布")
            return

        event = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat(),
        }
        await redis_client.publish("erp:stock_events", json.dumps(event, ensure_ascii=False))
        logger.debug("事件已发布: %s", event_type)
    except (OSError, ConnectionError, ValueError) as e:
        logger.warning("事件发布失败: %s", e)


class ConnectionManager:
    """WebSocket 连接管理器 + Redis Pub/Sub 桥梁"""

    def __init__(self):
        self.active_connections: dict[int, list] = {}
        self._redis_task: asyncio.Task | None = None
        self._async_redis = None
        self._pubsub = None
        self._redis_url = None

    async def connect(self, websocket, user_id: int):
        await websocket.accept()
        self._register(websocket, user_id)

    def connect_existing(self, websocket, user_id: int):
        self._register(websocket, user_id)

    def _register(self, websocket, user_id: int):
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info("WebSocket 连接: user_id=%s, 当前连接数=%s", user_id, len(self.active_connections))

    def disconnect(self, websocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info("WebSocket 断开: user_id=%s, 当前连接数=%s", user_id, len(self.active_connections))

    async def broadcast_event(self, event: dict):
        snapshot = list(self.active_connections.items())
        disconnected = []
        for user_id, connections in snapshot:
            for ws in connections:
                try:
                    await ws.send_json(event)
                except RuntimeError:
                    logger.debug("WebSocket 广播发送失败，标记断开: user_id=%s", user_id)
                    disconnected.append((user_id, ws))
        for user_id, ws in disconnected:
            self.disconnect(ws, user_id)

    async def send_to_user(self, user_id: int, event: dict):
        connections = self.active_connections.get(user_id, [])
        for ws in list(connections):
            try:
                await ws.send_json(event)
            except RuntimeError:
                logger.debug("WebSocket 定向发送失败，断开: user_id=%s", user_id)
                self.disconnect(ws, user_id)

    def _build_redis_url(self):
        from fastapi_app.core.config import settings
        url = settings.REDIS_URL
        if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
            url = url.replace("redis://", f"redis://:{settings.REDIS_PASSWORD}@")
        return url

    async def start_redis_listener(self):

        self._redis_url = self._build_redis_url()
        self._redis_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        import redis.asyncio as aioredis

        while True:
            try:
                self._async_redis = aioredis.from_url(
                    self._redis_url, decode_responses=True
                )
                self._pubsub = self._async_redis.pubsub()
                await self._pubsub.subscribe("erp:stock_events")
                logger.info("Redis Pub/Sub 订阅已启动: erp:stock_events")

                async for message in self._pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        event = json.loads(data)
                        if "message" not in event:
                            event["message"] = EVENT_DISPLAY_MESSAGES.get(
                                event.get("type", ""), "收到新通知"
                            )
                        await self.broadcast_event(event)

            except asyncio.CancelledError:
                logger.info("Redis Pub/Sub 监听任务已取消")
                break
            except (OSError, ConnectionError, ValueError) as e:
                logger.error("Redis Pub/Sub 监听异常: %s，5s 后重连", e)

            await self._cleanup_connections()

            if not self._redis_task or self._redis_task.done():
                break

            await asyncio.sleep(5)

    async def _cleanup_connections(self):
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe("erp:stock_events")
                await self._pubsub.close()
            except (OSError, ConnectionError) as e:
                logger.debug("PubSub 关闭异常（可忽略）: %s", e)
            self._pubsub = None
        if self._async_redis:
            try:
                await self._async_redis.close()
            except (OSError, ConnectionError) as e:
                logger.debug("Redis 连接关闭异常（可忽略）: %s", e)
            self._async_redis = None

    async def stop_redis_listener(self):
        if self._redis_task and not self._redis_task.done():
            self._redis_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._redis_task
        self._redis_task = None
        await self._cleanup_connections()
        logger.info("Redis Pub/Sub 订阅已停止")


manager = ConnectionManager()
