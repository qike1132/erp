"""
采购中心 - BOM 复制服务

从 purchase_center_service.py 拆分，包含 BOM 复制搜索、预览和执行功能。
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import (
    PurchaseOrder,
    PurchaseOrderItem,
)
from fastapi_app.services.bom_service import (  # noqa: E402,F401
    copy_bom as copy_bom_to_product,
    preview_bom as get_bom_preview,
    search_for_bom_copy as search_products_for_bom_copy,
)

logger = logging.getLogger(__name__)


async def batch_delete_purchase_orders(db: AsyncSession, order_ids: list, username: str = 'unknown') -> dict:
    if not order_ids:
        raise ValueError('请选择要删除的订单')

    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids)))
    orders_to_delete = result.scalars().all()
    if not orders_to_delete:
        raise ValueError('未找到要删除的订单')

    deleted_info = []
    for order in orders_to_delete:
        count_result = await db.execute(
            select(func.count(PurchaseOrderItem.id)).where(PurchaseOrderItem.order_id == order.id)
        )
        item_count = count_result.scalar()
        deleted_info.append({
            'order_no': order.order_no,
            'supplier_name': order.supplier_name or '',
            'customer_name': order.customer_name or '',
            'item_count': item_count,
        })
        await db.delete(order)

    await db.flush()

    logger.warning(
        f'批量删除采购订单 | 操作人: {username} | '
        f'删除数量: {len(deleted_info)} | '
        f"订单编号: {', '.join(info['order_no'] for info in deleted_info)}"
    )

    return {
        'message': f'成功删除 {len(deleted_info)} 个订单',
        'deleted_count': len(deleted_info),
    }
