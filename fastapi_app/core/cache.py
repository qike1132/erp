"""
Redis 缓存装饰器和工具函数

提供三级缓存架构：
L1: 进程内缓存 (TTL 30s)
L2: Redis 缓存 (TTL 可配置)
L3: 数据库
"""
import json
import hashlib
import logging
from functools import wraps
from typing import Optional, Callable, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_CACHE_LOCAL_MAX_SIZE = 10000  # L1 缓存最大条目数
_cache_local: dict[str, tuple[Any, datetime]] = {}


def _evict_local_cache():
    """当 L1 缓存超过上限时，淘汰最早过期的条目"""
    if len(_cache_local) <= _CACHE_LOCAL_MAX_SIZE:
        return
    # 按过期时间排序，淘汰最旧的 25%
    sorted_items = sorted(_cache_local.items(), key=lambda x: x[1][1])
    evict_count = len(sorted_items) // 4
    for k, _ in sorted_items[:evict_count]:
        del _cache_local[k]


def _get_redis_cache():
    """获取 Redis 缓存实例（延迟导入避免循环依赖）"""
    try:
        from utils.redis_cache import redis_cache
        return redis_cache
    except (ImportError, OSError):
        return None


def cache_result(
    key_prefix: str,
    ttl: int = 60,
    local_ttl: int = 30,
    key_builder: Optional[Callable] = None,
    serialize: bool = True,
):
    """
    缓存装饰器 - 支持 L1(内存) + L2(Redis) 两级缓存
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                if key_builder:
                    cache_key = f"{key_prefix}:{key_builder(*args, **kwargs)}"
                else:
                    params_str = json.dumps({'args': str(args), 'kwargs': kwargs}, sort_keys=True, default=str)
                    params_hash = hashlib.md5(params_str.encode(), usedforsecurity=False).hexdigest()[:10]
                    cache_key = f"{key_prefix}:{params_hash}"

                now = datetime.now()

                if cache_key in _cache_local:
                    value, expire_at = _cache_local[cache_key]
                    if now < expire_at:
                        return value
                    else:
                        del _cache_local[cache_key]

                redis = _get_redis_cache()
                if redis:
                    try:
                        cached = await redis.get(cache_key)
                        if cached is not None:
                            result = cached
                            _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))
                            return result
                    except (OSError, ConnectionError, ValueError) as e:
                        logger.warning("Redis 缓存读取失败，降级到数据库查询: %s", e)

                result = await func(*args, **kwargs)

                _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))
                _evict_local_cache()

                if redis:
                    try:
                        await redis.set(cache_key, result, timeout=int(ttl))
                    except (OSError, ConnectionError, ValueError) as e:
                        logger.warning("Redis 缓存写入失败: %s", e)

                return result

            except (OSError, ConnectionError, ValueError) as e:
                logger.error("缓存装饰器执行失败: %s", e, exc_info=True)
                return await func(*args, **kwargs)

        return wrapper
    return decorator


async def invalidate_cache(pattern: str) -> int:
    """使缓存失效（先删 L2 Redis，再删 L1 本地，缩小竞态窗口）"""
    try:
        deleted = 0

        # 先删 L2 Redis，防止其他进程/协程从 Redis 读到旧数据回填 L1
        redis = _get_redis_cache()
        if redis:
            try:
                redis_deleted = await redis.delete_pattern(pattern)
                deleted += redis_deleted
                logger.info("Redis 缓存失效: pattern=%s, deleted=%d", pattern, redis_deleted)
            except (OSError, ConnectionError, ValueError) as e:
                logger.warning("Redis 缓存失效失败: %s", e)

        # 再删 L1 本地缓存
        keys_to_remove = [k for k in _cache_local if _match_pattern(k, pattern)]
        for k in keys_to_remove:
            del _cache_local[k]
        deleted += len(keys_to_remove)

        return deleted
    except (OSError, ValueError) as e:
        logger.error("缓存失效失败: %s", e, exc_info=True)
        return 0


def invalidate_local_cache(pattern: str) -> int:
    """仅使进程内 L1 缓存失效"""
    keys_to_remove = [k for k in _cache_local if _match_pattern(k, pattern)]
    for k in keys_to_remove:
        del _cache_local[k]
    return len(keys_to_remove)


def _match_pattern(key: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(key, pattern)


async def warmup_cache(func, *args, key_prefix: str, ttl: int = 60, **kwargs):
    """主动预热缓存"""
    result = await func(*args, **kwargs)
    cache_key = f"{key_prefix}:prewarm"
    now = datetime.now()
    _cache_local[cache_key] = (result, now + timedelta(seconds=30))
    redis = _get_redis_cache()
    if redis:
        try:
            await redis.set(cache_key, result, timeout=int(ttl))
        except (OSError, ValueError):
            pass
    return result
