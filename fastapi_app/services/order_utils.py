"""
订单工具函数

从 order_service.py 提取的共享工具逻辑，消除 order_service ↔ batch_service 的循环依赖。

包含：
- compute_order_status_from_db: 从数据库派生计算订单状态
- _batch_deduct_quantities: 批量查询订单已抵扣备货数量
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Order, StockOut
from fastapi_app.shared_models.order import compute_status_from_stockouts

logger = logging.getLogger(__name__)


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
    shipped_qty = max(0, int(result.scalar()))
    return compute_status_from_stockouts(order, deducted_qty, shipped_qty)
