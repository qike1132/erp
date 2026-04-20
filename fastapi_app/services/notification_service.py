"""
WebSocket 实时通知服务

基于 FastAPI WebSocket + Redis Pub/Sub 实现实时库存变更通知和操作冲突预警。
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ==================== Redis Pub/Sub 事件定义 ====================

class StockEvent:
    """库存事件类型常量"""
    STOCK_CHANGED = "stock_changed"
    SHIPMENT_PLAN_UPLOADED = "shipment_plan_uploaded"
    ORDER_LOCKED = "order_locked"
    ORDER_UNLOCKED = "order_unlocked"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"


EVENT_DISPLAY_MESSAGES = {
    "stock_changed": "库存数据已更新",
    "shipment_plan_uploaded": "新的出货计划已上传",
}

# 模块级共享同步 Redis 客户端（供 publish_stock_event 使用，避免每次创建新连接）
_sync_redis_client = None


def _get_sync_redis_client():
    """获取或创建模块级共享同步 Redis 客户端（延迟初始化，不主动ping）"""
    global _sync_redis_client
    if _sync_redis_client is not None:
        return _sync_redis_client

    try:
        import redis as sync_redis
        from fastapi_app.core.config import settings
        url = settings.REDIS_URL
        if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
            url = url.replace("redis://", f"redis://:{settings.REDIS_PASSWORD}@")
        _sync_redis_client = sync_redis.from_url(url)
        return _sync_redis_client
    except Exception as e:
        logger.warning("同步 Redis 客户端初始化失败: %s", e)
        return None


def _warmup_sync_redis():
    """预热同步 Redis 客户端（在启动时调用，建立连接避免首次请求延迟）"""
    global _sync_redis_client
    try:
        client = _get_sync_redis_client()
        if client:
            client.ping()  # 强制建立TCP连接
            logger.info("同步 Redis 客户端预热成功")
    except Exception as e:
        logger.warning(f"同步 Redis 客户端预热失败: {e}")
        _sync_redis_client = None


def publish_stock_event(event_type: str, data: dict, redis_client=None):
    """发布库存事件到 Redis Pub/Sub 频道。"""
    try:
        if redis_client is None:
            redis_client = _get_sync_redis_client()

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
        logger.warning(f"事件发布失败: {e}")


# ==================== WebSocket 连接管理 ====================

class ConnectionManager:
    """WebSocket 连接管理器 + Redis Pub/Sub 桥梁"""

    def __init__(self):
        self.active_connections: dict[int, list] = {}
        self._redis_task: Optional[asyncio.Task] = None
        self._async_redis = None
        self._pubsub = None
        self._redis_url = None

    async def connect(self, websocket, user_id: int):
        await websocket.accept()
        self._register(websocket, user_id)

    def connect_existing(self, websocket, user_id: int):
        """注册已 accept 的 WebSocket 连接（用于消息优先认证流程）"""
        self._register(websocket, user_id)

    def _register(self, websocket, user_id: int):
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket 连接: user_id={user_id}, 当前连接数={len(self.active_connections)}")

    def disconnect(self, websocket, user_id: int):
        if user_id in self.active_connections:
            self.active_connections[user_id].remove(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
        logger.info(f"WebSocket 断开: user_id={user_id}, 当前连接数={len(self.active_connections)}")

    async def broadcast_event(self, event: dict):
        # 快照当前连接，避免 await 期间其他协程修改字典导致 RuntimeError
        snapshot = list(self.active_connections.items())
        disconnected = []
        for user_id, connections in snapshot:
            for ws in connections:
                try:
                    await ws.send_json(event)
                except Exception:
                    logger.debug("WebSocket 广播发送失败，标记断开: user_id=%s", user_id)
                    disconnected.append((user_id, ws))
        for user_id, ws in disconnected:
            self.disconnect(ws, user_id)

    async def send_to_user(self, user_id: int, event: dict):
        connections = self.active_connections.get(user_id, [])
        for ws in list(connections):
            try:
                await ws.send_json(event)
            except Exception:
                logger.debug("WebSocket 定向发送失败，断开: user_id=%s", user_id)
                self.disconnect(ws, user_id)

    def _build_redis_url(self):
        """构建带密码的 Redis URL"""
        from fastapi_app.core.config import settings
        url = settings.REDIS_URL
        if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
            url = url.replace("redis://", f"redis://:{settings.REDIS_PASSWORD}@")
        return url

    async def start_redis_listener(self):
        """启动 Redis Pub/Sub 订阅，带自动重连"""
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.warning("redis.asyncio 不可用，跳过 Pub/Sub 订阅")
            return

        self._redis_url = self._build_redis_url()
        self._redis_task = asyncio.create_task(self._listen_loop())

    async def _listen_loop(self):
        """Redis 监听循环，断线自动重连"""
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
            except Exception as e:
                logger.error(f"Redis Pub/Sub 监听异常: {e}，5s 后重连")

            # 清理旧连接
            await self._cleanup_connections()

            if not self._redis_task or self._redis_task.done():
                break

            await asyncio.sleep(5)

    async def _cleanup_connections(self):
        if self._pubsub:
            try:
                await self._pubsub.unsubscribe("erp:stock_events")
                await self._pubsub.close()
            except Exception as e:
                logger.debug("PubSub 关闭异常（可忽略）: %s", e)
            self._pubsub = None
        if self._async_redis:
            try:
                await self._async_redis.close()
            except Exception as e:
                logger.debug("Redis 连接关闭异常（可忽略）: %s", e)
            self._async_redis = None

    async def stop_redis_listener(self):
        if self._redis_task and not self._redis_task.done():
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
        self._redis_task = None
        await self._cleanup_connections()
        logger.info("Redis Pub/Sub 订阅已停止")


# 全局连接管理器实例
manager = ConnectionManager()
