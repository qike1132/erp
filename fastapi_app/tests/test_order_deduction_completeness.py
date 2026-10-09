"""P1-8 抵扣完整性校验：抵扣不足时报错，并回报实际生效量。

背景（docs/optimization-plan-2026-10-01-round3.md:167）
---------------------------------------------------
fastapi_app/services/order/deduction.py 的抵扣链路存在「静默截断 / 假报成功」窗口：
_decrease_deduction 结尾不校验未消化的 reduce_amount；update_deduct_quantity 结尾
无条件返回 success=True，且回报的是请求量而不是实际生效量。

本文件覆盖
----------
1) 预检与尾部兜底：可用备货 / 现有抵扣不足时，在写任何 StockOut、InventoryLog 或
   库存变更之前抛 ValueError（文案含还差多少件），不得静默返回；
2) 返回值语义：deduct_quantity 以 flush 后从会话重新聚合的实际生效量为准，任何
   「未完全生效」路径都不返回 success=True；
3) 事务边界：函数内不 commit / rollback（失败回滚由端点 db_transaction 提供）；
   真实测试库用例证明失败路径不留下部分抵扣（StockOut / InventoryLog / 库存零残留）。
"""
import os
import re
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from fastapi_app.services.order.deduction import (
    _decrease_deduction,
    update_deduct_quantity,
)
from fastapi_app.shared_models import InventoryLog, Order, Product, StockIn, StockOut

_USER = SimpleNamespace(id=1, username='janitor', role='admin')

_DB_PREFIX = 'JANITOR-DEDUCT-'
_DB_PRODUCT_ID = 9301
_DB_PRODUCT_STOCK = 100
_DB_STOCKIN_QTY = 30


def _nth_index(seq, value, n):
    """第 n 次（1 起）出现 value 的下标，缺失即断言失败。"""
    index = -1
    for _ in range(n):
        index = seq.index(value, index + 1)
    return index


# ---------------------------------------------------------------------------
# 内存版会话替身
# ---------------------------------------------------------------------------
class _Result:
    """最小 Result 替身：支持 all / scalars().all / scalar / scalar_one_or_none。"""

    def __init__(self, rows=(), scalar=None, rowcount=0):
        self._rows = rows
        self._scalar = scalar
        self.rowcount = rowcount

    def all(self):
        return self._rows

    def scalars(self):
        return self

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar


class _Savepoint:
    """begin_nested 替身（乐观锁写入口内部使用）。"""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _ShrinkingRows(list):
    """故障注入：第 2 次迭代只返回 second_pass，模拟校验与消化之间的并发改动。"""

    def __init__(self, items, second_pass=()):
        super().__init__(items)
        self._second = list(second_pass)
        self._passes = 0

    def __iter__(self):
        self._passes += 1
        return iter(list(self)) if self._passes == 1 else iter(self._second)


def _update_values(statement) -> dict:
    """取出 UPDATE 语句的 SET 值（列名 -> 值），供 refresh 替身同步内存对象。"""
    values: dict = {}
    for column, value in (getattr(statement, '_values', None) or {}).items():
        key = getattr(column, 'key', None) or str(column)
        values[key] = getattr(value, 'value', value)
    return values


