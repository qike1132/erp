"""
客户订单 ↔ 采购中心同步服务

当客户订单发生变更（删除/更新）时，同步更新采购中心的相关数据，
确保两个系统间的数据一致性。

核心设计：
- 使用与调用方相同的 AsyncSession，在同一事务内完成同步
- 删除同步处理两种关联：source_order_id（单值）和 source_order_ids（JSON 数组）
- 更新同步包括：客户名、订单数量、采购项数量（基于 unit_usage 重算）
"""

import json
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import PurchaseOrder, PurchaseOrderItem

logger = logging.getLogger(__name__)


async def sync_order_delete(db: AsyncSession, order_id: int) -> dict:
    """当客户订单被删除时，同步删除采购中心中关联的采购订单

    处理两种关联方式：
    1. PurchaseOrder.source_order_id == order_id（直接关联，一键审核生成）
    2. PurchaseOrder.source_order_ids 包含 order_id（JSON 数组关联）
    """
    deleted_count = 0
    updated_count = 0

    # 1. 删除直接关联的采购订单（cascade='all, delete-orphan' 自动删除 items）
    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.source_order_id == order_id)
    )
    direct_orders = result.scalars().all()
    for po in direct_orders:
        logger.info(
            '同步删除采购订单：%s（关联客户订单ID: %s，状态: %s）',
            po.order_no, order_id, po.status,
        )
        await db.delete(po)
        deleted_count += 1

    # 2. 处理 JSON 数组关联的采购订单
    # source_order_ids 存储 JSON 数组如 "[1,2,3]"，使用 PostgreSQL JSONB @> 操作符避免全表扫描
    from sqlalchemy import cast as sa_cast
    from sqlalchemy.dialects.postgresql import JSONB as PG_JSONB
    result2 = await db.execute(
        select(PurchaseOrder).where(
            PurchaseOrder.source_order_ids.isnot(None),
            sa_cast(PurchaseOrder.source_order_ids, PG_JSONB).contains([order_id])
        )
    )
    for po in result2.scalars():
        try:
            ids = json.loads(po.source_order_ids)
            if isinstance(ids, list) and order_id in ids:
                ids.remove(order_id)
                if not ids:
                    logger.info(
                        '同步删除采购订单（无剩余关联）：%s', po.order_no,
                    )
                    await db.delete(po)
                    deleted_count += 1
                else:
                    po.source_order_ids = json.dumps(ids)
                    updated_count += 1
        except (json.JSONDecodeError, TypeError):
            pass

    return {'deleted_purchase_orders': deleted_count, 'updated_purchase_orders': updated_count}


async def sync_order_update(
    db: AsyncSession,
    order_id: int,
    *,
    customer: str | None = None,
    old_customer: str | None = None,
    quantity: int | None = None,
    old_quantity: int | None = None,
) -> dict | None:
    """当客户订单被更新时，同步更新采购中心中关联的采购订单

    更新内容：
    - PurchaseOrder.customer_name：客户名称变更
    - PurchaseOrder.product_quantity：订单数量变更
    - PurchaseOrderItem.customer_name：采购项客户名称
    - PurchaseOrderItem.quantity：采购项数量（基于 unit_usage 重新计算）
    """
    customer_changed = (
        customer is not None and old_customer is not None and customer != old_customer
    )
    quantity_changed = (
        quantity is not None and old_quantity is not None and quantity != old_quantity
    )

    if not customer_changed and not quantity_changed:
        return None

    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.source_order_id == order_id)
    )
    updated_count = 0
    for po in result.scalars():
        if customer_changed:
            po.customer_name = customer
            items_result = await db.execute(
                select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == po.id)
            )
            for item in items_result.scalars():
                item.customer_name = customer

        if quantity_changed:
            po.product_quantity = Decimal(str(quantity))
            items_result = await db.execute(
                select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == po.id)
            )
            for item in items_result.scalars():
                if item.unit_usage and item.unit_usage > 0:
                    new_qty = item.unit_usage * Decimal(str(quantity))
                    item.quantity = new_qty
                    if item.unit_price:
                        item.total_price = new_qty * item.unit_price

        updated_count += 1

    if updated_count > 0:
        logger.info(
            '同步更新采购订单：%d条，客户变更=%s，数量变更=%s',
            updated_count, customer_changed, quantity_changed,
        )

    return {
        'updated_purchase_orders': updated_count,
        'customer_changed': customer_changed,
        'quantity_changed': quantity_changed,
    }
