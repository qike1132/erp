"""订单抵扣：自定义抵扣量必须同时受「可用备货」和「订单数量」收口（2026-10-17 审计 P1-17）。

现场：前端「抵扣备货」只在开启那一刻按 min(数量, 可用) 算一次，之后把订单数量改小不回收，
编辑弹窗里的 `max` 属性也挡不住键入。后端 `process_order_deduction` 原先只按
`min(请求, 可用)` 收口 —— 于是「3 件的订单扣 10 件备货」能一路落库：

    订单 quantity=3，stock_out 有一条 quantity=10（note='[订单抵扣] …'），inventory_log 扣 10。

前端已按同一口径拦截（`deductRules.deductLimit`），但直连 API / 批量导入 / 旧前端仍可能传大值，
所以后端这一层必须自己收口：**抵扣量 ≤ min(自定义量, 可用备货, 订单数量)**。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.order_deduction_service import process_order_deduction


def _stockin(stockin_id: int = 1, quantity: int = 10) -> MagicMock:
    """一笔可用 10 件的备货（无历史抵扣）。"""
    si = MagicMock()
    si.id = stockin_id
    si.product_id = 1
    si.stockin_no = 'SI-1'
    si.quantity = quantity
    si.stockin_stockouts = []
    return si


def _db_with(stockins: list) -> MagicMock:
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = stockins
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    return db


def _order(order_quantity: int) -> MagicMock:
    order = MagicMock()
    order.id = 7
    order.order_no = 'PO-TEST-1'
    order.customer = '贝乐'
    order.quantity = order_quantity
    order.status = 'pending'
    return order


async def _run(db, order, order_quantity: int, custom: int | None):
    with (
        patch(
            'fastapi_app.services.order_deduction_service.get_product_for_update',
            AsyncMock(return_value=MagicMock(id=1)),
        ),
        patch(
            'fastapi_app.services.order_deduction_service.generate_stockout_number',
            AsyncMock(return_value='SO-TEST-1'),
        ),
        patch(
            'fastapi_app.services.order_deduction_service.update_stock_with_optimistic_lock',
            AsyncMock(),
        ) as mock_update,
        patch(
            'fastapi_app.services.order_deduction_service.compute_order_status_from_db',
            AsyncMock(return_value='pending'),
        ),
    ):
        amount, details = await process_order_deduction(
            db, order, product_id=1, order_quantity=order_quantity,
            deduct_stock=True, custom_deduct_quantity=custom,
        )
    return amount, details, mock_update


def _added_stockout(db) -> MagicMock:
    """db.add 里**唯一**的那条 StockOut。

    不用 `hasattr(obj, 'stockout_no')` 兜底：MagicMock 对任意属性都返回真，
    兜底会让「db.add 里塞了别的对象」也静默通过，断言就失去意义。
    """
    stockouts = [
        call.args[0] for call in db.add.call_args_list
        if call.args[0].__class__.__name__ == 'StockOut'
    ]
    assert len(stockouts) == 1, f'应恰好创建 1 条 StockOut，实际 {len(stockouts)}'
    return stockouts[0]


@pytest.mark.asyncio
async def test_custom_deduct_clamped_by_order_quantity():
    """订单数量 3、可用备货 10、请求抵扣 10 → 只能扣 3（原实现扣 10）。"""
    db = _db_with([_stockin(quantity=10)])
    amount, details, mock_update = await _run(db, _order(3), order_quantity=3, custom=10)

    assert amount == 3
    assert details[0]['deduct_amount'] == 3
    assert _added_stockout(db).quantity == 3
    # 库存扣减与抵扣量必须一致，否则台账与 stock_out 对不上
    mock_update.assert_awaited_once_with(db, 1, -3)


@pytest.mark.asyncio
async def test_custom_deduct_still_clamped_by_available_stock():
    """订单数量 10、可用备货 4、请求抵扣 10 → 仍按可用备货 4 收口（原有行为不回归）。"""
    db = _db_with([_stockin(quantity=4)])
    amount, _details, _mock_update = await _run(db, _order(10), order_quantity=10, custom=10)

    assert amount == 4


@pytest.mark.asyncio
async def test_custom_deduct_within_order_quantity_kept_as_requested():
    """订单数量 10、可用备货 10、请求抵扣 6 → 照用户意愿扣 6（不擅自放大）。"""
    db = _db_with([_stockin(quantity=10)])
    amount, _details, _mock_update = await _run(db, _order(10), order_quantity=10, custom=6)

    assert amount == 6
    assert _added_stockout(db).quantity == 6
