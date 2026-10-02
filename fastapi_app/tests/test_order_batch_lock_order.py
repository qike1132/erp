"""P1-5 批量创建锁顺序：Product 行锁按 id 升序获取，锁范围收窄到本组商品。

修复背景
--------
order_batch_create.batch_create_orders 原实现在进入第一个 customer 分组的 savepoint
时，把整批订单引用的 Product 一次性 select(...).with_for_update() 加锁，且 SQL 不带
ORDER BY：IN 列表按传入顺序渲染，多行行锁的实际获取顺序取决于商品顺序与执行计划；
该锁集合又被 product_map 缓存贯穿整个批量循环（失败分组回滚会释放其行锁，后续分组
却因缓存命中而跳过加锁）。商品集合重叠的两个并发批量因此可能以不同顺序取行锁，
形成交叉死锁。

修复
----
1) 显式 ORDER BY product.id，IN 列表同样升序（sorted），并发批量按同一顺序取行锁；
2) 加锁范围收窄为「当前 customer 分组实际引用的商品」，且只有组内 savepoint 正常
   退出后才计入 locked_ids（回滚分组释放的行锁不污染后续分组的加锁判定）。
   锁粒度不变：仍是 Product 行级 FOR UPDATE（非表锁、非 NOWAIT/SKIP LOCKED）。

测试边界
--------
单元部分用录制式 mock 会话（承接 test_order_batch_create.py 的 _NestedCM / _make_db
范式）捕获 batch_create_orders 下发的语句，按 PostgreSQL 方言编译成字面量 SQL 后
断言形状；集成部分连测试库（与 tests/test_numbering_sequence_integration.py 同款
前提），用真实 asyncpg 下发的 SQL 与行级锁行为做反证，只使用 JANITOR-LOCK-* 数据
并在前后清理。
"""
import os
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy import Select, event, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from fastapi_app.services.order_batch_create import _lock_products, batch_create_orders
from fastapi_app.shared_models import Product

#: 真实 SQL / 行锁反证使用的固定商品 id 段（JANITOR-LOCK-* 前缀，用例前后清理）
_LOCK_IDS = (9101, 9102, 9103, 9104)
_LOCK_NAME_PREFIX = 'JANITOR-LOCK-'


def _make_product(pid):
    product = MagicMock()
    product.id = pid
    product.name = f'产品{pid}'
    product.barcode = f'BC{pid}'
    product.factory = '测试工厂'
    return product


def _make_order_data(product_id, customer='客户A', quantity=5):
    return {
        'product_id': product_id,
        'customer': customer,
        'quantity': quantity,
        'deduct_stock': False,
        'deduct_quantity': 0,
        'order_type': 'regular',
        'note': '',
    }


class _NestedCM:
    """模拟 db.begin_nested() 返回的 savepoint 上下文，记录是否回滚。"""

    def __init__(self):
        self.rolled_back = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if exc is not None:
            self.rolled_back = True
        return False


def _make_recording_db(products):
    """构造录制式 mock AsyncSession：记录所有 execute 下发的语句。"""
    db = AsyncMock()
    db.add = MagicMock()
    statements: list = []
    counter = {'n': 0}

    async def _flush(*args, **kwargs):
        for call in reversed(db.add.call_args_list):
            obj = call.args[0]
            if getattr(obj, 'id', None) is None:
                counter['n'] += 1
                obj.id = counter['n']
                return

    db.flush = AsyncMock(side_effect=_flush)

    result = MagicMock()
    result.scalars.return_value.all.return_value = list(products)
    result.scalar_one_or_none.return_value = None

    async def _execute(statement, *args, **kwargs):
        statements.append(statement)
        return result

    db.execute = AsyncMock(side_effect=_execute)

    nested_cms = []

    def _make_nested():
        cm = _NestedCM()
        nested_cms.append(cm)
        return cm

    db.begin_nested = MagicMock(side_effect=_make_nested)
    db._statements = statements
    db._nested_cms = nested_cms
    return db


def _lock_sql(db) -> list:
    """本批下发过的加锁语句（按发放顺序），已编译为 PostgreSQL 字面量 SQL。"""
    rendered = []
    for statement in db._statements:
        if not isinstance(statement, Select):
            continue
        if getattr(statement, '_for_update_arg', None) is None:
            continue
        rendered.append(
            str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={'literal_binds': True},
                )
            ).lower()
        )
    return rendered


@contextmanager
def _stubbed_side_effects():
    """把本模块的四个外部副作用替换为无害桩，保证单元用例不触达真实服务。"""
    with (
        patch(
            'fastapi_app.services.numbering.generate_order_number',
            new_callable=AsyncMock,
            return_value='PO-LOCK-0001',
        ),
        patch(
            'fastapi_app.services.order_batch_create.process_order_deduction',
            new_callable=AsyncMock,
        ),
        patch(
            'fastapi_app.services.order_batch_create.dispatch_factory_notifications',
            new_callable=AsyncMock,
        ),
        patch(
            'fastapi_app.services.order_batch_create.dispatch_beile_unconfirmed_notifications',
            new_callable=AsyncMock,
        ),
    ):
        yield


