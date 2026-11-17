"""启动对账：GREATEST 只升不降、补插缺行、幂等（spec §5）。

自包含 fixture（函数级引擎）：与 ``tests/test_numbering_sequence_integration.py``
同一模式——事务回滚隔离，全程不触碰生产库（monkeypatch 把 _AsyncSessionLocal
指向测试引擎）。``reconcile_numbering_counters`` 写入调用方会话、不自行 commit，
故用例结束的 rollback 即可完全回滚其 INSERT/UPDATE，无跨用例残留。
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.services.numbering_reconcile import reconcile_numbering_counters
from fastapi_app.services.numbering_sequence import business_period_str
from fastapi_app.shared_models import Base, NumberingCounter, Order

pytestmark = pytest.mark.integration


def _test_db_url() -> str:
    """测试库 URL（单点收敛，2026-11-16 上线前审计 H-6）。

    原实现自建派生链且没有 `*_test` 硬闸；替换串还少了前导 `/`（靠 `urlunparse`
    自动补回，属侥幸正确）→ 一并收敛到单点入口。
    """
    from fastapi_app.tests._test_db_guard import resolve_test_db_url

    return resolve_test_db_url()


@pytest_asyncio.fixture
async def db_and_factory(monkeypatch):
    """函数级：测试库建表 + 事务回滚会话；同时把 _AsyncSessionLocal 指向测试引擎。

    monkeypatch 在 fixture 结束时自动还原，生产配置不受影响。
    """
    from fastapi_app.core import database as core_db

    engine = create_async_engine(_test_db_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(core_db, '_AsyncSessionLocal', factory)

    async with factory() as session:
        async with session.begin() as transaction:
            yield session, factory
            await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_and_factory):
    """只取会话部分，贴合本文件用例的 ``db`` 参数。"""
    session, _factory = db_and_factory
    yield session


@pytest.mark.asyncio
async def test_reconcile_raises_watermark_and_inserts_missing(db):
    db.add(Order(order_no='PO-20260929-0007', customer='c', quantity=1,
                 order_date=datetime(2026, 9, 29, tzinfo=UTC)))
    await db.flush()

    result = await reconcile_numbering_counters(db)

    row = (await db.execute(
        select(NumberingCounter).where(
            NumberingCounter.prefix == 'PO', NumberingCounter.number_date == '20260929'))).scalar_one()
    assert row.last_seq >= 7          # GREATEST 只升不降
    assert result['raised'] >= 1 or result['inserted'] >= 1


@pytest.mark.asyncio
async def test_reconcile_never_lowers_watermark(db):
    db.add(NumberingCounter(prefix='PO', number_date='20260929', last_seq=99))
    await db.flush()
    await reconcile_numbering_counters(db)
    row = (await db.execute(
        select(NumberingCounter).where(
            NumberingCounter.prefix == 'PO', NumberingCounter.number_date == '20260929'))).scalar_one()
    assert row.last_seq == 99         # 数据 max=0 也不降


@pytest.mark.asyncio
async def test_reconcile_is_idempotent(db):
    db.add(Order(order_no='PO-20260929-0007', customer='c', quantity=1,
                 order_date=datetime(2026, 9, 29, tzinfo=UTC)))
    await db.flush()
    first = await reconcile_numbering_counters(db)
    assert first['raised'] >= 1 or first['inserted'] >= 1   # 首轮确有对账动作
    second = await reconcile_numbering_counters(db)
    assert second['raised'] == 0 and second['inserted'] == 0   # 第二次无变化


@pytest.mark.asyncio
async def test_reconcile_raises_when_counter_behind_data(db):
    """真实"抬升"分支：水位落后于数据 max 时对账必须把水位抬到数据 max。

    这正是关闭部署窗口的那一步 —— 数据行由历史路径（旧 core/batch 取号）产出、
    从不写 ``numbering_counter``，水位行落后；对账须把水位抬到数据 max，否则
    后续 ``allocate_sequence`` 返回 ``last_seq+1`` 会与既有数据重号。

    日期段取自 ``business_period_str()``（与编号数据同源），不硬编码字面日期 ——
    与 ``tests/test_numbering_audit.py`` 同一纪律，任何墙钟日期运行都成立。
    """
    segment = business_period_str()
    db.add(NumberingCounter(prefix='PO', number_date=segment, last_seq=3))
    for seq in (5, 6, 7):  # 数据 max = 7 > 水位 3
        db.add(Order(order_no=f'PO-{segment}-{seq:04d}', customer='c', quantity=1,
                     order_date=datetime.now(UTC)))
    await db.flush()

    result = await reconcile_numbering_counters(db)

    assert result['raised'] == 1 and result['inserted'] == 0   # 只抬升既有水位、不补插
    row = (await db.execute(
        select(NumberingCounter).where(
            NumberingCounter.prefix == 'PO', NumberingCounter.number_date == segment))).scalar_one()
    assert row.last_seq == 7
