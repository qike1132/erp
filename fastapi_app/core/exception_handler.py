"""
统一异常处理工具模块

提供标准化的异常分类、日志格式和降级策略，
消除服务层重复的 try/except 模式。

核心设计：
- safe_call: 内联安全调用，替代 try/except 块
- safe_publish_event: 事件发布专用安全调用
- INFRA_EXCEPTIONS: 统一的基础设施异常类型元组
"""
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

INFRA_EXCEPTIONS = (OSError, ConnectionError)  # 移除 ValueError：业务校验异常不应被基础设施降级捕获


async def safe_call(
    coro: Any,
    context: str,
    fallback: Any = None,
    log_level: str = "warning",
) -> Any:
    """安全调用异步协程，捕获基础设施异常后返回降级值

    用法:
        result = await safe_call(
            redis_cache.get(key),
            context="客户名称缓存读取",
            fallback=None,
        )

    等价于:
        try:
            result = await redis_cache.get(key)
        except (OSError, ConnectionError) as e:
            logger.warning("客户名称缓存读取失败: %s", e)
            result = None
    """
    try:
        return await coro
    except INFRA_EXCEPTIONS as e:
        _log = getattr(logger, log_level, logger.warning)
        _log("%s失败: %s", context, e)
        return fallback


async def safe_publish_event(
    publish_func: Callable,
    event_type: str,
    data: dict,
    context: str = "事件发布",
    **kwargs,
) -> None:
    """安全发布事件，捕获所有异常后仅记录日志

    事件发布属于非关键操作（不影响核心业务数据），
    因此捕获所有异常防止主流程中断。
    已知基础设施异常记录 warning，意外异常记录 error。

    用法:
        await safe_publish_event(
            publish_event,
            StockEvent.ORDER_CREATED,
            {'order_id': order.id, ...},
            context="订单创建事件发布",
        )
    """
    try:
        await publish_func(event_type, data, **kwargs)
    except INFRA_EXCEPTIONS as e:
        logger.warning("%s失败（不影响数据）: %s", context, e)
    except Exception as e:  # defensive: event publishing is non-critical and must not interrupt business flow
        logger.error("%s意外异常（不影响数据）: %s", context, e, exc_info=False)