class TestLockStatementShape:
    """锁语句形状：显式 ORDER BY product.id + 升序 IN 列表 + 行级 FOR UPDATE。"""

    async def test_lock_sql_orders_by_product_id(self):
        products = [_make_product(10), _make_product(20), _make_product(30)]
        db = _make_recording_db(products)
        # 乱序入参：修复前编译出的 IN 列表与锁获取顺序都是 (30, 10, 20)
        orders_data = [
            _make_order_data(30, customer='客户A'),
            _make_order_data(10, customer='客户A'),
            _make_order_data(20, customer='客户A'),
        ]
        with _stubbed_side_effects():
            result = await batch_create_orders(db, orders_data)

        assert result['created_count'] == 1
        locks = _lock_sql(db)
        assert len(locks) == 1, locks
        lock_sql = locks[0]
        assert 'for update' in lock_sql, lock_sql
        assert 'order by product.id' in lock_sql, lock_sql
        assert lock_sql.index('order by product.id') < lock_sql.index('for update'), lock_sql
        # IN 列表升序：乱序输入 [30, 10, 20] 必须编译为 (10, 20, 30)
        assert 'in (10, 20, 30)' in lock_sql, lock_sql

    async def test_lock_is_row_level_for_update_not_table_lock(self):
        db = _make_recording_db([_make_product(1)])
        with _stubbed_side_effects():
            await batch_create_orders(db, [_make_order_data(1)])

        lock_sql = _lock_sql(db)[0]
        assert 'from product' in lock_sql, lock_sql
        assert 'for update' in lock_sql, lock_sql
        assert 'lock table' not in lock_sql, lock_sql
        assert 'nowait' not in lock_sql, lock_sql
        assert 'skip locked' not in lock_sql, lock_sql


class TestGlobalLockOrder:
    """整批一次性按 id 升序取锁（P1-5 修正）。

    曾经改成「逐分组各自加锁」以求缩小锁范围，但那会重新打开跨组死锁：分组顺序取决于
    请求里 customer 的首次出现顺序，T1 按 [A(p1), B(p2)]、T2 按 [B(p2), A(p1)] 处理时
    双方各持一把、互等对方。对分组排序也消除不了这种交叉（分组构成逐请求不同），
    只有单条语句按全局升序取锁，才能保证所有并发批次的取锁顺序一致。
    """

    async def test_single_lock_across_all_customer_groups(self):
        """多客户分组也只发一条加锁语句，且覆盖全部商品。"""
        products = [_make_product(1), _make_product(2), _make_product(3)]
        db = _make_recording_db(products)
        orders_data = [
            _make_order_data(1, customer='客户A'),
            _make_order_data(2, customer='客户B'),
            _make_order_data(3, customer='客户B'),
        ]
        with _stubbed_side_effects():
            result = await batch_create_orders(db, orders_data)

        assert result['created_count'] == 2
        locks = _lock_sql(db)
        assert len(locks) == 1, f'必须只有一条加锁语句，实际 {locks}'
        assert 'product.id in (1, 2, 3)' in locks[0], locks[0]
        assert 'order by product.id' in locks[0], locks[0]

    async def test_lock_order_is_ascending_regardless_of_input_order(self):
        """乱序输入必须编译成升序 IN 列表——这正是跨批次互斥的根据。"""
        products = [_make_product(1), _make_product(2)]
        db = _make_recording_db(products)
        orders_data = [
            _make_order_data(2, customer='客户A'),
            _make_order_data(1, customer='客户B'),
        ]
        with _stubbed_side_effects():
            await batch_create_orders(db, orders_data)

        locks = _lock_sql(db)
        assert len(locks) == 1, locks
        assert 'product.id in (1, 2)' in locks[0], locks[0]

    async def test_repeated_group_products_locked_once(self):
        products = [_make_product(1), _make_product(2)]
        db = _make_recording_db(products)
        orders_data = [
            _make_order_data(1, customer='客户A'),
            _make_order_data(2, customer='客户A'),
            _make_order_data(1, customer='客户B'),
            _make_order_data(2, customer='客户B'),
        ]
        with _stubbed_side_effects():
            result = await batch_create_orders(db, orders_data)

        assert result['created_count'] == 2
        locks = _lock_sql(db)
        assert len(locks) == 1, locks
        assert 'product.id in (1, 2)' in locks[0], locks[0]

    async def test_failed_group_keeps_upfront_lock(self):
        """前置加锁不在 savepoint 内：某组回滚不影响已取的锁，也不会对后续组重复加锁。"""
        products = [_make_product(2)]
        db = _make_recording_db(products)
        orders_data = [
            _make_order_data(999, customer='客户A'),  # 产品不存在 → 整组 savepoint 回滚
            _make_order_data(2, customer='客户B'),
        ]
        with _stubbed_side_effects():
            result = await batch_create_orders(db, orders_data)

        assert db._nested_cms[0].rolled_back is True
        assert result['results'][0]['success'] is False
        assert result['results'][1]['success'] is True
        locks = _lock_sql(db)
        assert len(locks) == 1, f'加锁只应发生一次（前置），实际 {locks}'
        assert 'product.id in (2, 999)' in locks[0], locks[0]