class _LedgerSession:
    """内存版会话替身：模拟抵扣链路用到的 SELECT / UPDATE / add / delete / flush。

    行数据直接用真实 ORM 实体（StockIn / StockOut），循环内的 quantity 变更与
    db.delete 因此能被后续聚合查询如实读到 —— 重算实际生效量这一步是真的
    「从会话状态聚合」，而不是照抄请求量。
    """

    def __init__(self, *, product, order=None, stockins=(), stockouts=(), stockout_rows=None, returns=()):
        self.product = product
        self.order = order
        self.stockins = list(stockins)
        self.rows = list(stockouts)
        self.stockout_rows = self.rows if stockout_rows is None else stockout_rows
        self.returns = list(returns)
        self.logs: list = []
        self.deleted: list = []
        self.statements: list = []
        self.timeline: list = []
        self.committed = 0
        self.rolled_back = 0
        self.last_update: dict = {}
        self._next_id = 6000

    # -- 会话接口 ---------------------------------------------------------
    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        if getattr(statement, '__visit_name__', '') == 'update':
            self.last_update = _update_values(statement)
            return _Result(rowcount=1)

        low = str(statement).lower()
        if 'select "order".product_id' in low:
            # 第十四轮：锁序预读（Product→Order）—— 无锁取 product_id（SQL 文本以
            # select "order".product_id 开头，与全列锁读可区分）
            return _Result(scalar=getattr(self.order, 'product_id', 1))
        if 'stock_in' in low:
            return _Result(rows=self.stockins)
        if 'stock_return' in low:
            return _Result(rows=self.returns)
        if 'stock_out' in low:
            if 'is null' in low:  # 独立出货量（订单状态派生）
                return _Result(scalar=self._shipped_total())
            if 'group by' not in low:  # 抵扣出库行列表（减少抵扣用）
                return _Result(rows=self.stockout_rows)
            key = 'order_id' if 'stock_out.order_id in' in low else 'stockin_id'
            self.timeline.append('aggregate:' + ('order' if key == 'order_id' else 'stockin'))
            return _Result(rows=list(self._deducted_by(key).items()))
        if 'from "order"' in low or re.search(r'from\s+order\b', low):
            return _Result(scalar=self.order)
        return _Result(scalar=self.product)

    def add(self, obj):
        if isinstance(obj, StockOut):
            self._stage_stockout(obj)
        else:
            self.logs.append(obj)

    def add_all(self, objs):
        for obj in objs:
            self.add(obj)

    async def delete(self, obj):
        self.deleted.append(obj)
        if obj in self.rows:
            self.rows.remove(obj)

    async def flush(self):
        self.timeline.append('flush')

    async def commit(self):
        self.committed += 1

    async def rollback(self):
        self.rolled_back += 1

    def begin_nested(self):
        return _Savepoint()

    async def refresh(self, obj):
        # 真实 DB 会从库中重读 UPDATE 后的值；替身据此同步内存对象
        # （update_stock_with_optimistic_lock 靠 refresh 同步 current_stock / version）
        if obj is self.product and self.last_update:
            for key, value in self.last_update.items():
                setattr(obj, key, value)
        return None

    def expunge(self, obj):
        return None

    # -- 内部 -------------------------------------------------------------
    def _stage_stockout(self, stockout):
        if stockout.id is None:
            stockout.id = self._next_id
            self._next_id += 1
        self.rows.append(stockout)

    def _deducted_by(self, key):
        agg: dict = {}
        for row in self.rows:
            if row.stockin_id is None:
                continue
            name = row.order_id if key == 'order_id' else row.stockin_id
            agg[name] = agg.get(name, 0) + max(0, row.quantity - (row.returned_quantity or 0))
        return agg

    def _shipped_total(self):
        return sum(
            max(0, row.quantity - (row.returned_quantity or 0))
            for row in self.rows
            if row.stockin_id is None
        )



# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------
def _make_product(stock=_DB_PRODUCT_STOCK, version=0):
    return Product(
        id=9001, name=_DB_PREFIX + '产品', factory='测试工厂',
        initial_stock=stock, current_stock=stock, version=version,
    )


def _make_order(order_id=1, quantity=100, customer='客户A'):
    return Order(
        id=order_id, order_no='DD-DEDUCT-' + str(order_id), customer=customer,
        product_id=9001, quantity=quantity, status='待备货', is_deleted=False,
    )


def _make_stockin(stockin_id=11, quantity=_DB_STOCKIN_QTY, customer='客户A'):
    return StockIn(
        id=stockin_id, stockin_no='BH-DEDUCT-' + str(stockin_id),
        customer=customer, product_id=9001, quantity=quantity,
    )


