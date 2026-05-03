"""
智能缓存管理器
提供多级缓存自动管理、缓存预热、降级策略等高级功能 (FastAPI 兼容版本)
"""
import asyncio
import functools
import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    import xxhash
    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """缓存统计"""
    hits: int = 0
    misses: int = 0
    sets: int = 0
    deletes: int = 0
    evictions: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_hit(self):
        with self._lock:
            self.hits += 1

    def record_miss(self):
        with self._lock:
            self.misses += 1

    def record_set(self):
        with self._lock:
            self.sets += 1

    def record_delete(self):
        with self._lock:
            self.deletes += 1

    def record_eviction(self):
        with self._lock:
            self.evictions += 1

    def record_error(self):
        with self._lock:
            self.errors += 1

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    def to_dict(self) -> dict[str, Any]:
        return {
            'hits': self.hits,
            'misses': self.misses,
            'sets': self.sets,
            'deletes': self.deletes,
            'evictions': self.evictions,
            'errors': self.errors,
            'hit_rate': f"{self.hit_rate:.2f}%",
            'total_requests': self.total_requests
        }

    def reset(self):
        with self._lock:
            self.hits = 0
            self.misses = 0
            self.sets = 0
            self.deletes = 0
            self.evictions = 0
            self.errors = 0


class LRUCache:
    """LRU 缓存实现（使用 OrderedDict 实现 O(1) 操作，支持 TTL）"""

    def __init__(self, maxsize: int = 1000):
        self.maxsize = maxsize
        from collections import OrderedDict
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()  # key -> (value, expire_at)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._cache:
                value, expire_at = self._cache[key]
                # 检查 TTL 过期
                if expire_at is not None and time.time() > expire_at:
                    del self._cache[key]
                    return None
                self._cache.move_to_end(key)  # O(1) LRU 更新
                return value
            return None

    def set(self, key: str, value: Any, ttl: int | None = None):
        with self._lock:
            expire_at = time.time() + ttl if ttl is not None else None
            if key in self._cache:
                self._cache.move_to_end(key)
            elif len(self._cache) >= self.maxsize:
                self._cache.popitem(last=False)  # O(1) 淘汰最旧

            self._cache[key] = (value, expire_at)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self):
        with self._lock:
            self._cache.clear()

    def __contains__(self, key: str) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)


class SmartCacheManager:
    """智能缓存管理器"""

    def __init__(self,
                 max_memory_size: int = 1000,
                 default_ttl: int = 300,
                 enable_fallback: bool = True):
        self.local_cache = LRUCache(maxsize=max_memory_size)
        self.default_ttl = default_ttl
        self.enable_fallback = enable_fallback
        self.stats = CacheStats()
        self._redis_client = None
        self._is_redis_available = None

        logger.info(f"智能缓存管理器已初始化 (内存缓存: {max_memory_size} 条)")

    def _get_redis_client(self):
        if self._is_redis_available is not None:
            return self._redis_client

        try:
            from utils.redis_cache import redis_cache
            if redis_cache and redis_cache.redis_client:
                self._redis_client = redis_cache
                self._is_redis_available = True
                return self._redis_client
        except Exception:
            pass

        self._is_redis_available = False
        return None

    def get(self, key: str, default: Any = None,
            use_local: bool = True, use_redis: bool = True) -> Any:
        cache_key = self._make_key(key)

        if use_local:
            value = self.local_cache.get(cache_key)
            if value is not None:
                self.stats.record_hit()
                return value

        redis_client = self._get_redis_client()
        if use_redis and redis_client:
            try:
                value = redis_client.get(cache_key)
                if value is not None:
                    if use_local:
                        self.local_cache.set(cache_key, value)
                    self.stats.record_hit()
                    return value
            except Exception as e:
                logger.warning(f"Redis 读取失败: {e}")
                self.stats.record_error()

        self.stats.record_miss()
        return default

    def set(self, key: str, value: Any, ttl: int | None = None,
            use_local: bool = True, use_redis: bool = True) -> bool:
        if ttl is None:
            ttl = self.default_ttl

        cache_key = self._make_key(key)

        if use_local:
            self.local_cache.set(cache_key, value)

        redis_client = self._get_redis_client()
        if use_redis and redis_client:
            try:
                redis_client.set(cache_key, value, ttl)
                self.stats.record_set()
                return True
            except Exception as e:
                logger.warning(f"Redis 写入失败: {e}")
                self.stats.record_error()
                return False

        self.stats.record_set()
        return True

    def delete(self, key: str, use_local: bool = True, use_redis: bool = True) -> bool:
        cache_key = self._make_key(key)
        deleted = False

        if use_local and self.local_cache.delete(cache_key):
            deleted = True

        redis_client = self._get_redis_client()
        if use_redis and redis_client:
            try:
                redis_client.delete(cache_key)
                deleted = True
            except Exception as e:
                logger.warning(f"Redis 删除失败: {e}")
                self.stats.record_error()

        if deleted:
            self.stats.record_delete()
        return deleted

    async def delete_by_pattern(self, pattern: str) -> int:
        count = 0
        redis_client = self._get_redis_client()

        if redis_client:
            try:
                count = await redis_client.delete_pattern(pattern)
            except Exception as e:
                logger.warning(f"Redis 批量删除失败: {e}")
                self.stats.record_error()

        # Also clear matching local cache entries
        prefix = pattern.replace('*', '')
        keys_to_delete = [k for k in list(self.local_cache._cache.keys()) if prefix in k]
        for k in keys_to_delete:
            self.local_cache.delete(k)
            count += 1

        return count

    async def clear(self, use_local: bool = True, use_redis: bool = True):
        if use_local:
            self.local_cache.clear()

        redis_client = self._get_redis_client()
        if use_redis and redis_client:
            try:
                await redis_client.delete_pattern('*')
            except Exception as e:
                logger.warning(f"Redis 清空失败: {e}")
                self.stats.record_error()

    def get_stats(self) -> dict[str, Any]:
        stats = self.stats.to_dict()
        stats['local_cache_size'] = len(self.local_cache)
        redis_client = self._get_redis_client()
        stats['redis_available'] = redis_client is not None
        return stats

    @staticmethod
    def _make_key(key: str) -> str:
        if len(key) > 100:
            if HAS_XXHASH:
                return f"smart:{xxhash.xxh64(key).hexdigest()}"
            else:
                return f"smart:{hashlib.md5(key.encode()).hexdigest()}"
        return f"smart:{key}"