def _test_db_url() -> str:
    """测试库 URL：TEST_DATABASE_URL 优先，否则把主库名替换为 *_test（幂等）。"""
    override = os.getenv('TEST_DATABASE_URL')
    if override:
        return override
    from fastapi_app.core.config import settings

    db_name = os.getenv('DB_NAME', 'erp_system')
    parsed = urlparse(settings.ASYNC_DATABASE_URL)
    if parsed.path.rstrip('/').endswith('_test'):
        return settings.ASYNC_DATABASE_URL
    new_path = parsed.path.replace(f'/{db_name}', f'/{db_name}_test', 1)
    return urlunparse(parsed._replace(path=new_path))


async def _clear_lock_rows(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text('DELETE FROM product WHERE name LIKE :prefix'),
            {'prefix': _LOCK_NAME_PREFIX + '%'},
        )


async def _insert_lock_products(engine, ids) -> None:
    async with engine.begin() as conn:
        for pid in ids:
            await conn.execute(
                text(
                    'INSERT INTO product (id, name, initial_stock, current_stock) '
                    'VALUES (:pid, :name, 0, 0)'
                ),
                {'pid': pid, 'name': f'{_LOCK_NAME_PREFIX}{pid}'},
            )


@pytest_asyncio.fixture
async def lock_engine():
    """测试库引擎；product 表按需建（测试库可能只有部分表），数据只用 JANITOR-LOCK-*。"""
    engine = create_async_engine(_test_db_url(), echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Product.__table__.create(sync_conn, checkfirst=True))
    except (OSError, SQLAlchemyError) as exc:  # pragma: no cover - 环境前提不满足时跳过
        await engine.dispose()
        pytest.skip(f'测试库不可达，跳过 P1-5 真实 SQL / 行锁反证：{exc}')

    await _clear_lock_rows(engine)
    try:
        yield engine
    finally:
        try:
            await _clear_lock_rows(engine)
        finally:
            await engine.dispose()


@pytest.mark.integration
@pytest.mark.db
async def test_real_sql_orders_by_product_id_and_locks_ascending(lock_engine):
    """真实 asyncpg 下发的加锁 SQL 带 ORDER BY product.id，且加锁参数升序。"""
    await _insert_lock_products(lock_engine, (9103, 9101, 9102))

    captured: list = []

    def _listener(conn, cursor, statement, parameters, context, executemany):
        if 'for update' in statement.lower():
            captured.append((statement, parameters))

    event.listen(lock_engine.sync_engine, 'before_cursor_execute', _listener)
    try:
        async with AsyncSession(lock_engine, expire_on_commit=False) as session:
            locked = await _lock_products(session, [9103, 9101, 9102])
            await session.rollback()
    finally:
        event.remove(lock_engine.sync_engine, 'before_cursor_execute', _listener)

    assert sorted(locked) == [9101, 9102, 9103], sorted(locked)
    assert len(captured) == 1, captured
    statement, parameters = captured[0]
    lowered = statement.lower()
    assert 'for update' in lowered, statement
    assert 'order by product.id' in lowered, statement
    assert lowered.index('order by product.id') < lowered.index('for update'), statement
    # 修复前实测为 (9103, 9101, 9102)：参数顺序即加锁顺序
    assert list(parameters) == [9101, 9102, 9103], parameters


@pytest.mark.integration
@pytest.mark.db
async def test_lock_is_row_level_other_rows_stay_lockable(lock_engine):
    """持锁期间被锁行 NOWAIT 失败、未锁行 NOWAIT 成功 —— 证明仍是行级锁。"""
    await _insert_lock_products(lock_engine, _LOCK_IDS)

    holder = AsyncSession(lock_engine, expire_on_commit=False)
    other = AsyncSession(lock_engine, expire_on_commit=False)
    try:
        locked = await _lock_products(holder, [9101, 9102, 9103])
        assert sorted(locked) == [9101, 9102, 9103], sorted(locked)

        # 未被持锁事务锁定的行：NOWAIT 立即成功（若为表锁会立即失败）
        free_row = await other.execute(
            select(Product).where(Product.id == 9104).with_for_update(nowait=True)
        )
        assert [row.id for row in free_row.scalars().all()] == [9104]
        await other.rollback()

        # 已被持锁事务锁定的行：NOWAIT 立即报锁不可得
        with pytest.raises(SQLAlchemyError) as excinfo:
            await other.execute(
                select(Product).where(Product.id == 9103).with_for_update(nowait=True)
            )
        await other.rollback()
        orig = getattr(excinfo.value, 'orig', None)
        assert 'locknotavailable' in type(orig).__name__.lower() or 'lock' in str(excinfo.value).lower()
    finally:
        await holder.rollback()
        await other.close()
        await holder.close()