def _make_deduction_row(row_id=31, quantity=20, *, order_id=1, stockin_id=11, returned=0):
    return StockOut(
        id=row_id, stockout_no='SO-DEDUCT-' + str(row_id), product_id=9001,
        quantity=quantity, returned_quantity=returned, customer='客户A',
        order_id=order_id, stockin_id=stockin_id,
    )


def _make_return(return_id=1, *, stockout_id, status='active'):
    """指向某出货行的退货记录（真实 ORM 实体，便于断言 stockout_id 被置空）。"""
    from fastapi_app.shared_models import StockReturn

    return StockReturn(
        id=return_id, return_no='SR-DEDUCT-' + str(return_id), product_id=9001,
        quantity=5, stockout_id=stockout_id, status=status,
    )


@contextmanager
def _stubbed_side_effects():
    """隔离权限锁/缓存副作用（与本次断言无关），并固定备货号生成器。

    返回的 stub.numbers 记录「已生成备货号」序列 —— 断言失败路径一次都没调用，
    即证明报错发生在任何写操作之前。
    """
    stub = SimpleNamespace(numbers=[])
    cache = MagicMock()
    cache.invalidate = AsyncMock()

    async def _next_number(db):
        stub.numbers.append('SO-DEDUCT-N' + str(len(stub.numbers) + 1))
        return stub.numbers[-1]

    with (
        patch('fastapi_app.services.order.deduction._check_order_lock', new=AsyncMock()),
        patch('fastapi_app.services.order.deduction.cache_mgr', new=cache),
        patch('fastapi_app.services.order.deduction._safe_invalidate_purchase_cache', new=AsyncMock()),
        patch('fastapi_app.services.numbering.generate_stockout_number', new=_next_number),
    ):
        yield stub


@pytest.fixture(autouse=True)
def _deny_negative_stock(monkeypatch):
    """固定负库存策略为默认（拒绝），避免其它用例的 env 泄漏影响断言。"""
    monkeypatch.delenv('ALLOW_NEGATIVE_STOCK', raising=False)


def _updates(session):
    return [s for s in session.statements if getattr(s, '__visit_name__', '') == 'update']


# ---------------------------------------------------------------------------
# 单元：预检 / 尾部兜底（acceptance 1、3、4）
# ---------------------------------------------------------------------------
async def test_increase_shortfall_100_vs_30_raises_and_writes_nothing():
    """请求抵扣 100、可用 30 → 报错（说明还差 70），且零写操作。"""
    product = _make_product(stock=100)
    db = _LedgerSession(product=product, order=_make_order(), stockins=[_make_stockin(quantity=30)])

    with _stubbed_side_effects() as stub, pytest.raises(ValueError, match='可用备货不足，还需70件无法抵扣'):
        await update_deduct_quantity(db, 1, 100, _USER)

    assert stub.numbers == []          # 一个备货号都没生成
    assert db.rows == []               # 无 StockOut
    assert db.logs == []               # 无 InventoryLog
    assert db.deleted == []
    assert _updates(db) == []          # 库存未被触碰
    assert product.current_stock == 100 and product.version == 0
    assert db.committed == 0 and db.rolled_back == 0
    assert db.timeline == ['aggregate:order', 'aggregate:stockin']  # 只做了预检读取


async def test_increase_shortfall_sums_availability_across_stockins():
    """预检按全部备货行求和：30 + 5 = 35，请求 100 → 还差 65。"""
    product = _make_product(stock=100)
    db = _LedgerSession(
        product=product, order=_make_order(),
        stockins=[_make_stockin(stockin_id=11, quantity=30), _make_stockin(stockin_id=12, quantity=5)],
    )

    with _stubbed_side_effects() as stub, pytest.raises(ValueError, match='可用备货不足，还需65件无法抵扣'):
        await update_deduct_quantity(db, 1, 100, _USER)

    assert stub.numbers == [] and db.rows == [] and product.current_stock == 100


