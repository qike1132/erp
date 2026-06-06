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
import random
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import Flag, auto
from functools import wraps
from typing import Any

CACHE_TIMEOUT = 1.0

logger = logging.getLogger(__name__)

_CACHE_LOCAL_MAX_SIZE = 5000  # L1 缓存最大条目数（从 10000 降至 5000）
_cache_local: OrderedDict[str, tuple[Any, datetime]] = OrderedDict()

# 断路器：Redis 连续失败 N 次后短路跳过，避免每次请求浪费超时等待
_redis_fail_count = 0
_REDIS_CIRCUIT_THRESHOLD = 3
_redis_circuit_open_until: datetime | None = None
_REDIS_CIRCUIT_COOLDOWN = timedelta(seconds=30)


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
    MATERIAL = auto()
    ALL = ORDER | INVENTORY | STOCKIN | STOCKOUT | PRODUCT | CUSTOMER | SEARCH | MATERIAL


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
    CacheDomain.MATERIAL: "material:*",
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


def _evict_local_cache() -> int:
    """清理过期条目并淘汰超限条目（O(1) LRU）"""
    now = datetime.now()
    # 先清理过期条目
    expired_keys = [k for k, (_, exp) in _cache_local.items() if now >= exp]
    for k in expired_keys:
        _cache_local.pop(k, None)
    # 淘汰最旧的条目（FIFO 端）
    while len(_cache_local) > _CACHE_LOCAL_MAX_SIZE:
        _cache_local.popitem(last=False)
    return len(expired_keys)


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
            global _redis_fail_count, _redis_circuit_open_until
            try:
                if key_builder:
                    cache_key = f"{key_prefix}:{key_builder(*args, **kwargs)}"
                else:
                    params_str = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True, default=str)
                    params_hash = hashlib.md5(params_str.encode(), usedforsecurity=False).hexdigest()[:10]
                    cache_key = f"{key_prefix}:{params_hash}"

                now = datetime.now()

                if cache_key in _cache_local:
                    value, expire_at = _cache_local.pop(cache_key)  # 移除
                    if now < expire_at:
                        _cache_local[cache_key] = (value, expire_at)  # 移到末尾（最近使用）
                        return value
                    # 已过期，不回插

                # 断路器：Redis 连续失败超过阈值时跳过
                redis_available = True
                if _redis_circuit_open_until is not None:
                    if now < _redis_circuit_open_until:
                        redis_available = False
                    else:
                        _redis_circuit_open_until = None
                        _redis_fail_count = 0

                redis = _get_redis_cache() if redis_available else None
                if redis:
                    try:
                        cached = await asyncio.wait_for(
                            redis.get(cache_key),
                            timeout=CACHE_TIMEOUT
                        )
                        if cached is not None:
                            result = cached
                            # 回填 L1：先移除再插入，保证 OrderedDict 顺序
                            _cache_local.pop(cache_key, None)
                            _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))
                            _redis_fail_count = 0
                            return result
                        _redis_fail_count = 0
                    except (TimeoutError, OSError, ConnectionError, ValueError) as e:
                        _redis_fail_count += 1
                        if _redis_fail_count >= _REDIS_CIRCUIT_THRESHOLD:
                            _redis_circuit_open_until = now + _REDIS_CIRCUIT_COOLDOWN
                            logger.warning("Redis 断路器开启，%s秒内跳过Redis: %s", _REDIS_CIRCUIT_COOLDOWN.total_seconds(), e)
                        else:
                            logger.warning("Redis 缓存读取失败(timeout=%ss)，降级到数据库查询: %s", CACHE_TIMEOUT, e)

                result = await func(*args, **kwargs)

                # 写入 L1：先移除再插入，保证 OrderedDict 顺序
                _cache_local.pop(cache_key, None)
                _cache_local[cache_key] = (result, now + timedelta(seconds=local_ttl))
                _evict_local_cache()

                if redis and redis_available:
                    try:
                        await asyncio.wait_for(
                            redis.set(cache_key, result, timeout=int(ttl)),
                            timeout=CACHE_TIMEOUT
                        )
                        _redis_fail_count = 0
                    except (TimeoutError, OSError, ConnectionError, ValueError) as e:
                        _redis_fail_count += 1
                        if _redis_fail_count >= _REDIS_CIRCUIT_THRESHOLD:
                            _redis_circuit_open_until = now + _REDIS_CIRCUIT_COOLDOWN

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
            _cache_local.pop(k, None)
        deleted += len(keys_to_remove)

        return deleted
    except (OSError, ValueError) as e:
        logger.error("缓存失效失败: %s", e, exc_info=True)
        return 0


def invalidate_local_cache(pattern: str) -> int:
    """仅使进程内 L1 缓存失效"""
    keys_to_remove = [k for k in _cache_local if _match_pattern(k, pattern)]
    for k in keys_to_remove:
        _cache_local.pop(k, None)
    return len(keys_to_remove)


def _match_pattern(key: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(key, pattern)


async def warmup_cache(func, *args, key_prefix: str, ttl: int = 60, **kwargs):
    """主动预热缓存"""
    result = await func(*args, **kwargs)
    cache_key = f"{key_prefix}:prewarm"
    now = datetime.now()
    _cache_local.pop(cache_key, None)
    _cache_local[cache_key] = (result, now + timedelta(seconds=30))
    redis = _get_redis_cache()
    if redis:
        with contextlib.suppress(OSError, ValueError):
            await redis.set(cache_key, result, timeout=int(ttl))
    return result


async def invalidate_dashboard_cache():
    """失效 dashboard 相关缓存，确保数据同步"""
    try:
        await invalidate_cache('dashboard:*')
        await invalidate_cache('dashboard:stats')
        await invalidate_cache('dashboard:activities')
        logger.info("Dashboard 缓存已失效")
    except Exception as e:
        logger.warning(f"失效 Dashboard 缓存失败: {e}")
