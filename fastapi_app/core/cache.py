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

_cache_local: dict[str, tuple[Any, datetime]] = {}


def _get_redis_cache():
    """获取 Redis 缓存实例（延迟导入避免循环依赖）"""
    try:
        from utils.redis_cache import redis_cache
        return redis_cache
    except Exception:
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
                        if cached:
                            if serialize:
                                result = json.loads(cached)
                            else:
                                result = cached
                            _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))
                            return result
                    except Exception as e:
                        logger.warning("Redis 缓存读取失败，降级到数据库查询: %s", e)

                result = await func(*args, **kwargs)

                _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))

                if redis:
                    try:
                        if serialize:
                            serialized = json.dumps(result, ensure_ascii=False, default=str)
                        else:
                            serialized = result
                        await redis.set(cache_key, serialized, ex=ttl)
                    except Exception as e:
                        logger.warning("Redis 缓存写入失败: %s", e)

                return result

            except Exception as e:
                logger.error("缓存装饰器执行失败: %s", e, exc_info=True)
                return await func(*args, **kwargs)

        return wrapper
    return decorator


async def invalidate_cache(pattern: str) -> int:
    """使缓存失效"""
    try:
        deleted = 0
        keys_to_remove = [k for k in _cache_local if _match_pattern(k, pattern)]
        for k in keys_to_remove:
            del _cache_local[k]
        deleted += len(keys_to_remove)

        redis = _get_redis_cache()
        if redis:
            try:
                keys = await redis.keys(pattern)
                if keys:
                    redis_deleted = await redis.delete(*keys)
                    deleted += redis_deleted
                    logger.info("Redis 缓存失效: pattern=%s, deleted=%d", pattern, redis_deleted)
            except Exception as e:
                logger.warning("Redis 缓存失效失败: %s", e)

        return deleted
    except Exception as e:
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
            await redis.set(cache_key, json.dumps(result, ensure_ascii=False, default=str), ex=ttl)
        except Exception:
            pass
    return result
