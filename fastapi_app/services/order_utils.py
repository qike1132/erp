"""
订单工具函数

从 order_service.py 提取的共享工具逻辑，消除 order_service ↔ batch_service 的循环依赖。

包含：
- compute_order_status_from_db: 从数据库派生计算订单状态
- _batch_deduct_quantities: 批量查询订单已抵扣备货数量
- sync_single_item_quantity: 单明细订单改数量时同步明细行
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Order, OrderItem, StockOut
from fastapi_app.shared_models.order import compute_status_from_stockouts

logger = logging.getLogger(__name__)


async def sync_single_item_quantity(db: AsyncSession, order_id: int, quantity: int) -> None:
    """单明细订单：把明细数量同步为订单数量。

    列表页显示的数量取自明细行（`_build_beile_order_record` 的
    `record['quantity'] = first_item.quantity`），主表与明细不一致会让贝莱/外包/采购页
    一直显示旧数量——实测改 10000→8888 后主表已变、明细仍 10000。

    直改（order/commands._update_order_directly）与审批通过（approval_service
    ._handle_edit_approval）两条写路径都必须调用。

    多 SKU 订单「改哪一个」的语义未定（两处均有 TODO），此时不擅自改动，仅记日志留痕。
    不走 `order.items` 关系：异步下会触发同步 lazy load（MissingGreenlet），故显式按 order_id 查。
    """
    result = await db.execute(select(OrderItem).where(OrderItem.order_id == order_id))
    items = list(result.scalars().all())
    if len(items) == 1:
        items[0].quantity = quantity
    elif items:
        logger.warning(
            "订单 id=%s 有 %d 条明细，改数量未同步明细（多 SKU 语义未定）",
            order_id, len(items),
        )


async def _batch_deduct_quantities(db: AsyncSession, order_ids: list[int]) -> dict[int, int]:
    """批量查询订单已抵扣备货数量（单次 SQL 聚合，替代 selectinload + Python 遍历）"""
    if not order_ids:
        return {}
    result = await db.execute(
        select(StockOut.order_id, func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
        .where(StockOut.order_id.in_(order_ids), StockOut.stockin_id.isnot(None))
        .group_by(StockOut.order_id)
    )
    return {row[0]: int(row[1]) for row in result.all()}


async def compute_order_status_from_db(db: AsyncSession, order: Order) -> str:
    """从数据库查询订单关联的出入库记录，派生计算订单状态"""
    # 复用 _batch_deduct_quantities 获取抵扣备货量（与列表展示逻辑一致）
    deduct_map = await _batch_deduct_quantities(db, [order.id])
    deducted_qty = max(0, deduct_map.get(order.id, 0))
    # 单独查询独立出货量（stockin_id IS NULL 的出库记录）
    result = await db.execute(
        select(func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
        .where(StockOut.order_id == order.id, StockOut.stockin_id.is_(None))
    )
    shipped_qty = max(0, int(result.scalar() or 0))
    return compute_status_from_stockouts(order, deducted_qty, shipped_qty)
