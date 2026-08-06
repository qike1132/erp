"""
库存可发数量计算服务

从 batch_service.py 提取，职责单一：异步可出货量计算。
同步版本位于 shared/stock_crud_service.py。

TODO(multi-sku-order): 本模块多处 SQL 直接引用 Order.product_id/Order.quantity/
Order.order_type/Order.country（where 条件、累加逻辑）。多 SKU 模型下这些为首 item
兼容值，完整改造涉及业务语义变更，待后续 spec 改造为 JOIN OrderItem。
当前依赖 Task 3 设置的兼容值。
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import Order, StockOut

logger = logging.getLogger(__name__)


async def calculate_available_shipment_quantity(
    db: AsyncSession, product_id: int, customer: str,
    order_type: str | None = None, country: str | None = None
) -> dict:
    """
    计算指定客户和产品的可出货量

    业务规则：
    1. 出货量严格受限于订单量
    2. 备货量只能通过订单抵扣使用，不能直接出货
    3. 可出货量 = 订单总量 - 已出货量（非抵扣出货）
    4. 当指定 order_type 时，仅计算该类型订单（逻辑隔离）
    """
    # 历史兼容：'normal' 在数据库中与 'regular' 等价
    if order_type == 'normal':
        order_type = 'regular'

    where_clause = [Order.product_id == product_id, Order.customer == customer]
    if order_type:
        if order_type == 'regular':
            where_clause.append(Order.order_type.in_(['regular', 'normal']))
        else:
            where_clause.append(Order.order_type == order_type)
            if country:
                where_clause.append(Order.country == country)

    result = await db.execute(
        select(Order)
        .where(*where_clause)
        .order_by(Order.order_date.asc())
        .with_for_update()
    )
    orders = result.scalars().all()

    if not orders:
        return {
            'order_quantity': 0,
            'shipped_quantity': 0,
            'available_quantity': 0,
            'regular_available': 0,
            'custom_available': 0,
            'orders': []
        }

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
    shipped_map = dict(shipped_result.all())

    total_order_quantity = 0
    regular_order_quantity = 0
    custom_order_quantity = 0
    regular_shipped = 0
    custom_shipped = 0
    order_details = []

    for order in orders:
        # TODO(multi-sku-order): 遍历累加 order.quantity/order_type/country 在多 SKU 下语义变更，待后续 spec 改造为遍历 order.items；当前依赖兼容值。
        total_order_quantity += order.quantity
        _order_type = order.order_type or 'regular'
        _country = order.country or ''
        non_deduction_shipped = shipped_map.get(order.id, 0)

        if _order_type in ('regular', 'normal'):  # 'normal' 为历史数据兼容
            regular_order_quantity += order.quantity
            regular_shipped += non_deduction_shipped
        else:
            custom_order_quantity += order.quantity
            custom_shipped += non_deduction_shipped

        order_details.append({
            'order_id': order.id,
            'order_no': order.order_no,
            'quantity': order.quantity,
            'shipped': non_deduction_shipped,
            'available': order.quantity - non_deduction_shipped,
            'order_type': _order_type,
            'country': _country
        })

    total_shipped = sum(shipped_map.values())

    available_quantity = max(0, total_order_quantity - total_shipped)

    return {
        'order_quantity': total_order_quantity,
        'shipped_quantity': total_shipped,
        'available_quantity': available_quantity,
        'regular_available': max(0, regular_order_quantity - regular_shipped),
        'custom_available': max(0, custom_order_quantity - custom_shipped),
        'orders': order_details
    }