smart_cache = SmartCacheManager()


def smart_cached(ttl: int = 300, key_prefix: str = "smart",
                 cache_none: bool = True,
                 condition: Callable | None = None,
                 tags: list[str] | None = None,
                 use_async: bool = False):
    """智能缓存装饰器"""
    def decorator(func: Callable) -> Callable:
        if use_async:
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                if condition and not condition(*args, **kwargs):
                    return await func(*args, **kwargs)

                cache_key = _generate_cache_key(key_prefix, func, args, kwargs)

                result = smart_cache.get(cache_key)
                if result is not None:
                    return result

                result = await func(*args, **kwargs)

                if result is not None or cache_none:
                    smart_cache.set(cache_key, result, ttl=ttl)

                return result
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                if condition and not condition(*args, **kwargs):
                    return func(*args, **kwargs)

                cache_key = _generate_cache_key(key_prefix, func, args, kwargs)

                result = smart_cache.get(cache_key)
                if result is not None:
                    return result

                result = func(*args, **kwargs)

                if result is not None or cache_none:
                    smart_cache.set(cache_key, result, ttl=ttl)

                return result
            return sync_wrapper

    return decorator


def _generate_cache_key(prefix: str, func: Callable, args: tuple, kwargs: dict) -> str:
    key_parts = [prefix, func.__module__, func.__qualname__]

    for arg in args:
        key_parts.append(str(arg))

    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")

    key_str = ":".join(key_parts)

    if HAS_XXHASH:
        key_hash = xxhash.xxh64(key_str.encode()).hexdigest()[:16]
    else:
        key_hash = hashlib.md5(key_str.encode()).hexdigest()[:16]

    return f"{prefix}:{func.__name__}:{key_hash}"


class CacheWarmupManager:
    """缓存预热管理器"""

    def __init__(self, cache_manager: SmartCacheManager = None):
        self.cache = cache_manager or smart_cache
        self.warmup_tasks: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def register_task(self, name: str, func: Callable, ttl: int = 3600,
                      interval: int = 300, priority: int = 10):
        with self._lock:
            self.warmup_tasks.append({
                'name': name,
                'function': func,
                'ttl': ttl,
                'interval': interval,
                'priority': priority,
                'last_run': None,
                'status': 'pending'
            })
            self.warmup_tasks.sort(key=lambda x: x['priority'])
        logger.info(f"注册预热任务: {name} (优先级: {priority})")

    async def warmup_all(self):
        tasks = []
        with self._lock:
            for task in self.warmup_tasks:
                tasks.append(self._warmup_single(task))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _warmup_single(self, task: dict[str, Any]):
        try:
            task['status'] = 'running'
            logger.info(f"开始预热: {task['name']}")

            start_time = time.time()
            result = await task['function']()
            elapsed = time.time() - start_time

            task['last_run'] = datetime.now()
            task['status'] = 'success'

            logger.info(f"预热完成: {task['name']} (耗时: {elapsed:.2f}s)")
            return result

        except Exception as e:
            task['status'] = 'error'
            logger.error(f"预热失败: {task['name']} - {e}")

    def get_status(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    'name': t['name'],
                    'status': t['status'],
                    'last_run': t['last_run'].isoformat() if t['last_run'] else None,
                    'priority': t['priority']
                }
                for t in self.warmup_tasks
            ]


warmup_manager = CacheWarmupManager()


def auto_refresh_cache(ttl: int = 3600, interval: int = 300,
                       name: str = None, priority: int = 10):
    """自动刷新缓存装饰器"""
    def decorator(func: Callable) -> Callable:
        task_name = name or f"{func.__module__}:{func.__qualname__}"
        warmup_manager.register_task(
            name=task_name,
            func=func,
            ttl=ttl,
            interval=interval,
            priority=priority
        )

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator
