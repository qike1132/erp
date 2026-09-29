"""编号巡检：counter_behind 只对反向偏差报警，正向跳号不报（spec §4.5）。

自包含 fixture（函数级引擎 + 事务回滚）：与 test_numbering_sequence_integration
同款，不依赖 root conftest 的 session 级 test_engine（避免 ScopeMismatch），
并 monkeypatch _AsyncSessionLocal 指向测试库引擎，全程不触碰生产库。

日期口径：compute_audit 按 business_date_str()（北京今天）过滤当日编号段。测试
把该函数钉死为一个**其他用例与生产路径都不会产生的远期日期段** `_TODAY`，于是
date-scoped 扫描（data_max / counter）只命中本文件自己插入的行——这些断言因此
不受共享测试库中其他用例残留数据的影响。

违规计数则**按表全局**统计（10 个编号列扫全表），而 erp_system_test 由整个测试
会话共享，其他用例可能留下不合规编号行。故所有涉及 violations 的断言都不假设
"库内零违规"，而是核对**报告与独立直查结果双向一致**（逐实体复核，多报/漏报都抓）。
"""
import os
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi_app.services.numbering_reconcile import NUMBERED_ENTITIES
from fastapi_app.shared_models import Base, NumberingAudit, NumberingCounter, Order
from fastapi_app.tasks import numbering_audit_task as audit_task_module
from fastapi_app.tasks.numbering_audit_task import compute_audit

# 本文件专用的编号日期段：远期日期，其他用例/生产路径都不会产生该段的行，
# 从而把 date-scoped 扫描（data_max / counter）隔离到本文件的造数。
_TODAY = '29991231'

# 合规编号模式：与生产巡检同一口径，但在本文件内独立书写，用于直查复核。
_NUMBER_PATTERN = r'^[A-Z]+-[0-9]{8}-[0-9]+$'


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
    """把 compute_audit 的"今天"钉死为 _TODAY（远期唯一段），隔离共享测试库污染。"""
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


async def _direct_violation_count(db, table: str, column: str) -> int:
    """独立直查：该表该列不合规编号行数（不复用生产模块的同名 SQL 文本）。"""
    result = await db.execute(
        text(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" !~ :pat'),
        {'pat': _NUMBER_PATTERN},
    )
    return int(result.scalar() or 0)


def _violation_entry(report: dict, table: str, column: str) -> dict | None:
    """报告里 (table, column) 的违规条目，无则 None。"""
    return next((v for v in report['violations']
                 if v['table'] == table and v['column'] == column), None)


@pytest.mark.asyncio
async def test_behind_reported(db):
    # 数据 max=7 > 水位 3 → behind（日期段唯一，data_max 必为本文件的行）
    db.add_all([
        Order(order_no=f'PO-{_TODAY}-0007', customer='c', quantity=1,
              order_date=datetime.now(UTC)),
        NumberingCounter(prefix='PO', number_date=_TODAY, last_seq=3),
    ])
    await db.flush()
    report = await compute_audit(db)
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['data_max'] == 7
    assert po['counter'] == 3
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
    assert po['data_max'] == 1
    assert po['counter'] == 45
    assert po['counter_behind'] is False


@pytest.mark.asyncio
async def test_format_violation_reported(db):
    """不合规行被计入，且计数与独立直查精确一致。

    计数按表全局：库内可能还有别的用例残留的不合规行，故不假设"只有本行"，
    只断言报告值 == 直查值，且直查值 ≥ 本用例插入的 1 行。
    """
    db.add(Order(order_no='PO-PENDING-42', customer='c', quantity=1,
                 order_date=datetime.now(UTC)))
    await db.flush()
    report = await compute_audit(db)
    direct = await _direct_violation_count(db, 'order', 'order_no')
    entry = _violation_entry(report, 'order', 'order_no')
    assert entry is not None, 'order 表存在不合规行，报告却遗漏'
    assert entry['count'] == direct
    assert direct >= 1


@pytest.mark.asyncio
async def test_missing_counter_row_is_not_behind(db):
    """缺水位行（首用前）不算 behind —— 只有数据 > 已有水位才报警。"""
    db.add(Order(order_no=f'PO-{_TODAY}-0009', customer='c', quantity=1,
                 order_date=datetime.now(UTC)))
    await db.flush()
    report = await compute_audit(db)
    po = next(r for r in report['prefixes'] if r['prefix'] == 'PO')
    assert po['data_max'] == 9
    assert po['counter'] is None
    assert po['counter_behind'] is False


@pytest.mark.asyncio
async def test_violation_report_matches_direct_query(db):
    """报告与库内事实双向一致，不依赖库内是否只有本用例的数据。

    对 10 个编号实体逐一独立直查：直查 > 0 的表必须出现在报告且计数相等
    （无漏报 / 无错值），直查 = 0 的不该出现（无多报），报告也不得含实体外条目。
    """
    report = await compute_audit(db)
    reported = {(v['table'], v['column']): v['count'] for v in report['violations']}
    entity_cols = {(table, column) for _prefix, table, column in NUMBERED_ENTITIES}
    assert set(reported) <= entity_cols, f'报告含非实体条目: {set(reported) - entity_cols}'
    for _prefix, table, column in NUMBERED_ENTITIES:
        direct = await _direct_violation_count(db, table, column)
        if direct > 0:
            assert (table, column) in reported, f'{table}.{column} 有 {direct} 行不合规，报告遗漏'
            assert reported[(table, column)] == direct, f'{table}.{column} 计数不符'
        else:
            assert (table, column) not in reported, f'{table}.{column} 无不合规行，报告多报'


def test_numbering_audit_model_shape():
    """ORM 表/列契约：表名、主键、列集（迁移必须逐列对齐）。"""
    assert NumberingAudit.__tablename__ == 'numbering_audit'
    cols = {c.name for c in NumberingAudit.__table__.columns}
    assert cols == {'id', 'scope', 'counter_behind', 'detail', 'checked_at'}
    assert NumberingAudit.__table__.primary_key.columns.keys() == ['id']
