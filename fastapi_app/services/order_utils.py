"""
订单工具函数

从 order_service.py 提取的共享工具逻辑，消除 order_service ↔ batch_service 的循环依赖。

包含：
- compute_order_status_from_db: 从数据库派生计算订单状态
- _batch_deduct_quantities: 批量查询订单已抵扣备货数量
- sync_single_item_quantity: 单明细订单改数量时同步明细行
"""
import logging

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Order, OrderItem, StockOut, StockReturn
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


async def compute_order_statuses_batch(
    db: AsyncSession, orders: list[Order]
) -> dict[int, str]:
    """一次聚合算出多张订单的状态（替代循环内逐单 2 条 SQL）。

    与 :func:`compute_order_status_from_db` 同口径：抵扣量按 stockin_id 非空聚合，
    独立出货量按 stockin_id 为空聚合；只是把 N 次查询压成 2 次。
    """
    if not orders:
        return {}
    order_ids = [o.id for o in orders]
    deduct_map = await _batch_deduct_quantities(db, order_ids)
    result = await db.execute(
        select(
            StockOut.order_id,
            func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0),
        )
        .where(StockOut.order_id.in_(order_ids), StockOut.stockin_id.is_(None))
        .group_by(StockOut.order_id)
    )
    shipped_map = {row[0]: int(row[1]) for row in result.all()}
    return {
        o.id: compute_status_from_stockouts(
            o, max(0, deduct_map.get(o.id, 0)), max(0, shipped_map.get(o.id, 0))
        )
        for o in orders
    }


async def assert_no_linked_returns(db: AsyncSession, order_id: int) -> None:
    """订单存在**未取消**的退货记录时禁止删除（迁移 072：stock_return.stockout_id ON DELETE RESTRICT）。

    删订单会级联物理删其 stock_out；出货行只要被退货记录引用（RESTRICT 外键）就删不掉。
    **已取消**（status='cancelled'）的退货不构成阻碍——删订单时由
    `detach_cancelled_returns_for_order` 解除其对外键的引用（退货行本身保留，可追溯）；
    仍为 active 的退货才拒绝。直删（order/commands._delete_order_directly）与审批通过
    （approval_service._handle_delete_approval）两条路径都先过此校验，否则会退化成 DB 层
    IntegrityError 被映射成 409「订单存在关联数据」的含糊报错（2026-10-08 鲨鱼订单 68927）。
    """
    result = await db.execute(
        select(StockReturn.return_no).where(
            StockReturn.status != 'cancelled',
            or_(
                StockReturn.order_id == order_id,
                StockReturn.stockout_id.in_(
                    select(StockOut.id).where(StockOut.order_id == order_id)
                ),
            ),
        ).order_by(StockReturn.id)
    )
    return_nos = list(result.scalars().all())
    if return_nos:
        shown = '、'.join(return_nos[:5])
        more = f' 等 {len(return_nos)} 条' if len(return_nos) > 5 else ''
        raise ValueError(
            f'该订单存在退货记录（{shown}{more}），无法删除：已出货且有退货的订单需保留退货台账以便追溯。'
        )


async def detach_cancelled_returns_for_order(db: AsyncSession, order_id: int) -> None:
    """删订单前解除「已取消」退货记录对该订单出货行的引用（退货行本身保留）。

    迁移 072 的 RESTRICT 外键要求出货行被任何退货记录引用时都不可删。把已取消退货的
    stockout_id 置空，出货行即可删除，同时退货台账（单号/数量/状态）仍保留。
    active 退货不在本函数范围——它们已在 `assert_no_linked_returns` 处被拒。
    """
    await db.execute(
        update(StockReturn)
        .where(
            StockReturn.status == 'cancelled',
            StockReturn.stockout_id.in_(
                select(StockOut.id).where(StockOut.order_id == order_id)
            ),
        )
        .values(stockout_id=None)
    )