async def test_increase_shortfall_accounts_for_deduction_of_other_orders():
    """同一备货行已被别的订单抵扣 25 件时，本单可用量只有 5 件。"""
    product = _make_product(stock=100)
    other = _make_deduction_row(row_id=41, quantity=25, order_id=2, stockin_id=11)
    db = _LedgerSession(
        product=product, order=_make_order(), stockins=[_make_stockin(quantity=30)], stockouts=[other],
    )

    with _stubbed_side_effects() as stub, pytest.raises(ValueError, match='可用备货不足，还需5件无法抵扣'):
        await update_deduct_quantity(db, 1, 10, _USER)

    assert stub.numbers == [] and db.rows == [other] and product.current_stock == 100


async def test_decrease_beyond_existing_deduction_raises():
    """请求减少 50 件但现有抵扣只有 20 件 → 报错（还差 30），不删行、不改库存。"""
    product = _make_product(stock=80)
    row = _make_deduction_row(row_id=31, quantity=20)
    db = _LedgerSession(product=product, order=_make_order(), stockouts=[row])

    with pytest.raises(ValueError, match='现有抵扣量不足，还需30件无法减少'):
        await _decrease_deduction(db, db.order, 1, 50)

    assert db.deleted == []
    assert db.logs == []
    assert _updates(db) == []
    assert product.current_stock == 80 and product.version == 0
    assert [r.quantity for r in db.rows] == [20]
    assert db.committed == 0 and db.rolled_back == 0


async def test_decrease_tail_guard_catches_unconsumable_remaining():
    """尾部兜底：预检可见的量在消化阶段不可用（并发改动）时，不得静默返回 success。"""
    product = _make_product(stock=80)
    rows = _ShrinkingRows([_make_deduction_row(row_id=31, quantity=20)], second_pass=[])
    db = _LedgerSession(product=product, order=_make_order(), stockouts=[], stockout_rows=rows)

    with pytest.raises(ValueError, match='现有抵扣量不足，还需20件无法减少'):
        await _decrease_deduction(db, db.order, 1, 20)

    assert db.deleted == [] and db.logs == [] and _updates(db) == []
    assert product.current_stock == 80


async def test_decrease_rejects_row_with_active_return():
    """减少抵扣要整条删掉的出货行若被 active 退货引用，必须拒绝。

    回归 2026-10-09：_decrease_deduction 直删出货行、无退货守卫，撞迁移 072 的
    ON DELETE RESTRICT 会以未映射的 IntegrityError(500) 冒出来。active 退货保留台账。
    """
    product = _make_product(stock=80)
    row = _make_deduction_row(row_id=31, quantity=20, returned=5)
    db = _LedgerSession(
        product=product, order=_make_order(), stockouts=[row],
        returns=[_make_return(return_id=1, stockout_id=31, status='active')],
    )

    with pytest.raises(ValueError, match='退货'):
        await _decrease_deduction(db, db.order, 1, 15)

    assert db.deleted == []                      # 出货行未被删
    assert db.returns[0].stockout_id == 31       # 关联未被解除
    assert db.logs == [] and _updates(db) == []


async def test_decrease_detaches_cancelled_return_then_deletes():
    """已取消的退货不阻碍删除：解除关联后照常删除该出货行（退货行保留）。"""
    product = _make_product(stock=80)
    row = _make_deduction_row(row_id=31, quantity=20, returned=5)
    db = _LedgerSession(
        product=product, order=_make_order(), stockouts=[row],
        returns=[_make_return(return_id=2, stockout_id=31, status='cancelled')],
    )

    await _decrease_deduction(db, db.order, 1, 15)

    assert db.deleted == [row]
    assert db.returns[0].stockout_id is None     # 已解除关联，退货行保留


