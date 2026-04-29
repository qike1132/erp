"""
Redis 缓存管理器 - 全异步版本

使用 redis.asyncio.Redis 替代同步 redis.Redis，
消除 FastAPI 异步事件循环中的阻塞调用。
"""
import redis
import redis.asyncio as aioredis
import json
import hashlib
import os
import time
import logging
import asyncio
from functools import wraps
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RedisCacheManager:
    """异步 Redis 缓存管理器"""

    FALLBACK_MAX_SIZE = 1000

    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.default_timeout = 300
        import socket
        instance_id = os.getenv("HOSTNAME", socket.gethostname())[:20]
        self.key_prefix = f'erp:{instance_id}:'
        self._fallback_cache: dict[str, Any] = {}
        self._fallback_timestamps: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def init_app(self, app=None, redis_url: str = None, redis_host: str = 'localhost',
                       redis_port: int = 6379, redis_db: int = 0, redis_password: str = None,
                       default_timeout: int = 300, key_prefix: str = 'erp:'):
        if app is not None:
            redis_url = redis_url or app.config.get('REDIS_URL') or os.getenv('REDIS_URL')
            redis_host = app.config.get('REDIS_HOST', os.getenv('REDIS_HOST', 'localhost'))
            redis_port = int(app.config.get('REDIS_PORT', os.getenv('REDIS_PORT', 6379)))
            redis_db = int(app.config.get('REDIS_DB', os.getenv('REDIS_DB', 0)))
            redis_password = app.config.get('REDIS_PASSWORD', os.getenv('REDIS_PASSWORD'))
            default_timeout = app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
            key_prefix = app.config.get('CACHE_KEY_PREFIX', 'erp:')

        if redis_url:
            try:
                self.redis_client = aioredis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    max_connections=100
                )
                await self.redis_client.ping()
                logger.info("Redis 异步连接成功: %s", redis_url)
            except (redis.ConnectionError, Exception) as e:
                logger.warning("Redis 异步连接失败，将使用内存缓存: %s", e)
                self.redis_client = None
        else:
            try:
                self.redis_client = aioredis.Redis(
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    max_connections=100
                )
                await self.redis_client.ping()
                logger.info("Redis 异步连接成功: %s:%s", redis_host, redis_port)
            except (redis.ConnectionError, Exception) as e:
                logger.warning("Redis 异步连接失败，将使用内存缓存: %s", e)
                self.redis_client = None

        self.default_timeout = default_timeout
        self.key_prefix = key_prefix

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    def _cleanup_fallback(self):
        # 惰性清理：仅在缓存条目数超过阈值的 80% 时才执行过期清理
        if len(self._fallback_cache) < int(self.FALLBACK_MAX_SIZE * 0.8):
            return

        now = time.time()
        expired_keys = [k for k, ts in self._fallback_timestamps.items()
                        if now - ts > self.default_timeout]
        for k in expired_keys:
            self._fallback_cache.pop(k, None)
            del self._fallback_timestamps[k]

        if len(self._fallback_cache) > self.FALLBACK_MAX_SIZE:
            sorted_keys = sorted(self._fallback_timestamps.items(), key=lambda x: x[1])
            keys_to_remove = sorted_keys[:len(sorted_keys) // 2]
            for k, _ in keys_to_remove:
                self._fallback_cache.pop(k, None)
                del self._fallback_timestamps[k]

    async def get(self, key: str) -> Optional[Any]:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                value = await self.redis_client.get(full_key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.warning("Redis async get error: %s", e)

        async with self._lock:
            ts = self._fallback_timestamps.get(full_key)
            if ts is not None and time.time() - ts > self.default_timeout:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return None
            return self._fallback_cache.get(full_key)

    async def set(self, key: str, value: Any, timeout: int = None) -> bool:
        full_key = self._make_key(key)
        timeout = timeout or self.default_timeout

        if self.redis_client:
            try:
                serialized = json.dumps(value, ensure_ascii=False)
                return await self.redis_client.setex(full_key, timeout, serialized)
            except Exception as e:
                logger.warning("Redis async set error: %s", e)

        async with self._lock:
            self._fallback_cache[full_key] = value
            self._fallback_timestamps[full_key] = time.time()
            self._cleanup_fallback()
        return True

    async def delete(self, key: str) -> bool:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                await self.redis_client.delete(full_key)
            except Exception as e:
                logger.warning("Redis async delete error: %s", e)

        async with self._lock:
            self._fallback_cache.pop(full_key, None)
            self._fallback_timestamps.pop(full_key, None)
        return True

    async def delete_pattern(self, pattern: str) -> int:
        full_pattern = self._make_key(pattern)
        deleted_count = 0

        if self.redis_client:
            try:
                cursor = 0
                max_iterations = 1000
                iterations = 0
                while True:
                    cursor, keys = await self.redis_client.scan(
                        cursor=cursor, match=full_pattern, count=100
                    )
                    if keys:
                        deleted_count += await self.redis_client.delete(*keys)
                    iterations += 1
                    if cursor == 0 or iterations >= max_iterations:
                        break
                if iterations >= max_iterations:
                    logger.warning("delete_pattern 达到迭代上限 %d，模式: %s", max_iterations, full_pattern)
            except Exception as e:
                logger.warning("Redis async delete_pattern error: %s", e)

        async with self._lock:
            prefix = full_pattern.replace('*', '')
            keys_to_delete = [k for k in self._fallback_cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._fallback_cache[key]
                self._fallback_timestamps.pop(key, None)
                deleted_count += 1

        return deleted_count

    async def exists(self, key: str) -> bool:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return bool(await self.redis_client.exists(full_key))
            except Exception as e:
                logger.warning("Redis async exists error: %s", e)

        async with self._lock:
            ts = self._fallback_timestamps.get(full_key)
            if ts is not None and time.time() - ts > self.default_timeout:
                self._fallback_cache.pop(full_key, None)
                del self._fallback_timestamps[full_key]
                return False
            return full_key in self._fallback_cache

    async def incr(self, key: str) -> int:
        full_key = self._make_key(key)

        if self.redis_client:
            try:
                return await self.redis_client.incr(full_key)
            except Exception as e:
                logger.warning("Redis async incr error: %s", e)

        async with self._lock:
            current = self._fallback_cache.get(full_key, 0)
            new_value = current + 1
            self._fallback_cache[full_key] = new_value
            self._fallback_timestamps[full_key] = time.time()
            return new_value

    async def get_stats(self) -> dict:
        stats = {
            'backend': 'redis' if self.redis_client else 'memory',
            'connected': self.redis_client is not None
        }

        if self.redis_client:
            try:
                info = await self.redis_client.info()
                stats.update({
                    'connected_clients': info.get('connected_clients', 0),
                    'used_memory_human': info.get('used_memory_human', '0B'),
                    'total_commands_processed': info.get('total_commands_processed', 0),
                    'keyspace_hits': info.get('keyspace_hits', 0),
                    'keyspace_misses': info.get('keyspace_misses', 0),
                })
            except Exception as e:
                stats['error'] = str(e)
        else:
            stats['fallback_cache_size'] = len(self._fallback_cache)

        return stats

    async def close(self):
        if self.redis_client:
            try:
                await self.redis_client.aclose()
            except Exception as e:
                logger.warning("Redis async close error: %s", e)
            self.redis_client = None


redis_cache = RedisCacheManager()


def redis_cached(timeout: int = 300, key_prefix: str = None):
    """异步 Redis 缓存装饰器，支持 async 和 sync 函数"""
    def decorator(f):
        is_async = asyncio.iscoroutinefunction(f)

        if is_async:
            @wraps(f)
            async def async_wrapper(*args, **kwargs):
                cache_key = _generate_cache_key(f, key_prefix, args, kwargs)
                result = await redis_cache.get(cache_key)
                if result is not None:
                    return result
                result = await f(*args, **kwargs)
                if result is not None:
                    await redis_cache.set(cache_key, result, timeout)
                return result
            return async_wrapper
        else:
            @wraps(f)
            def sync_wrapper(*args, **kwargs):
                cache_key = _generate_cache_key(f, key_prefix, args, kwargs)
                import asyncio as _aio
                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    result = _aio.run_coroutine_threadsafe(
                        redis_cache.get(cache_key), loop
                    ).result(timeout=5)
                else:
                    result = _aio.run(redis_cache.get(cache_key))

                if result is not None:
                    return result

                result = f(*args, **kwargs)

                if result is not None:
                    if loop and loop.is_running():
                        _aio.run_coroutine_threadsafe(
                            redis_cache.set(cache_key, result, timeout), loop
                        )
                    else:
                        _aio.run(redis_cache.set(cache_key, result, timeout))

                return result
            return sync_wrapper
    return decorator


def cache_invalidate(*key_patterns):
    """缓存失效装饰器，支持 async 和 sync 函数"""
    def decorator(f):
        is_async = asyncio.iscoroutinefunction(f)

        if is_async:
            @wraps(f)
            async def async_wrapper(*args, **kwargs):
                result = await f(*args, **kwargs)
                for pattern in key_patterns:
                    await redis_cache.delete_pattern(pattern)
                return result
            return async_wrapper
        else:
            @wraps(f)
            def sync_wrapper(*args, **kwargs):
                result = f(*args, **kwargs)
                import asyncio as _aio
                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    loop = None
                for pattern in key_patterns:
                    if loop and loop.is_running():
                        _aio.run_coroutine_threadsafe(
                            redis_cache.delete_pattern(pattern), loop
                        )
                    else:
                        _aio.run(redis_cache.delete_pattern(pattern))
                return result
            return sync_wrapper
    return decorator


def _generate_cache_key(f, key_prefix: str, args: tuple, kwargs: dict) -> str:
    if key_prefix is None:
        key_prefix = f.__name__
    args_str = _hash_args(args, kwargs)
    return f"{key_prefix}:{args_str}"


def _hash_args(args: tuple, kwargs: dict) -> str:
    try:
        args_json = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True)
        return hashlib.sha256(args_json.encode()).hexdigest()[:16]
    except Exception:
        raw = str(args) + str(kwargs)
        return hashlib.md5(raw.encode()).hexdigest()[:16]


class CacheConfig:
    PRODUCT_LIST = ('product:list', 600)
    PRODUCT_DETAIL = ('product:detail', 1800)
    PRODUCT_SEARCH = ('product:search', 300)
    INVENTORY_STATS = ('inventory:stats', 300)
    STOCK_LIST = ('stock:list', 600)
    ORDER_LIST = ('order:list', 300)
    ORDER_STATS = ('order:stats', 300)
    USER_PERMISSIONS = ('user:permissions', 3600)
    USER_PROFILE = ('user:profile', 1800)
    REPORT_DATA = ('report:data', 600)
