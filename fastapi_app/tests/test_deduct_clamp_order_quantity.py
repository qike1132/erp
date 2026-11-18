"""抵扣量按订单数量收口，且明细记的值必须与实扣同口径（2026-10-17 审计 P1-17）。

`process_order_deduction` 只扣 `min(自定义量, 可用备货, 订单数量)`。明细
`OrderItem.deduct_quantity` 若照抄请求值，「3 件的订单填 10 件抵扣」就会落成
`stock_out.quantity=3` + `order_item.deduct_quantity=10` —— 订单明细/对账读到的抵扣
与库存流水永久对不上，而且没有任何提示。本用例把「收口函数」与「暂存确认写明细」
两处钉在一起。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi_app.services.order_deduction_service import clamp_deduct_to_quantity
from fastapi_app.services.staging.order import _confirmed_order_item
from fastapi_app.shared_models import Order

RECENT_AUDIT = 'P1-17'  # 便于回溯审计条目


def _staging(**over) -> SimpleNamespace:
    base = {
        'deduct_stock': True,
        'deduct_quantity': 10,
        'quantity': 3,
        'product_id': 9001,
        'note': '',
    }
    base.update(over)
    return SimpleNamespace(**base)


def _order(quantity: int = 3) -> Order:
    return Order(
        id=1, order_no='PO-CLAMP-1', customer='客户A', product_id=9001,
        quantity=quantity, status='待备货', is_deleted=False,
    )


def _product() -> MagicMock:
    product = MagicMock()
    product.name = '产品A'
    product.barcode = 'BC-CLAMP'
    return product


def test_clamp_deduct_to_quantity_cases():
    """收口语义：≤ 订单数量，永不放大，非正数归零。"""
    assert clamp_deduct_to_quantity(10, 3) == 3    # 本次要消灭的形态
    assert clamp_deduct_to_quantity(3, 10) == 3    # 未超量：按用户意愿
    assert clamp_deduct_to_quantity(10, 10) == 10  # 边界相等
    assert clamp_deduct_to_quantity(0, 10) == 0    # 未填
    assert clamp_deduct_to_quantity(None, 10) == 0  # 未开启抵扣
    assert clamp_deduct_to_quantity(-5, 10) == 0   # 脏输入
    assert clamp_deduct_to_quantity(10, 0) == 0    # 订单数量缺失


def test_confirmed_order_item_records_clamped_deduct_quantity():
    """暂存确认写明细时用的是与实扣同口径的收口值，不是请求值。"""
    item = _confirmed_order_item(
        _order(quantity=3), _staging(), _product(),
        clamp_deduct_to_quantity(10, 3),
    )

    assert item.quantity == 3
    assert item.deduct_quantity == 3, f'{RECENT_AUDIT}：明细必须与实扣同口径'
    assert item.deduct_stock is True


def test_confirmed_order_item_records_zero_when_deduct_disabled():
    """未开启抵扣时明细记 0（调用方传 0），不会把暂存行里的残留值写进去。"""
    item = _confirmed_order_item(
        _order(quantity=10), _staging(deduct_stock=False, deduct_quantity=0, quantity=10),
        _product(), 0,
    )

    assert item.deduct_quantity == 0


def test_write_confirmed_order_passes_clamped_value_to_item_and_deduction():
    """调用点守卫：暂存确认把**收口值**同时给明细与落扣（源码级，防被改回请求值）。

    `_confirmed_order_item` 是纯函数，单测只能证明它「会」用收口值；
    这里锁住 `_write_confirmed_order` 真的把 `deduct_qty` 传进去（回退即失败）。
    """
    import inspect

    from fastapi_app.services.staging import order as staging_order

    src = inspect.getsource(staging_order._write_confirmed_order)
    assert '_confirmed_order_item(order, staging, product, deduct_qty)' in src
    assert 'custom_deduct_quantity=deduct_qty' in src
    assert 'clamp_deduct_to_quantity(staging.deduct_quantity, staging.quantity)' in src


def test_batch_create_uses_clamped_value_for_item_and_deduction():
    """批量下单两条路径都用收口值：写明细（_create_order_items）与落扣（_apply_deductions）。"""
    import inspect

    from fastapi_app.services import order_batch_create as obc

    src = inspect.getsource(obc)
    expect = "clamp_deduct_to_quantity(it['deduct_quantity'], it['quantity'])"
    assert src.count(expect) == 2, '明细与落扣必须各有一处收口'
    assert "custom_deduct_quantity=it['deduct_quantity']" not in src, '落扣不得再用未收口的请求值'
