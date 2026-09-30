"""改订单数量必须同步明细行（回归守卫）

缺陷背景（2026-09-30）：把客户订单 PO-20260930-0005 的数量从 10000 改成 8888 后，
客户订单页显示 8888，但贝莱订单页/外包订单页/采购页仍显示 10000。

根因：`_update_order_directly` 只写 `order.quantity`，**不碰 `order_item.quantity`**；
而列表页显示的数量取自明细行——`_build_beile_order_record` 里
`record['quantity'] = first_item.quantity`、`items[].quantity = item.quantity`
（外包页同样按 SKU 汇总）。实测该订单改后主表 8888、明细仍 10000，
且全库「主表与明细数量不一致」的订单恰好只有这一张。

本文件锁死不变量：**修改订单数量后，明细行数量必须与订单数量一致**。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services import order_service


def _make_order(order_id: int, quantity: int) -> MagicMock:
    order = MagicMock()
    order.id = order_id
    order.order_no = "PO-20260930-0005"
    order.quantity = quantity
    order.customer = "客户"
    order.note = ""
    order.is_locked = False
    order.is_deleted = False
    order.locked_by_id = None
    order.order_type = "regular"
    order.product_id = 1
    return order


def _make_item(item_id: int, order_id: int, quantity: int) -> MagicMock:
    item = MagicMock()
    item.id = item_id
    item.order_id = order_id
    item.quantity = quantity
    return item


def _mock_db_for(order, items) -> AsyncMock:
    """同一个 execute 返回既要供订单查询（scalar_one_or_none）也要供明细查询（scalars().all()）"""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = order
    result.scalars.return_value.all.return_value = items
    db.execute = AsyncMock(return_value=result)
    db.info = {}
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_edit_quantity_syncs_single_item():
    order = _make_order(1, 10000)
    item = _make_item(11, 1, 10000)
    db = _mock_db_for(order, [item])

    user = MagicMock()
    user.is_super = True
    user.id = 1
    user.username = "admin"

    with patch(
        "fastapi_app.services.order.commands.get_product_for_update",
        new_callable=AsyncMock, return_value=MagicMock(id=1, current_stock=100),
    ), patch(
        "fastapi_app.services.order._common._safe_publish_event", new_callable=AsyncMock,
    ):
        await order_service.update_order(
            db, order_id=1, quantity=8888, customer="客户", note="", current_user=user,
        )

    assert order.quantity == 8888
    assert item.quantity == 8888, (
        "明细行数量未同步：列表页（贝莱/外包/采购）显示的是 order_item.quantity，"
        "只改主表会让这些页面永远停留在旧数量"
    )


@pytest.mark.asyncio
async def test_multi_item_order_items_left_untouched():
    """多 SKU 下「改哪一个」语义未定（见代码内 TODO），此时不得擅自改动明细"""
    order = _make_order(2, 300)
    items = [_make_item(21, 2, 100), _make_item(22, 2, 200)]
    db = _mock_db_for(order, items)

    user = MagicMock()
    user.is_super = True
    user.id = 1
    user.username = "admin"

    with patch(
        "fastapi_app.services.order.commands.get_product_for_update",
        new_callable=AsyncMock, return_value=MagicMock(id=1, current_stock=100),
    ), patch(
        "fastapi_app.services.order._common._safe_publish_event", new_callable=AsyncMock,
    ):
        await order_service.update_order(
            db, order_id=2, quantity=999, customer="客户", note="", current_user=user,
        )

    assert [i.quantity for i in items] == [100, 200], "多 SKU 订单的明细不应被静默改写"


@pytest.mark.asyncio
async def test_approval_edit_quantity_syncs_item():
    """非超管的编辑走审批：审批通过后应用修改时，明细同样必须被同步。

    与直改（_update_order_directly）是同一类问题——只写 order.quantity 会让
    列表页继续显示旧数量。
    """
    import json as _json

    from fastapi_app.services import approval_service

    order = _make_order(3, 10000)
    item = _make_item(31, 3, 10000)
    db = _mock_db_for(order, [item])

    approval = MagicMock()
    approval.operation_data = _json.dumps({"quantity": 8888, "customer": "客户"})

    with patch(
        "fastapi_app.services.approval_service.get_product_for_update",
        new_callable=AsyncMock, return_value=MagicMock(id=1, current_stock=100),
    ):
        await approval_service._handle_edit_approval(db, approval, order)

    assert order.quantity == 8888
    assert item.quantity == 8888, "审批通过的改数量未同步明细，列表页仍显示旧数量"
