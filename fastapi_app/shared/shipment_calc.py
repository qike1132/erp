"""
库存可发量汇总计算（同步/异步版本共用纯函数）

从 inventory_service.py（异步）与 shared/stock_crud_service.py（同步，已移除）中提取，
两份实现曾各自维护一份相同的累加逻辑，容易在修改时漂移。
本模块只做纯计算，不依赖任何 Web 框架与数据库会话。
"""
from __future__ import annotations

from collections.abc import Sequence

from fastapi_app.shared_models import Order


def build_shipment_summary(orders: Sequence[Order], shipped_map: dict[int, int]) -> dict:
    """根据订单列表与已出货映射，组装可出货量汇总与订单明细。

    Args:
        orders: 已按 order_date 升序的订单列表（可能为空）
        shipped_map: {order_id: 净出货量}（已扣除退货，且排除入库抵扣）

    Returns:
        dict: { order_quantity, shipped_quantity, available_quantity, orders }
    """
    if not orders:
        return {
            'order_quantity': 0,
            'shipped_quantity': 0,
            'available_quantity': 0,
            'orders': [],
        }

    total_order_quantity = 0
    order_details = []

    for order in orders:
        # TODO(multi-sku-order): 遍历累加 order.quantity 在多 SKU 下语义变更，
        # 待后续 spec 改造为遍历 order.items；当前依赖兼容值。
        total_order_quantity += order.quantity
        non_deduction_shipped = shipped_map.get(order.id, 0)

        order_details.append({
            'order_id': order.id,
            'order_no': order.order_no,
            'quantity': order.quantity,
            'shipped': non_deduction_shipped,
            'available': order.quantity - non_deduction_shipped,
        })

    total_shipped = sum(shipped_map.values())
    available_quantity = max(0, total_order_quantity - total_shipped)

    return {
        'order_quantity': total_order_quantity,
        'shipped_quantity': total_shipped,
        'available_quantity': available_quantity,
        'orders': order_details,
    }
