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

try:
    import redis.exceptions as _redis_exceptions
    _REDIS_INFRA: tuple[type[BaseException], ...] = (_redis_exceptions.RedisError,)
except ImportError:  # pragma: no cover - redis 为运行时必需依赖，此处仅保证模块可导入
    _REDIS_INFRA = ()

logger = logging.getLogger(__name__)

# 说明：redis-py 的 ConnectionError / TimeoutError / AuthenticationError 均继承自
# redis.exceptions.RedisError，而 **不** 继承 Python 内置的 ConnectionError / OSError
# （已实测 issubclass(redis.exceptions.ConnectionError, ConnectionError) is False）。
# 因此必须显式纳入 RedisError，否则 Redis 不可用/认证失败不会走降级路径，而是直接冒泡。
INFRA_EXCEPTIONS: tuple[type[BaseException], ...] = (OSError, ConnectionError, *_REDIS_INFRA)  # 移除 ValueError：业务校验异常不应被基础设施降级捕获

# 常用组合：RuntimeError + 基础设施异常（供「防御性兜底」场景使用）。
#
# ⚠️ 不能直接写 `except (RuntimeError, *INFRA_EXCEPTIONS)`：mypy 无法推导
#    星号解包后的 except 元组类型，会报
#        misc: Exception type must be derived from BaseException
#    预展开为显式元组后语义完全等价，且类型可推导。
#
# 收敛说明：此前 purchase_cache.py 有本地副本 _LOCAL_INFRA_EXCEPTIONS，
# event_bus.py / order/_common.py 则直接写星号解包（未纳入类型门禁故未暴露）。
# 现统一到本常量，避免同一变通方案在多个文件里各写一遍。
# （event_bus.py 已于 2026-10-15 删除——其同名 safe_publish_event 与本函数签名
#  不同，构成 import 陷阱；唯一调用方 order_batch_service 已改用本函数。）
RUNTIME_INFRA_EXCEPTIONS: tuple[type[BaseException], ...] = (RuntimeError, *INFRA_EXCEPTIONS)


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
        except INFRA_EXCEPTIONS as e:
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
        logger.error("%s意外异常（不影响数据）: %s", context, e, exc_info=True)