async def test_empty_deduction_decrease_raises_with_full_shortfall():
    """完全没有抵扣记录时请求减少 1 件 → 报错而不是静默通过。"""
    product = _make_product(stock=100)
    db = _LedgerSession(product=product, order=_make_order())

    with pytest.raises(ValueError, match='现有抵扣量不足，还需1件无法减少'):
        await _decrease_deduction(db, db.order, 1, 1)

    assert db.deleted == [] and db.logs == [] and product.current_stock == 100


# ---------------------------------------------------------------------------
# 单元：返回值语义 = 实际生效量（acceptance 2）
# ---------------------------------------------------------------------------
async def test_no_change_path_reports_current_actual_without_flush():
    """new == current 早退：回报实际当前量，且不触发 flush / commit。"""
    product = _make_product(stock=100)
    db = _LedgerSession(product=product, order=_make_order())

    with _stubbed_side_effects():
        result = await update_deduct_quantity(db, 1, 0, _USER)

    assert result == {'success': True, 'message': '抵扣数量未变化', 'deduct_quantity': 0}
    assert db.timeline == ['aggregate:order']
    assert db.committed == 0


async def test_success_returns_actual_effective_quantity_and_flushes_before_recount():
    """增加抵扣：返回值等于 flush 后重新聚合出的实际量（不是照抄请求量）。"""
    product = _make_product(stock=100)
    db = _LedgerSession(product=product, order=_make_order(), stockins=[_make_stockin(quantity=30)])

    with _stubbed_side_effects() as stub:
        result = await update_deduct_quantity(db, 1, 20, _USER)

    assert result == {'success': True, 'message': '抵扣数量修改成功', 'deduct_quantity': 20}
    assert [r.quantity for r in db.rows] == [20]
    assert db.rows[0].order_id == 1 and db.rows[0].stockin_id == 11
    assert db.rows[0].stockout_no == stub.numbers[0]
    assert sum(r.quantity for r in db.rows) == result['deduct_quantity']
    assert product.current_stock == 80 and product.version == 1
    assert [log.change_quantity for log in db.logs] == [-20]
    # 先 flush 再聚合：重算（第 2 次 aggregate:order）必须晚于 flush
    assert _nth_index(db.timeline, 'aggregate:order', 1) < db.timeline.index('flush')
    assert db.timeline.index('flush') < _nth_index(db.timeline, 'aggregate:order', 2)
    assert db.committed == 0 and db.rolled_back == 0


async def test_decrease_success_reports_actual_and_leaves_consistent_row():
    """减少抵扣：部分减少后返回值 = 5（实际量），行被改写而不是留半成品。"""
    product = _make_product(stock=80)
    row = _make_deduction_row(row_id=31, quantity=20)
    db = _LedgerSession(product=product, order=_make_order(), stockouts=[row])

    with _stubbed_side_effects():
        result = await update_deduct_quantity(db, 1, 5, _USER)

    assert result == {'success': True, 'message': '抵扣数量修改成功', 'deduct_quantity': 5}
    assert [r.quantity for r in db.rows] == [5]
    assert db.deleted == []
    assert product.current_stock == 95
    assert [log.change_quantity for log in db.logs] == [15]
    assert db.committed == 0 and db.rolled_back == 0


async def test_partial_effect_never_returns_success():
    """兜底：flush 后重算小于请求量时只能报错，绝不返回 success=True。"""
    product = _make_product(stock=100)
    db = _LedgerSession(product=product, order=_make_order(), stockins=[_make_stockin(quantity=30)])
    seq = [{1: 0}, {1: 15}]

    with _stubbed_side_effects(), patch(
        'fastapi_app.services.order.deduction._batch_deduct_quantities',
        new=AsyncMock(side_effect=lambda _db, _ids: seq.pop(0)),
    ):
        with pytest.raises(ValueError, match='抵扣数量未能完全生效：请求20件，实际生效15件'):
            await update_deduct_quantity(db, 1, 20, _USER)

    assert seq == []
    assert db.committed == 0 and db.rolled_back == 0


