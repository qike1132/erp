"""
Redis 缓存装饰器和工具函数

提供三级缓存架构：
L1: 进程内缓存 (TTL 30s)
L2: Redis 缓存 (TTL 可配置)
L3: 数据库
"""
import asyncio
import contextlib
import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Flag, auto
from functools import wraps
from typing import Any

CACHE_TIMEOUT = 2.0

logger = logging.getLogger(__name__)

_CACHE_LOCAL_MAX_SIZE = 10000  # L1 缓存最大条目数
_cache_local: dict[str, tuple[Any, datetime]] = {}


class CacheDomain(Flag):
    """缓存域枚举，支持按位或组合"""
    NONE = 0
    ORDER = auto()
    INVENTORY = auto()
    STOCKIN = auto()
    PRODUCT = auto()      # 预留：产品信息变更时失效
    CUSTOMER = auto()     # 预留：客户信息变更时失效
    SEARCH = auto()       # 预留：搜索索引变更时失效

    # 常用组合
    ORDER_AND_INVENTORY = ORDER | INVENTORY
    STOCKOUT = auto()
    ALL = ORDER | INVENTORY | STOCKIN | STOCKOUT | PRODUCT | CUSTOMER | SEARCH


# 缓存域 → pattern 映射（仅允许单域 key，禁止添加组合域 key，
# 否则 invalidate_related_caches 的按位与判断会导致重复失效）
_DOMAIN_PATTERN_MAP: dict[CacheDomain, str] = {
    CacheDomain.ORDER: "orders:*",
    CacheDomain.INVENTORY: "inventory:*",
    CacheDomain.STOCKIN: "stockins:*",
    CacheDomain.PRODUCT: "products:*",
    CacheDomain.CUSTOMER: "customers:*",
    CacheDomain.SEARCH: "search:*",
    CacheDomain.STOCKOUT: "stockouts:*",
}


async def invalidate_related_caches(domains: CacheDomain) -> int:
    """根据缓存域枚举失效相关缓存

    Args:
        domains: 缓存域枚举，支持按位或组合，如 CacheDomain.ORDER | CacheDomain.INVENTORY

    Returns:
        失效的缓存条目数
    """
    if domains == CacheDomain.NONE:
        logger.debug("invalidate_related_caches: 传入 NONE，跳过缓存失效")
        return 0

    deleted = 0
    for domain, pattern in _DOMAIN_PATTERN_MAP.items():
        # 仅匹配单域：跳过组合域 key，防止按位与导致重复失效
        if domain.value & (domain.value - 1) != 0:
            continue
        if domains & domain:
            try:
                deleted += await invalidate_cache(pattern)
            except (RuntimeError, OSError, ValueError) as e:
                logger.warning("缓存域 %s 失效失败，继续处理其他域: %s", domain.name, e)
    return deleted


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
    key_builder: Callable | None = None,
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
                    params_str = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True, default=str)
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
                        cached = await asyncio.wait_for(
                            redis.get(cache_key),
                            timeout=CACHE_TIMEOUT
                        )
                        if cached is not None:
                            result = cached
                            _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))
                            return result
                    except (TimeoutError, OSError, ConnectionError, ValueError) as e:
                        logger.warning("Redis 缓存读取失败(timeout=%ss)，降级到数据库查询: %s", CACHE_TIMEOUT, e)

                result = await func(*args, **kwargs)

                _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))
                _evict_local_cache()

                if redis:
                    try:
                        await asyncio.wait_for(
                            redis.set(cache_key, result, timeout=int(ttl)),
                            timeout=CACHE_TIMEOUT
                        )
                    except (TimeoutError, OSError, ConnectionError, ValueError) as e:
                        logger.warning("Redis 缓存写入失败(timeout=%ss): %s", CACHE_TIMEOUT, e)

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
        with contextlib.suppress(OSError, ValueError):
            await redis.set(cache_key, result, timeout=int(ttl))
    return result
