"""
Redis 缓存操作统一包装器

封装 utils.redis_cache 的常用操作，统一异常处理和日志格式。
所有方法在 Redis 不可用时静默降级，不影响核心业务流程。
"""
import logging
from typing import Any

from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS, safe_call

logger = logging.getLogger(__name__)


async def safe_get(key: str, fallback: Any = None, context: str = "") -> Any:
    """安全获取 Redis 缓存

    用法:
        cached = await safe_get("active_customer_names", context="客户名称缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        return await redis_cache.get(key)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s读取失败: %s", _ctx(context, key), e)
        return fallback


async def safe_set(key: str, value: Any, timeout: int = 300, context: str = "") -> bool:
    """安全设置 Redis 缓存

    用法:
        await safe_set("active_customer_names", data, timeout=300, context="客户名称缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.set(key, value, timeout=timeout)
        return True
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s写入失败: %s", _ctx(context, key), e)
        return False


async def safe_delete(key: str, context: str = "") -> bool:
    """安全删除 Redis 缓存

    用法:
        await safe_delete("active_customer_names", context="客户名称缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.delete(key)
        return True
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s删除失败: %s", _ctx(context, key), e)
        return False


async def safe_delete_pattern(pattern: str, context: str = "") -> int:
    """安全按模式删除 Redis 缓存

    用法:
        await safe_delete_pattern("pp:monthly:*", context="月度日历缓存")
    """
    try:
        from utils.redis_cache import redis_cache
        return await redis_cache.delete_pattern(pattern)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s模式删除失败: %s", _ctx(context, pattern), e)
        return 0


def _ctx(context: str, key: str) -> str:
    if context:
        return f"[{context}] key={key}"
    return f"key={key}"