# ---------------------------------------------------------------------------
# 集成：真实事务边界（acceptance 4 的「不留半成品」反证）
# F-06（t43 修复）：URL 推导幂等 —— settings 已是测试库时原样复用，不再追加 _test；
# 且只有「建连探测」阶段的连接类异常才转 skip，DDL / schema 错误必须照常冒泡。
# ---------------------------------------------------------------------------
def _create_table(sync_conn, table) -> None:
    table.create(sync_conn, checkfirst=True)


def _is_test_db_url(raw_url: str) -> bool:
    """URL 的库名是否已经是测试库（以 _test 结尾）。"""
    return urlparse(raw_url).path.lstrip('/').endswith('_test')


def _test_db_url() -> str:
    """测试库 URL；幂等：已是测试库时原样复用，绝不二次追加 _test。"""
    override = os.getenv('TEST_DATABASE_URL')
    if override:
        return override
    from fastapi_app.core.config import settings

    current = settings.ASYNC_DATABASE_URL
    if _is_test_db_url(current):
        # tests/conftest.py 的会话级 autouse fixture 会把全局单例
        # settings.ASYNC_DATABASE_URL 改写成测试库（进程级副作用，不随 fixture 作用域
        # 隔离）。此时必须原样复用：再做一次库名替换会拼出不存在的 erp_system_test_test，
        # 连接失败又逃过原 except 分支，最终被记成 setup ERROR。
        return current
    db_name = os.getenv('DB_NAME', 'erp_system')
    parsed = urlparse(current)
    new_path = parsed.path.replace('/' + db_name, '/' + db_name + '_test', 1)
    return urlunparse(parsed._replace(path=new_path))


def _connection_error_types() -> tuple:
    """建连探测专用的连接类异常集合（DDL / schema / 断言错误不在其中，必须冒泡）。

    asyncpg 的 ConnectionDoesNotExistError 是 PostgresConnectionError 的子类，且不继承
    SQLAlchemyError，必须显式纳入，否则「库不可达」会被 pytest 记成 setup ERROR 而非 skip。
    """
    types: list[type[BaseException]] = [OSError, ConnectionError, InterfaceError, OperationalError]
    try:
        import asyncpg
    except ImportError:  # pragma: no cover - asyncpg 是运行时依赖，缺失时退化为内建集合
        return tuple(types)
    types += [asyncpg.PostgresConnectionError, asyncpg.InterfaceError]
    return tuple(types)


_CONNECTION_ERROR_TYPES = _connection_error_types()


async def _clear_rows(engine) -> None:
    statements = (
        'DELETE FROM stock_out WHERE product_id = :pid',
        'DELETE FROM inventory_log WHERE product_id = :pid',
        'DELETE FROM stock_in WHERE product_id = :pid',
        'DELETE FROM "order" WHERE product_id = :pid',
        'DELETE FROM product WHERE id = :pid',
    )
    async with engine.begin() as conn:
        for sql in statements:
            await conn.execute(text(sql), {'pid': _DB_PRODUCT_ID})


async def _count(session, sql, params=None):
    result = await session.execute(text(sql), params or {})
    return result.scalar()


