"""
订单域共享辅助（事件发布 / 缓存失效 / 异常）

从 order_crud.py 拆出，供 beile 与命令/查询子模块共同引用，
避免子模块间循环依赖。行为与原 order_crud.py 完全一致。
"""
import asyncio
import logging

from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.domain_events import DomainEvent, DomainEventType, publish_with_retry
from fastapi_app.core.exception_handler import RUNTIME_INFRA_EXCEPTIONS
from fastapi_app.services.notification_service import StockEvent, publish_event

logger = logging.getLogger(__name__)

# 持有后台任务引用，防止被 GC 回收（Python asyncio 官方推荐模式）
_pending_tasks: set[asyncio.Task] = set()

# StockEvent → 领域事件映射（原 core/event_bus.safe_publish_event 语义，event_bus 下线后由本模块自持）
_STOCK_TO_DOMAIN_EVENT_MAP = {
    StockEvent.ORDER_CREATED: DomainEventType.ORDER_CREATED,
    StockEvent.ORDER_UPDATED: DomainEventType.ORDER_STATUS_CHANGED,
    # ORDER_DELETED 领域事件由 endpoint 层在事务提交后直接发布（order.py/approval.py），此处不映射
}


async def _safe_publish_event(event_type: str, data: dict) -> None:
    """安全发布库存事件（WebSocket 实时通知 + 领域事件总线）。

    core/event_bus.safe_publish_event 的等价实现：
    1. publish_event → WebSocket 广播，失败仅记警告；
    2. StockEvent 映射为领域事件后经 publish_with_retry 发布（失败重试一次，
       仍失败则内部记 ERROR 日志，不向主流程抛出）。
    """
    try:
        await publish_event(event_type, data)
    except RUNTIME_INFRA_EXCEPTIONS:
        logger.warning("事件发布失败: %s", event_type, exc_info=True)

    domain_event_type = _STOCK_TO_DOMAIN_EVENT_MAP.get(event_type)
    if domain_event_type:
        await publish_with_retry(DomainEvent(event_type=domain_event_type, domain='order', payload=data))


async def _safe_invalidate_purchase_cache():
    """安全清除采购中心缓存，失败仅记录警告"""
    await cache_mgr.invalidate(InvalidationStrategy.PURCHASE)


def schedule_post_commit_event(session, event_type: str, data: dict) -> None:
    """注册「事务提交成功后」再发布的实时事件（WebSocket + 领域事件）。

    必须在 commit 之后广播：客户端收到事件会立刻重取列表，若事件先于提交发出，
    重取读到的是**尚未提交**的旧数据（订单仍在），并以前端该次读取的时间戳作为
    dataUpdatedAt 缓存，staleTime 内不再回取——表现为「删除/改数量后关联页面
    延迟约 30 秒才更新」。审批路径（endpoints/approval.py）即为提交后发布。

    仅在使用 db_transaction 的调用链上生效（其 commit 成功后执行回调）；
    自行 commit 的入口需在提交后调用 run_post_commit_callbacks。

    挂载实现委托 core.domain_events.schedule_post_commit_callback
    （post-commit 调度唯一事实来源，2026-10-15 收敛）。
    """
    from fastapi_app.core.domain_events import schedule_post_commit_callback

    async def _publish() -> None:
        await _safe_publish_event(event_type, data)

    schedule_post_commit_callback(session, _publish)


def _log_background_task_exception(task: asyncio.Task) -> None:
    """后台任务完成回调：记录未捕获异常，防止 fire-and-forget 任务静默失败"""
    if not task.cancelled() and task.exception() is not None:
        logger.error('后台事件发布任务失败', exc_info=task.exception())


class PermissionDeniedError(Exception):
    """用户无权限执行此操作"""
    pass
