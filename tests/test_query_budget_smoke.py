"""AUD-13（2026-10-24 审计 P1）回归锁：核心列表查询的语句数预算冒烟。

Flask 时代的 performance 套件随被测目标删除而整体 skip（且被 CI --ignore
双重排除），性能回归实际零防护——任何 N+1/查询爆炸引入都不会被测试发现。
本文件用「单次调用的 SQL 语句数上限」做冒烟预算：语句数是确定性的（不受
机器速度/CI 噪声影响，比时间断言稳），能拦住最常见的性能退化形态
（循环内逐行查询的 N+1、意外缺失的批量取数）。

预算值 = 当前实现实测基线 + 少量余量（允许实现小改），大幅回退即红。
"""

import pytest
import pytest_asyncio
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration

CUSTOMER = '预算冒烟客户'
BARCODE_PREFIX = 'BUDGET-'


@pytest_asyncio.fixture
async def db(test_engine):
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
    )
    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def seeded_products(db):
    """造 5 个产品 × 各 1 条订单行，让列表查询有东西可查。"""
    from datetime import UTC, datetime

    from fastapi_app.shared_models import DailyProductionRecord, Order, Product

    products = []
    for i in range(5):
        product = Product(name=f'{CUSTOMER}产品{i}', barcode=f'{BARCODE_PREFIX}{i}',
                          current_stock=0, initial_stock=0)
        db.add(product)
        products.append(product)
    await db.flush()
    db.add(DailyProductionRecord(
        department='packaging', product_id=products[0].id,
        product_name=products[0].name, barcode=products[0].barcode,
        quantity=100, production_date=datetime.now(UTC).date(),
    ))
    db.add(Order(
        order_no='BUDGET-ORD-1', customer=CUSTOMER, product_id=products[0].id,
        quantity=50, order_date=datetime.now(UTC), status='待备货',
    ))
    await db.flush()
    return products


class _StatementCounter:
    """统计会话上真实下发的 SELECT 语句数（区分 flush 产生的写语句）。"""

    def __init__(self, session):
        self.selects = 0
        self._engine = session.sync_session.bind  # sync Engine（非 AsyncEngine 包装）

        def _after_cursor_execute(conn, cursor, statement, parameters, *args):
            if statement.lstrip().upper().startswith('SELECT'):
                self.selects += 1

        # 闭包存成属性：__exit__ 要按同一对象摘监听器（event.remove 按函数身份匹配）
        self._handler = _after_cursor_execute

    def __enter__(self):
        # 监听必须在 with 入口注册、出口摘掉。4.5（2026-10-17 审计 P2）：原实现在
        # __init__ 注册且**从不反注册**，而 self._engine 是会话级引擎（跨用例存活）——
        # 之后每个用例的 SELECT 都会累加进这个已废弃的计数器；同一用例里若出现两个
        # 计数器，两个实例都会被重复累加，断言（selects <= N）随之失真。
        event.listen(self._engine, 'after_cursor_execute', self._handler)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, 'after_cursor_execute', self._handler)
        return False


async def test_inventory_page_query_statement_budget(db, seeded_products):
    """/stock 库存分页：单次分页查询的 SELECT 数不得随产品数线性膨胀（N+1 防线）。"""
    from fastapi_app.services import stock_inventory_service as svc

    counter = _StatementCounter(db)
    with counter:
        result = await svc.get_inventory_paginated.__wrapped__(
            db, search_customer=CUSTOMER, page=1, per_page=50,
        )
    rows = [r for r in result['inventory_data'] if r['customer'] == CUSTOMER]
    assert rows, '夹具必须至少命中一行'
    # 当前实现为单一 CTE 查询 + 计数查询（实测基线 ~2）；放行到 6，
    # 回退成每产品一查（5 产品 = 7+ 语句）即红。
    assert counter.selects <= 6, (
        f'库存分页 SELECT 数 {counter.selects} 超预算（N+1 回归？）'
    )


async def test_inventory_page_time_budget(db, seeded_products):
    """灾难级时间预算：测试库小数据集下 5s 内必须完成（当前实现 <0.5s）。"""
    import time

    from fastapi_app.services import stock_inventory_service as svc

    start = time.monotonic()
    await svc.get_inventory_paginated.__wrapped__(
        db, search_customer=CUSTOMER, page=1, per_page=50,
    )
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, f'库存分页耗时 {elapsed:.2f}s——疑似灾难级性能回归（AUD-13）'


@pytest.mark.asyncio
async def test_statement_counter_stops_counting_after_with(db):
    """4.5 回归锁：with 块结束后监听器必须摘掉。

    原实现只在 ``__init__`` 里 ``event.listen``、从不 ``event.remove``，而 ``self._engine``
    是**会话级**引擎（跨用例存活）—— 之后每个用例的 SELECT 都会继续累加进这个已废弃的
    计数器；同一用例里出现两个计数器时两个实例都会被重复累加，``selects <= N`` 的预算
    断言随之失真。
    """
    counter = _StatementCounter(db)
    with counter:
        await db.execute(text('SELECT 1'))
    counted = counter.selects
    assert counted >= 1, 'with 块内必须真的计到语句（否则本用例什么都没验证）'

    await db.execute(text('SELECT 1'))
    assert counter.selects == counted, (
        f'with 结束后监听器仍挂在引擎上：计数从 {counted} 涨到 {counter.selects}'
    )
