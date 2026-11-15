"""`update_stockin_core` 的加锁顺序必须是 **Product → StockIn**。

修复背景
--------
本函数原实现先 `select(StockIn) ... .with_for_update()`，改数量时才
`get_product_for_update()` —— 与仓库其余路径（order_deduction_service、
stock_in_service.update_stockin / delete_stockin、批量建单）**相反**。
两条路径命中同一 (product, stockin) 时互相等锁，PostgreSQL 死锁检测会回滚其一
（表现为 500/409，无数据损坏，但用户看到「操作失败」）。

修复
----
1) 先**无锁读** `StockIn.product_id`（该列 NOT NULL 且不可改，只用来知道锁谁）；
2) `get_product_for_update()` 锁 Product；
3) 再 `select(StockIn) ... .with_for_update()` 锁 StockIn 并重新读取行；
4) `old_quantity` 必须取自**加锁后**的行（无锁读到的数量可能已被并发改过）。

测试边界
--------
用录制式 mock 会话按执行顺序记录「谁先加锁」，把 SQLAlchemy 语句按 PostgreSQL
方言编译成字面量 SQL 后判定语句种类，不连数据库（与
fastapi_app/tests/test_order_batch_lock_order.py 的单元部分同款范式）。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from fastapi_app.services import stock_in_service


def _sql(stmt) -> str:
    """把 SQLAlchemy 语句编译成 PostgreSQL 字面量 SQL（用于判定语句种类）。"""
    return str(stmt.compile(dialect=postgresql.dialect()))


def _make_product(product_id: int, current_stock: int = 100):
    product = MagicMock()
    product.id = product_id
    product.name = f'产品{product_id}'
    product.current_stock = current_stock
    product.version = 1
    return product


def _make_stockin(stockin_id: int = 5, product_id: int = 77, quantity: int = 5):
    stockin = MagicMock()
    stockin.id = stockin_id
    stockin.product_id = product_id
    stockin.quantity = quantity
    stockin.stockin_no = 'ST-5'
    return stockin


def _make_db(events: list, product_id: int, stockin_row):
    """录制式会话：按调用顺序把事件追加进 events。

    事件种类：
        ('execute', sql)      —— 下发的任一 SELECT/UPDATE
        ('product_lock',)     —— 对 Product 取行锁（get_product_for_update）
    """
    db = MagicMock()

    async def _execute(stmt, *args, **kwargs):
        sql = _sql(stmt)
        events.append(('execute', sql))
        result = MagicMock()
        # 快照读与加锁读都返回同一行：本测试只关心「谁先谁后」，
        # 行内容由 stockin_row 决定（None 表示记录不存在）。
        result.scalar_one_or_none = MagicMock(return_value=stockin_row)
        return result
    db.execute = AsyncMock(side_effect=_execute)
    db.flush = AsyncMock()
    return db


async def _run_core(events, *, product_id=77, stockin_row=None, incoming=None, quantity=5):
    """跑一次 update_stockin_core，返回 (result, db, product)。"""
    stockin_row = stockin_row or _make_stockin(product_id=product_id)
    product = _make_product(product_id)
    db = _make_db(events, product_id, stockin_row)

    async def _lock_product(_db, _product_id):
        events.append(('product_lock',))
        assert _product_id == product_id
        return product

    apply_delta = AsyncMock(return_value=product)
    log_inventory = MagicMock()
    with (
        patch('fastapi_app.services.stock_service.get_product_for_update', side_effect=_lock_product),
        patch.object(stock_in_service, 'apply_stock_delta_locked', apply_delta),
        patch('fastapi_app.services.stock_service.log_inventory_change', log_inventory),
    ):
        result = await stock_in_service.update_stockin_core(
            db, incoming or _make_stockin(product_id=product_id),
            quantity, '客户A', MagicMock(), '备注',
        )
    return result, db, product, apply_delta


def _index_of(kind, events):
    return [i for i, event in enumerate(events) if event[0] == kind]


@pytest.mark.asyncio
async def test_product_locked_before_stockin_row_lock():
    """Product 行锁必须早于 StockIn 的 `FOR UPDATE`（统一锁序 Product → StockIn）。"""
    events: list = []
    await _run_core(events, quantity=9)

    product_lock_at = _index_of('product_lock', events)
    assert product_lock_at, '没有对 Product 取锁'
    stockin_lock_at = [
        i for i, event in enumerate(events)
        if event[0] == 'execute' and 'FOR UPDATE' in event[1].upper()
    ]
    assert stockin_lock_at, '没有对 StockIn 取锁'
    assert product_lock_at[0] < stockin_lock_at[0], (
        f'锁序反了：先锁 StockIn（事件 {stockin_lock_at[0]}）后锁 Product'
        f'（事件 {product_lock_at[0]}）；事件序列={events}'
    )


@pytest.mark.asyncio
async def test_unlocked_snapshot_read_happens_before_any_lock():
    """第 1 步必须是无锁快照读（不带 FOR UPDATE）：用来判存在、并决定要不要锁 Product。

    这条也顺带保证「数量没变时不必锁 Product」——锁了反而与既有语义不一致。
    """
    events: list = []
    await _run_core(events, quantity=9)

    assert events[0][0] == 'execute'
    first_sql = events[0][1]
    assert 'FOR UPDATE' not in first_sql.upper(), f'第一条 SQL 不应加锁，实际={first_sql}'


@pytest.mark.asyncio
async def test_same_quantity_does_not_lock_product():
    """只改文本（数量不变）时不应锁 Product：省一次行锁，且不改变既有语义。"""
    events: list = []
    _, _, _product, apply_delta = await _run_core(events, quantity=5)
    assert not _index_of('product_lock', events), '数量未变却锁了 Product'
    apply_delta.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_quantity_taken_from_locked_row():
    """old_quantity 必须取自加锁后的行：传入对象是旧快照时不能拿它算差值。

    传入 StockIn(quantity=1)，加锁后读到的行是 quantity=5，本次改成 5 →
    没有库存变化，`apply_stock_delta_locked` 不应被调用。
    """
    events: list = []
    incoming = _make_stockin(quantity=1)
    locked_row = _make_stockin(quantity=5)
    _, _, _, apply_delta = await _run_core(events, stockin_row=locked_row, incoming=incoming, quantity=5)

    apply_delta.assert_not_called()
    assert locked_row.quantity == 5


@pytest.mark.asyncio
async def test_delta_computed_against_locked_row_quantity():
    """差值按加锁行的数量算：5 → 9 时 delta=+4。"""
    events: list = []
    incoming = _make_stockin(quantity=1)
    locked_row = _make_stockin(quantity=5)
    _, _, product, apply_delta = await _run_core(
        events, stockin_row=locked_row, incoming=incoming, quantity=9,
    )

    apply_delta.assert_awaited_once()
    assert apply_delta.await_args.args[1] is product
    assert apply_delta.await_args.args[2] == 4


@pytest.mark.asyncio
async def test_missing_stockin_raises_without_writing():
    """行不存在时抛 ValueError，不得写库存/流水（锁了 Product 也无妨，事务会回滚）。"""
    events: list = []
    db = _make_db(events, product_id=77, stockin_row=None)
    apply_delta = AsyncMock()
    log_inventory = MagicMock()
    with (
        patch('fastapi_app.services.stock_service.get_product_for_update', new=AsyncMock()),
        patch.object(stock_in_service, 'apply_stock_delta_locked', apply_delta),
        patch('fastapi_app.services.stock_service.log_inventory_change', log_inventory),
    ):
        with pytest.raises(ValueError, match='入库记录不存在'):
            await stock_in_service.update_stockin_core(
                db, _make_stockin(), 9, '客户A', MagicMock(), '备注',
            )
    apply_delta.assert_not_awaited()
    log_inventory.assert_not_called()
    db.flush.assert_not_awaited()
