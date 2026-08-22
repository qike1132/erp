"""
库存相关的事件/状态重算逻辑

- recalc_order_status_after_return：退货后重算订单状态（派生计算）
- _recalc_shipment_order_statuses：出库后重算受影响订单的状态
- _publish_shipment_completed_events：发布出货完成事件
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.notification_service import StockEvent
from fastapi_app.shared_models.order import ORDER_STATUS_CANCELLED, ORDER_STATUS_SHIPPED

logger = logging.getLogger(__name__)


async def recalc_order_status_after_return(db: AsyncSession, order_id: int) -> dict | None:
    """
    退货后重算订单状态（派生计算）

    根据订单关联的实际出入库数据推导状态，无需手动维护状态流转。
    返回出货完成的订单信息（如状态变更为'已出货'），否则返回 None。
    调用方需在 commit 后自行发布事件。
    """
    from fastapi_app.shared_models import Order
    order_result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = order_result.scalar_one_or_none()
    if not order:
        return None
    if order.status in (None, ORDER_STATUS_CANCELLED):
        return None

    old_status = order.status
    from fastapi_app.services.order_utils import compute_order_status_from_db
    order.status = await compute_order_status_from_db(db, order)

    if order.status == ORDER_STATUS_SHIPPED and old_status != ORDER_STATUS_SHIPPED:
        return {'order_id': order.id, 'order_no': order.order_no, 'customer': order.customer}
    return None


async def _recalc_shipment_order_statuses(db: AsyncSession, created_stockouts: list) -> list[dict]:
    """重算受影响订单的状态，返回变为'已出货'的订单信息列表"""
    if not created_stockouts:
        return []
    from fastapi_app.services.order_utils import compute_order_status_from_db
    from fastapi_app.shared_models import Order
    affected_order_ids: set[int] = {stock_out.order_id for stock_out in created_stockouts if stock_out.order_id}
    if not affected_order_ids:
        return []
    order_result = await db.execute(select(Order).where(Order.id.in_(affected_order_ids)))
    order_map = {order.id: order for order in order_result.scalars().all()}
    shipment_completed_orders = []
    for oid in affected_order_ids:
        order = order_map.get(oid)
        if not order or order.status == ORDER_STATUS_SHIPPED:
            continue
        old_status = order.status
        new_status = await compute_order_status_from_db(db, order)
        if new_status != old_status:
            order.status = new_status
        if new_status == ORDER_STATUS_SHIPPED and old_status != ORDER_STATUS_SHIPPED:
            shipment_completed_orders.append({'order_id': order.id, 'order_no': order.order_no, 'customer': order.customer})
    return shipment_completed_orders


async def _publish_shipment_completed_events(shipment_completed_orders: list[dict]) -> None:
    """发布出货完成事件（单个失败不影响主操作）"""
    if not shipment_completed_orders:
        return
    from fastapi_app.services.notification_service import publish_event_with_fcm
    for order_info in shipment_completed_orders:
        try:
            await publish_event_with_fcm(
                StockEvent.SHIPMENT_COMPLETED,
                order_info,
                fcm_title="出货完成",
                fcm_body=f"订单 {order_info['order_no']} 已完成出货",
            )
        except Exception as e:  # defensive: 单个事件发布失败不影响主操作
            logger.warning('出货完成事件发布失败: %s', e)
