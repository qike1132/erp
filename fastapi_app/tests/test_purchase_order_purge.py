"""采购单子表清理的单一实现回归（2026-10-30 审计 A-M19）。

三条删除路径（单张删除、批量删除、订单删除后的兜底清理）此前各写一套子表清理，
其中两处直接 `db.delete(po)` 依赖 ORM 级联——而 `PurchaseOrder.items` / `skus`
都是 `lazy='raise'` + `delete-orphan`，级联需要先加载集合，flush 时抛
InvalidRequestError；`purchase_order_item` 的 FK 又是 NO ACTION，没删干净就是 409。

现在统一为 `purge_purchase_order_children`：一条 DELETE 明细 + 一条 DELETE SKU 快照，
不触碰 ORM 集合、不依赖数据库外键级联开关。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.purchase_order_purge import purge_purchase_order_children


def _db(rowcount=2):
    result = MagicMock()
    result.rowcount = rowcount
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={'literal_binds': True}))


@pytest.mark.asyncio
async def test_purges_items_and_skus_for_all_ids():
    db = _db(rowcount=3)

    affected = await purge_purchase_order_children(db, [7, 8])

    assert affected == 3
    assert db.execute.await_count == 2
    sqls = [_sql(c.args[0]) for c in db.execute.await_args_list]
    assert 'purchase_order_item' in sqls[0]
    assert 'purchase_order_sku' in sqls[1]
    for sql in sqls:
        assert 'IN (7, 8)' in sql


@pytest.mark.asyncio
async def test_empty_ids_issues_no_sql():
    db = _db()

    assert await purge_purchase_order_children(db, []) == 0
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_rowcount_is_tolerated():
    """rowcount 只用于日志：驱动/替身没有该属性时不得让删除失败。"""
    result = object()
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    assert await purge_purchase_order_children(db, [1]) == 0
    assert db.execute.await_count == 2
