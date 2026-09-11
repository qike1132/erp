"""
事件发布安全封装

提供 safe_publish_event 函数，统一处理 WebSocket 广播和领域事件发布，
所有操作失败仅记录日志，不影响主业务流程。
（FCM 推送已于 2026-08-31 随移动端一并摘除）
"""
import logging

from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS

logger = logging.getLogger(__name__)


async def safe_publish_event(event_type: str, data: dict):
    """安全发布库存事件（WebSocket 广播），同时通过领域事件总线发布解耦事件

    调用链：
    1. notification_service.publish_event → WebSocket 广播（实时通知）
    2. domain_events.publish → 进程内订阅者通知 + Redis Pub/Sub 跨进程广播（跨域解耦）

    两者均失败不影响主业务流程。
    """
    try:
        from fastapi_app.services.notification_service import publish_event
        await publish_event(event_type, data)
    except (RuntimeError, *INFRA_EXCEPTIONS):
        logger.warning("事件发布失败: %s", event_type, exc_info=True)

    # 通过领域事件总线发布，实现跨域通信解耦
    # 事件映射：StockEvent → DomainEventType
    from fastapi_app.core.domain_events import DomainEvent, DomainEventType
    from fastapi_app.core.domain_events import publish as publish_domain_event
    from fastapi_app.services.notification_service import StockEvent

    _stock_to_domain_map = {
        StockEvent.ORDER_CREATED: DomainEventType.ORDER_CREATED,
        StockEvent.ORDER_UPDATED: DomainEventType.ORDER_STATUS_CHANGED,
        # ORDER_DELETED 领域事件由 endpoint 层在事务提交后直接发布（order.py/approval.py），
        # 不在此映射，避免 safe_publish_event 在事务提交前触发订阅者查询未提交数据。
    }
    domain_event_type = _stock_to_domain_map.get(event_type)
    if domain_event_type:
        try:
            event = DomainEvent(
                event_type=domain_event_type,
                domain='order',
                payload=data,
            )
            await publish_domain_event(event)
            logger.debug("领域事件已发布: %s", domain_event_type.value)
        except Exception:  # defensive: domain event bus failure must not interrupt main business flow
            logger.warning("领域事件总线发布失败（可忽略）: %s", domain_event_type.value, exc_info=True)
