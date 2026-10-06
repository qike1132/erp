"""
库存可发数量计算服务

从 batch_service.py 提取，职责单一：异步可出货量计算。
可出货量的汇总构建逻辑统一在 shared/shipment_calc.py（同步/异步共用）。

TODO(multi-sku-order): 本模块多处 SQL 直接引用 Order.product_id/Order.quantity
（where 条件、累加逻辑）。多 SKU 模型下这些为首 item 兼容值，完整改造涉及
业务语义变更，待后续 spec 改造为 JOIN OrderItem。当前依赖 Task 3 设置的兼容值。
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared.shipment_calc import build_shipment_summary
from fastapi_app.shared_models import Order, Product, StockOut

logger = logging.getLogger(__name__)


async def calculate_available_shipment_quantity(
    db: AsyncSession, product_id: int, customer: str, *, lock_orders: bool = True
) -> dict:
    """
    计算指定客户和产品的可出货量

    业务规则（2026-10-06 校准）：
    1. 出货量受限于订单量：可出货 = 订单总量 - 已出货量（非抵扣出货）
    2. 备货量只能通过订单抵扣使用，不能直接出货
    3. 出货还要有实物：生产即入库后 current_stock = 备货 + 生产 - 出库（产品净存量），
       可出货量最终以 min(订单余量, 产品净存量) 封顶——订单再多，没生产的货也出不了

    lock_orders 默认对订单行加排他行锁（出货提交路径防超量竞态的依据，
    勿在写路径关闭）。仅展示类端点可传 lock_orders=False：其会话可能来自
    只读副本，热备副本处于只读模式，无法执行行锁查询。
    """
    where_clause = [
        Order.product_id == product_id,
        Order.customer == customer,
        # 软删除订单不得计入可出货量，否则删除订单后仍能按已删订单的数量出货/抵扣
        Order.is_deleted.isnot(True),
    ]

    if lock_orders:
        result = await db.execute(
            select(Order)
            .where(*where_clause)
            .order_by(Order.order_date.asc())
            .with_for_update()
        )
    else:
        result = await db.execute(
            select(Order).where(*where_clause).order_by(Order.order_date.asc())
        )
    orders = result.scalars().all()

    if not orders:
        return build_shipment_summary([], {})

    # 单次查询获取所有订单的已出货量（扣除退货后的净出货量），替代N+1循环查询
    # 注意：PostgreSQL 不支持 FOR UPDATE 与 GROUP BY 组合使用，
    # Order 行锁防止出货超量竞态，StockOut 的 GROUP BY 查询无需行锁
    order_ids = [o.id for o in orders]
    shipped_result = await db.execute(
        select(StockOut.order_id, func.sum(StockOut.quantity - StockOut.returned_quantity))
        .where(
            StockOut.order_id.in_(order_ids),
            StockOut.stockin_id.is_(None)
        )
        .group_by(StockOut.order_id)
    )
    # order_id 列类型可空，查询已用 .in_(order_ids) 排除 NULL，守卫仅作类型收窄
    shipped_map = {o_id: total for o_id, total in shipped_result.all() if o_id is not None}
    summary = build_shipment_summary(orders, shipped_map)

    # 实物封顶（2026-10-06 校准）：订单口径的可出货量不得超过产品净存量
    # （备货 + 生产 - 出库）。净存量无锁读取——写路径的原子负库存守卫
    # （apply_stock_delta_locked）在扣减时兜底，显示/预检读旧值只是保守偏差。
    product_row = await db.execute(select(Product).where(Product.id == product_id))
    product = product_row.scalar_one_or_none()
    if product is not None and summary.get('available_quantity', 0) > max(0, product.current_stock):
        summary['available_quantity'] = max(0, product.current_stock)
    return summary