@pytest_asyncio.fixture
async def deduct_engine():
    """真实测试库引擎；仅「库不可达」转 skip，DDL / schema 错误照常冒泡。"""
    db_url = _test_db_url()
    engine = create_async_engine(db_url, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
    except _CONNECTION_ERROR_TYPES as exc:
        await engine.dispose()
        pytest.skip(f'测试库不可达，跳过 P1-8 真实事务反证：{db_url}（{type(exc).__name__}: {exc}）')
    # 建表在探测之后、且不在上面的 skip 分支内：DDL / schema 错误必须暴露为失败。
    async with engine.begin() as conn:
        for table in (
            Product.__table__,
            Order.__table__,
            StockIn.__table__,
            StockOut.__table__,
            InventoryLog.__table__,
        ):
            await conn.run_sync(_create_table, table)
    await _clear_rows(engine)
    try:
        yield engine
    finally:
        try:
            await _clear_rows(engine)
        finally:
            await engine.dispose()


async def _seed_order(engine) -> int:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(Product(
            id=_DB_PRODUCT_ID, name=_DB_PREFIX + '产品', factory='测试工厂',
            initial_stock=_DB_PRODUCT_STOCK, current_stock=_DB_PRODUCT_STOCK, version=0,
        ))
        await session.flush()
        session.add(StockIn(
            stockin_no=_DB_PREFIX + 'BH', customer=_DB_PREFIX + '客户',
            product_id=_DB_PRODUCT_ID, quantity=_DB_STOCKIN_QTY,
        ))
        order = Order(
            order_no=_DB_PREFIX + 'O', customer=_DB_PREFIX + '客户',
            product_id=_DB_PRODUCT_ID, quantity=100, status='待备货', is_deleted=False,
        )
        session.add(order)
        await session.commit()
        return order.id


@pytest.mark.integration
@pytest.mark.db
async def test_real_db_failed_deduction_leaves_no_partial_writes(deduct_engine):
    """抵扣不足报错后：会话内零待写对象、DB 零残留（StockOut / InventoryLog / 库存）。"""
    order_id = await _seed_order(deduct_engine)

    async with AsyncSession(deduct_engine, expire_on_commit=False) as session:
        with _stubbed_side_effects() as stub, pytest.raises(ValueError, match='可用备货不足，还需70件无法抵扣'):
            await update_deduct_quantity(session, order_id, 100, _USER)
        assert stub.numbers == []
        assert list(session.new) == []  # 没有一条待插入的 StockOut / InventoryLog
        assert not session.dirty  # 也没有被改脏的实体（库存未被触碰）
        assert await _count(
            session, 'SELECT count(*) FROM stock_out WHERE order_id = :oid', {'oid': order_id}
        ) == 0
        await session.rollback()  # 与端点 db_transaction 的失败分支一致

    async with deduct_engine.connect() as conn:
        assert await _count(
            conn, 'SELECT count(*) FROM stock_out WHERE order_id = :oid', {'oid': order_id}
        ) == 0
        assert await _count(
            conn, 'SELECT count(*) FROM inventory_log WHERE product_id = :pid', {'pid': _DB_PRODUCT_ID}
        ) == 0
        row = (await conn.execute(
            text('SELECT current_stock, version FROM product WHERE id = :pid'), {'pid': _DB_PRODUCT_ID}
        )).one()
    assert row.current_stock == _DB_PRODUCT_STOCK
    assert row.version == 0


@pytest.mark.integration
@pytest.mark.db
async def test_real_db_success_reports_actual_and_round_trips(deduct_engine):
    """增加 / 减少抵扣各一次：返回值与库内聚合一致，且减少后库内零抵扣行、库存复原。"""
    order_id = await _seed_order(deduct_engine)

    async with AsyncSession(deduct_engine, expire_on_commit=False) as session:
        with _stubbed_side_effects():
            first = await update_deduct_quantity(session, order_id, 20, _USER)
            mid = await _count(
                session,
                'SELECT coalesce(sum(quantity - returned_quantity), 0) FROM stock_out'
                ' WHERE order_id = :oid AND stockin_id IS NOT NULL',
                {'oid': order_id},
            )
            assert mid == 20 == first['deduct_quantity']
            second = await update_deduct_quantity(session, order_id, 0, _USER)
        await session.commit()

    assert first == {'success': True, 'message': '抵扣数量修改成功', 'deduct_quantity': 20}
    assert second == {'success': True, 'message': '抵扣数量修改成功', 'deduct_quantity': 0}

    async with deduct_engine.connect() as conn:
        assert await _count(
            conn, 'SELECT count(*) FROM stock_out WHERE order_id = :oid', {'oid': order_id}
        ) == 0
        assert await _count(
            conn, 'SELECT current_stock FROM product WHERE id = :pid', {'pid': _DB_PRODUCT_ID}
        ) == _DB_PRODUCT_STOCK
