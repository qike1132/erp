"""编号巡检：counter_behind 只对反向偏差报警，正向跳号不报（spec §4.5）。

自包含 fixture（函数级引擎 + 事务回滚）：与 test_numbering_sequence_integration
同款，不依赖 root conftest 的 session 级 test_engine（避免 ScopeMismatch），
并 monkeypatch _AsyncSessionLocal 指向测试库引擎，全程不触碰生产库。

日期口径：compute_audit 按 business_date_str()（北京今天）过滤当日编号段。
测试把该函数钉死为固定日期，数据与过滤同源——任何墙钟日期运行都成立，
不会在北京日历跨日后塌成 data_max=0。
"""
import os
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.shared_models import Base, NumberingAudit, NumberingCounter, Order
from fastapi_app.tasks import numbering_audit_task as audit_task_module
from fastapi_app.tasks.numbering_audit_task import compute_audit

# 巡检"今天"：测试数据与 compute_audit 的当日过滤共用此常量（经 monkeypatch 注入）。
_TODAY = '20260929'


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


@pytest.fixture(autouse=True)
def _pin_business_date(monkeypatch):
    """把 compute_audit 的"今天"钉死，移除墙钟依赖（跨北京午夜也不漂）。"""
    monkeypatch.setattr(audit_task_module, 'business_date_str', lambda: _TODAY)


@pytest_asyncio.fixture
async def db(monkeypatch):
    """函数级：测试库建表 + 事务回滚会话（compute_audit 不 commit，回滚隔离）。"""
    from fastapi_app.core import database as core_db

    engine = create_async_engine(_test_db_url(), echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(core_db, '_AsyncSessionLocal', factory)

    async with factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_behind_reported(db):
    # 数据 max=7 > 水位 3 → behind
    db.add_all([
        Order(order_no=f'PO-{_TODAY}-0007', customer='c', quantity=1,
              order_date=datetime.now(UTC)),
        NumberingCounter(prefix='PO', number_date=_TODAY, last_seq=3),
    ])
    await db.flush()
    report = await compute_audit(db)
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['counter_behind'] is True


@pytest.mark.asyncio
async def test_ahead_is_not_reported(db):
    # 水位 45 > 数据 max=1（跳号/删除正常态）→ 不报
    db.add_all([
        Order(order_no=f'PO-{_TODAY}-0001', customer='c', quantity=1,
              order_date=datetime.now(UTC)),
        NumberingCounter(prefix='PO', number_date=_TODAY, last_seq=45),
    ])
    await db.flush()
    report = await compute_audit(db)
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['counter_behind'] is False


@pytest.mark.asyncio
async def test_format_violation_reported(db):
    db.add(Order(order_no='PO-PENDING-42', customer='c', quantity=1,
                 order_date=datetime.now(UTC)))
    await db.flush()
    report = await compute_audit(db)
    assert any(v['table'] == 'order' for v in report['violations'])


@pytest.mark.asyncio
async def test_missing_counter_row_is_not_behind(db):
    """缺水位行（首用前）不算 behind —— 只有数据 > 已有水位才报警。"""
    db.add(Order(order_no=f'PO-{_TODAY}-0009', customer='c', quantity=1,
                 order_date=datetime.now(UTC)))
    await db.flush()
    report = await compute_audit(db)
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['counter_behind'] is False


@pytest.mark.asyncio
async def test_clean_data_has_no_violations(db):
    """合规编号：无格式违规、无 behind。"""
    db.add_all([
        Order(order_no=f'PO-{_TODAY}-0003', customer='c', quantity=1,
              order_date=datetime.now(UTC)),
        NumberingCounter(prefix='PO', number_date=_TODAY, last_seq=3),
    ])
    await db.flush()
    report = await compute_audit(db)
    assert report['violations'] == []
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['counter_behind'] is False


def test_numbering_audit_model_shape():
    """ORM 表/列契约：表名、主键、列集（迁移必须逐列对齐）。"""
    assert NumberingAudit.__tablename__ == 'numbering_audit'
    cols = {c.name for c in NumberingAudit.__table__.columns}
    assert cols == {'id', 'scope', 'counter_behind', 'detail', 'checked_at'}
    assert NumberingAudit.__table__.primary_key.columns.keys() == ['id']
