"""退货列表的工厂隔离回归（2026-10-30 审计 A-M6）。

读端点里其它库存列表（stockouts / stockins）都按 `factory_scope_of(user)` 过滤，
唯独退货列表没接工厂参数：厂绑定用户能看到他厂产品的退货记录。
修复：`get_stockreturns(..., factory=...)` 用 EXISTS 子查询把工厂条件下推到 SQL，
保证 count 与分页同口径（在 Python 层过滤会让 total 与页内容不一致）。
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.stock_inventory_service import get_stockreturns


def _db():
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    rows_result = MagicMock()
    rows_result.scalars.return_value.unique.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[count_result, rows_result])
    return db


def _sql(statement) -> str:
    return str(statement.compile(compile_kwargs={'literal_binds': True}))


@pytest.mark.asyncio
async def test_factory_condition_is_pushed_into_count_and_page_sql():
    db = _db()

    await get_stockreturns(db, factory='东莞')

    count_stmt = db.execute.await_args_list[0].args[0]
    page_stmt = db.execute.await_args_list[1].args[0]
    for stmt in (count_stmt, page_stmt):
        sql = _sql(stmt)
        assert 'product.factory' in sql
        assert 'EXISTS' in sql.upper()
        assert '东莞' in sql


@pytest.mark.asyncio
async def test_no_factory_condition_when_unscoped():
    db = _db()

    await get_stockreturns(db, factory=None)

    sql = _sql(db.execute.await_args_list[0].args[0])
    assert 'product.factory' not in sql


@pytest.mark.asyncio
async def test_factory_condition_combines_with_other_filters():
    """工厂条件与客户/日期筛选取交集，不能互相覆盖（AND 组合）。"""
    db = _db()

    await get_stockreturns(db, customer='客户A', factory='湖北')

    sql = _sql(db.execute.await_args_list[0].args[0])
    assert 'product.factory' in sql
    assert 'stock_return.customer' in sql
    assert ' AND ' in sql.upper()
