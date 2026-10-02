"""订单号统一后的种子算法与口径测试（spec §6.2/§6.4）。

seed（当日已落库最大序号）必须按**编号自身的日期段 + 数值排序**读取：
- 日期段取自编号字面量（split_part 第 2 段），与日期列的时区口径解耦；
- 序号段按数值取 max（字符串降序会把 10000 排在 9999 之前）；
- 正则守卫保证进入 cast 的序号段必为数字，脏行不抛 invalid input syntax。

自包含 fixture（函数级引擎）：与本仓带真库的编号测试
``tests/test_numbering_sequence_integration.py`` 同一模式——不复用 root
conftest 的 session 级引擎（pytest-asyncio 1.x 下有 ScopeMismatch）。
"""
import os
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.services.numbering_sequence import read_daily_max
from fastapi_app.shared_models import Base, Case, CaseMovement, Order

pytestmark = pytest.mark.integration


def _test_db_url() -> str:
    override = os.getenv('TEST_DATABASE_URL')
    if override:
        return override
    from fastapi_app.core.config import settings
    db_name = os.getenv('DB_NAME', 'erp_system')
    parsed = urlparse(settings.ASYNC_DATABASE_URL)
    # 幂等：conftest 的 session 级 app_on_test_db 已把 settings.ASYNC_DATABASE_URL
    # 重定向到 erp_system_test，此处再替换会生成不存在的 erp_system_test_test
    if parsed.path.rstrip('/').endswith('_test'):
        return settings.ASYNC_DATABASE_URL
    new_path = parsed.path.replace(f'/{db_name}', f'/{db_name}_test', 1)
    return urlunparse(parsed._replace(path=new_path))


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
async def test_read_daily_max_numeric_order_beats_lexicographic(db):
    # 同日 9999 与 10000 并存：字符串降序取 '9999'，数值 max 必须取 10000
    db.add_all([
        Order(order_no='PO-20260929-9999', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
        Order(order_no='PO-20260929-10000', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
    ])
    await db.flush()
    assert await read_daily_max(db, Order, 'order_no', '20260929') == 10000


@pytest.mark.asyncio
async def test_read_daily_max_filters_by_number_date_segment(db):
    # 种子只看编号自身的日期段，与日期列的时区口径无关
    db.add_all([
        Order(order_no='PO-20260929-0001', customer='c', quantity=1,
              order_date=datetime(2026, 9, 28, 20, 0, tzinfo=UTC)),  # 北京 09-29 凌晨
        Order(order_no='PO-20260928-0005', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, 5, 0, tzinfo=UTC)),  # 北京 09-29 下午
    ])
    await db.flush()
    assert await read_daily_max(db, Order, 'order_no', '20260929') == 1
    assert await read_daily_max(db, Order, 'order_no', '20260928') == 5


@pytest.mark.asyncio
async def test_read_daily_max_three_char_prefix_cso(db):
    # 三位前缀 CSO：split_part 不受前缀长度影响（substring 按位截取会错位）
    case = Case(name='测试皮套')
    db.add(case)
    await db.flush()
    db.add(CaseMovement(case_id=case.id, direction='out', movement_no='CSO-20260929-0007',
                        quantity=1, movement_date=datetime(2026, 9, 29, tzinfo=UTC)))
    await db.flush()
    assert await read_daily_max(db, CaseMovement, 'movement_no', '20260929') == 7


@pytest.mark.asyncio
async def test_read_daily_max_malformed_rows_are_guards_not_crashes(db):
    # 脏行（序号段非数字）必须被正则守卫过滤，cast 不抛 invalid input syntax
    db.add_all([
        Order(order_no='PO-20260929-0002', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
        Order(order_no='PO-20260929-XX', customer='c', quantity=1,
              order_date=datetime(2026, 9, 29, tzinfo=UTC)),
    ])
    await db.flush()
    assert await read_daily_max(db, Order, 'order_no', '20260929') == 2


@pytest.mark.asyncio
async def test_read_daily_max_empty_returns_zero(db):
    assert await read_daily_max(db, Order, 'order_no', '20991231') == 0


@pytest.mark.asyncio
async def test_business_date_str_beijing_boundary(monkeypatch):
    # UTC 16:30 = 北京 00:30（次日）——冻结时钟验证口径
    from datetime import datetime as _dt

    import fastapi_app.services.numbering_sequence as ns

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            base = _dt(2026, 9, 29, 16, 30, tzinfo=UTC)
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)

    monkeypatch.setattr(ns, 'datetime', _Frozen)
    assert ns.business_date_str() == '20260930'  # 北京已过午夜


@pytest.mark.asyncio
async def test_generated_number_uses_beijing_date_segment(db, monkeypatch):
    from unittest import mock

    from fastapi_app.services import numbering

    async def _no_seed(db_, model, field, date_str):
        return 0

    monkeypatch.setattr(numbering, 'read_daily_max', _no_seed)
    monkeypatch.setattr(numbering, 'allocate_sequence', mock.AsyncMock(return_value=1))
    number = await numbering.generate_number_async('PO', Order, 'order_no', db)
    assert number.startswith('PO-2026') and number.endswith('-0001')
