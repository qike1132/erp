"""
采购中心缓存统一管理

提供跨模块、跨进程的采购中心缓存失效机制：
- L1 进程内缓存：通过 register_purchase_cache 注册，invalidate_purchase_caches 清除
- 跨进程失效：通过 Redis Pub/Sub 广播失效信号，各 worker 订阅并清除本地缓存
"""

import asyncio
import contextlib
import json
import logging

logger = logging.getLogger(__name__)

_purchase_l1_caches: list[dict] = []
_listener_task: asyncio.Task | None = None
_listener_started = False

_CHANNEL = "erp:cache_invalidation"


def register_purchase_cache(cache: dict) -> None:
    """注册需要统一管理的采购中心 L1 缓存"""
    _purchase_l1_caches.append(cache)


async def invalidate_purchase_caches() -> int:
    """清除所有采购中心 L1 缓存 + core.cache 中的相关缓存，返回失效条数

    同时向 Redis Pub/Sub 发布跨进程失效信号，确保多 worker 部署下缓存一致。
    """
    count = 0
    for cache in _purchase_l1_caches:
        count += len(cache)
        cache.clear()
    try:
        from fastapi_app.core.cache import invalidate_local_cache
        count += invalidate_local_cache("orders:*")
    except Exception:
        pass

    await _async_publish_invalidation_signal()

    return count


async def _async_publish_invalidation_signal() -> None:
    """向 Redis Pub/Sub 发布缓存失效信号（异步版）"""
    try:
        from fastapi_app.services.notification_service import _get_async_redis_client
        client = await _get_async_redis_client()
        if client is None:
            return
        await client.publish(_CHANNEL, json.dumps({"scope": "purchase_caches"}))
    except Exception:
        pass


def _clear_all_local_caches() -> int:
    """仅清除本地 L1 缓存（不发布信号，避免循环）"""
    count = 0
    for cache in _purchase_l1_caches:
        count += len(cache)
        cache.clear()
    try:
        from fastapi_app.core.cache import invalidate_local_cache
        count += invalidate_local_cache("orders:*")
    except Exception:
        pass
    return count


async def start_purchase_cache_listener() -> None:
    """启动跨进程缓存失效监听器

    应在 FastAPI lifespan startup 中调用。
    订阅 Redis `erp:cache_invalidation` 频道，
    收到消息时清除本地 L1 缓存。
    """
    global _listener_task, _listener_started
    if _listener_started:
        return
    _listener_started = True
    _listener_task = asyncio.create_task(_listen_loop())
    logger.info("采购中心跨进程缓存失效监听器已启动")


async def stop_purchase_cache_listener() -> None:
    """停止跨进程缓存失效监听器"""
    global _listener_task, _listener_started
    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _listener_task
    _listener_task = None
    _listener_started = False


async def _listen_loop() -> None:
    """Redis Pub/Sub 监听循环：收到失效信号时清除本地缓存"""
    while True:
        redis_client = None
        pubsub = None
        try:
            import redis.asyncio as aioredis

            from fastapi_app.core.config import settings

            url = settings.REDIS_URL
            if settings.REDIS_PASSWORD and settings.REDIS_PASSWORD not in url:
                url = url.replace("redis://", f"redis://:{settings.REDIS_PASSWORD}@")

            redis_client = aioredis.from_url(url, decode_responses=True)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(_CHANNEL)

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        if data.get("scope") == "purchase_caches":
                            cleared = _clear_all_local_caches()
                            if cleared:
                                logger.debug("跨进程缓存失效：已清除 %d 条本地缓存", cleared)
                    except (json.JSONDecodeError, TypeError):
                        pass

        except asyncio.CancelledError:
            break
        except (OSError, ConnectionError, ValueError) as e:
            logger.warning("缓存失效监听异常: %s，5s 后重连", e)
            await asyncio.sleep(5)
        finally:
            try:
                if pubsub:
                    await pubsub.unsubscribe(_CHANNEL)
                    await pubsub.close()
            except Exception:
                pass
            try:
                if redis_client:
                    await redis_client.close()
            except Exception:
                pass
