"""P1-03 回归：整单预锁集合必须包含 OrderItem 产品，并按 id 升序加锁。"""
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.order import commands


async def test_prelock_includes_order_items_and_sorts_ascending():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[
        MagicMock(scalar_one_or_none=MagicMock(return_value=91)),          # order.product_id
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[7])))),   # stock_out
        MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[42])))),  # order_item
    ])
    locked: list[int] = []

    async def _fake_lock(_db, pid):
        locked.append(pid)

    original = commands.get_product_for_update
    commands.get_product_for_update = _fake_lock
    try:
        await commands._prelock_order_products(db, 7)
    finally:
        commands.get_product_for_update = original

    assert locked == [7, 42, 91]
