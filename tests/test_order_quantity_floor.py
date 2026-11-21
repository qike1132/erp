"""M-2 回归：整单/明细改量的数量下限守卫（2026-11-21 全量审计）。

_update_order_directly 此前对 order.quantity 无下限守卫——把已出货 50 的订单
改成 10，派生状态恒「已出货」、明细可用量恒负；明细改量入口对已抵扣量同样
无守卫。修复：整单下限 = max(Σ明细已抵扣, Σ出库净量)，明细下限 = 已抵扣量。
"""
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from fastapi_app.services.order import commands as order_commands
from fastapi_app.shared_models import Order, OrderItem, Product, StockOut


async def _make_order_with_shipment(db, *, shipped: int, deducted: int) -> tuple[Order, OrderItem]:
    """product.name / order.order_no / stockout_no 都是唯一列，按用例随机化。"""
    suffix = uuid4().hex[:8]
    product = Product(name=f'守卫产品P-{suffix}', current_stock=500)
    db.add(product)
    await db.flush()
    order = Order(order_no=f'FLOOR-{suffix}', customer='客户甲', quantity=100,
                  order_date=datetime(2026, 11, 1, tzinfo=UTC), status='pending')
    db.add(order)
    await db.flush()
    order.product_id = product.id  # 首 SKU 兼容值：整单改量的库存调整走它
    item = OrderItem(order_id=order.id, product_id=product.id, quantity=100,
                     product_name=f'守卫产品P-{suffix}', deduct_quantity=deducted)
    db.add(item)
    if shipped:
        db.add(StockOut(stockout_no=f'FLOOR-SO-{suffix}', stockout_date=datetime(2026, 11, 1, tzinfo=UTC),
                        product_id=product.id, quantity=shipped, customer='客户甲',
                        order_id=order.id, returned_quantity=0))
    await db.flush()
    return order, item


class _FakeUser:
    id = 1
    username = 'tester'


async def test_update_order_rejects_quantity_below_shipped(app_on_test_db, async_db_session):
    db = async_db_session
    order, _item = await _make_order_with_shipment(db, shipped=50, deducted=50)

    with pytest.raises(ValueError, match='不得低于已抵扣/已出库量'):
        await order_commands._update_order_directly(
            db, order, order.id, 10, '客户甲', '', _FakeUser())


async def test_update_order_allows_quantity_above_floor(app_on_test_db, async_db_session):
    db = async_db_session
    order, _item = await _make_order_with_shipment(db, shipped=50, deducted=50)

    result = await order_commands._update_order_directly(
        db, order, order.id, 80, '客户甲', '', _FakeUser())
    assert result['success'] is True
    assert order.quantity == 80


async def test_update_item_rejects_quantity_below_deducted(app_on_test_db, async_db_session):
    db = async_db_session
    _order, item = await _make_order_with_shipment(db, shipped=0, deducted=50)

    with pytest.raises(ValueError, match='不得低于已抵扣量'):
        await order_commands.update_order_item(db, item.id, 10, None, _FakeUser())
