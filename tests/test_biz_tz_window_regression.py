"""时区族回归（M-41 / M-26 / M-3 / V-02，2026-11-21/23 全量审计）。

timestamptz 列 + naive date/字符串参数的窗口正确性耦合在会话时区（生产恰为
Asia/Shanghai 才对；迁移/新集群默认 UTC 即月窗漂移 −8h）；naive-UTC 列
（``batch_completed_at``）按北京日历日筛选必须走 ``business_day_bounds_utc_naive``
（AUD-02 已建标准，此前未在四处应用）。V-02（2026-11-23）把同一口径锁到
**导出侧**（shared/report_data_service）：此前只有屏幕侧有回归，导出 Excel 在
UTC 会话下会静默漏掉北京 00:00–07:59 的流水。

本文件把会话时区强制 ``SET TIME ZONE 'UTC'`` 复现漂移：修复前这些窗口漏掉
北京 00:00–07:59 的记录（Red）；修复后窗口与会话时区解耦（Green）。
"""
import asyncio
import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest_asyncio
from conftest import TEST_DATABASE_URL
from sqlalchemy import delete, select, text

from fastapi_app.services import order_batch_service as obs
from fastapi_app.services import production_summary_service as pss
from fastapi_app.services import report_service as rs
from fastapi_app.shared_models import Case, CaseMovement, Order, OrderSyncConfig

# 北京 2026-11-01 00:30 == UTC 2026-10-31 16:30（会话时区为 UTC 时最容易漏的窗口）
_BEIJING_EARLY_AWARE = datetime(2026, 10, 31, 16, 30, tzinfo=UTC)
_BEIJING_EARLY_NAIVE_UTC = datetime(2026, 10, 31, 16, 30)  # naive-UTC 列的等值
CUSTOMER = "客户时区Z1"


async def _force_utc(db):
    await db.execute(text("SET TIME ZONE 'UTC'"))


async def test_case_stockout_daily_window_decoupled_from_session_tz(async_db_session):
    """M-41：皮套出库月窗在 UTC 会话下仍按北京日界命中。"""
    db = async_db_session
    await _force_utc(db)
    case = Case(name="时区皮套A", current_stock=50)
    db.add(case)
    await db.flush()
    db.add(CaseMovement(
        case_id=case.id, direction="out", movement_no="CSO-TZ-1",
        quantity=7, customer=CUSTOMER, movement_date=_BEIJING_EARLY_AWARE,
    ))
    await db.flush()

    result = await pss._get_case_stockout_daily(db, start=date(2026, 11, 1), end=date(2026, 11, 30))
    assert result.get("2026-11-01") == 7, result


async def test_order_logs_window_decoupled_from_session_tz(async_db_session):
    """M-26 代表性集成：订单流水日窗在 UTC 会话下仍按北京日界命中。"""
    db = async_db_session
    await _force_utc(db)
    db.add(Order(
        order_no="TZ-ORD-1", customer=CUSTOMER, quantity=5,
        order_date=_BEIJING_EARLY_AWARE, status="pending",
    ))
    await db.flush()

    result = await rs.get_order_logs(
        db, customer=CUSTOMER, start_date="2026-11-01", end_date="2026-11-01")
    assert any(row["order_no"] == "TZ-ORD-1" for row in result["logs"]), result["logs"]


async def test_batch_history_window_decoupled_from_session_tz(async_db_session, monkeypatch):
    """M-3：批次完成时间是 naive-UTC 列，历史筛选必须走 naive-UTC 业务日界。"""
    from fastapi_app.shared_models.order import ORDER_STATUS_BATCH_COMPLETED

    async def _no_redis():
        return None

    monkeypatch.setattr(obs, "_get_redis_client", _no_redis)
    db = async_db_session
    await _force_utc(db)
    db.add(OrderSyncConfig(
        config_key="order_batch_whitelist", config_value=json.dumps([CUSTOMER])))
    db.add(Order(
        order_no="TZ-BATCH-1", customer=CUSTOMER, quantity=3,
        status=ORDER_STATUS_BATCH_COMPLETED,
        batch_completed_at=_BEIJING_EARLY_NAIVE_UTC,
    ))
    await db.flush()

    result = await obs.get_batch_history(db, date_from="2026-11-01", date_to="2026-11-01")
    assert any(o["order_no"] == "TZ-BATCH-1" for o in result["items"]), result["items"]


def test_apply_date_filter_bounds_are_aware():
    """M-41（case/_common）：_apply_date_filter 的绑定参数必须是业务时区 aware 边界。"""
    from sqlalchemy.dialects import postgresql

    from fastapi_app.services.case._common import _apply_date_filter

    stmt = _apply_date_filter(
        select(CaseMovement.id), CaseMovement.movement_date,
        "2026-11-01", "2026-11-30", "开始日期")
    compiled = stmt.compile(dialect=postgresql.dialect())
    values = list(compiled.params.values())
    assert len(values) == 2, values
    start, end = values
    tz = ZoneInfo("Asia/Shanghai")
    assert start == datetime(2026, 11, 1, 0, 0, tzinfo=tz), values
    assert end == datetime(2026, 12, 1, 0, 0, tzinfo=tz), values


# ============================================================
# V-02（2026-11-23 审计）：导出侧日期窗时区解耦
# ============================================================
# 屏幕侧（report_service._append_biz_date_window）已绑 business_day_range() 的
# aware 边界，上面的用例锁死；导出侧（shared/report_data_service._apply_date_filters）
# 此前绑 naive 值（parse_date_strict + timedelta(days=1)），窗口正确性耦合在
# 「会话时区恰为 Asia/Shanghai」（生产靠 postgresql.conf 钉住，T-05 实测）。
# 会话时区一旦为 UTC（迁移/新集群/PgBouncer 池变更），导出 Excel 会静默漏掉
# 北京 00:00–07:59 的流水，而屏幕正常。以下用例把导出路径也锁死到 aware 边界。

_EXPORT_TZ_ORDER_NO = "TZ-EXPORT-ORD-1"
_EXPORT_TZ_CUSTOMER = "客户时区导出Z1"


@pytest_asyncio.fixture
async def export_tz_cleanup(async_db_session):
    """用例结束后清掉本文件造的行（共享测试库只在会话开始时整库重置）。"""
    yield
    await async_db_session.execute(
        delete(Order).where(Order.order_no == _EXPORT_TZ_ORDER_NO))
    await async_db_session.commit()


def _run_export_in_session(session_tz: str, start_date: str, end_date: str):
    """在指定会话时区的**同步 psycopg3 连接**里跑导出查询（与生产导出同构：
    export_report_to_excel / report_tasks 都用同步 Session）。

    返回 (logs, stats)。种子必须先 commit 才对这条独立连接可见。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from fastapi_app.shared.report_data_service import get_all_logs_data

    sync_url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg")
    engine = create_engine(sync_url)
    session = sessionmaker(bind=engine)()
    try:
        session.execute(text(f"SET TIME ZONE '{session_tz}'"))
        logs, stats = get_all_logs_data(
            session, "order", customer=_EXPORT_TZ_CUSTOMER,
            start_date=start_date, end_date=end_date)
        return logs, stats
    finally:
        session.close()
        engine.dispose()


async def test_export_order_logs_window_decoupled_from_session_tz(
        async_db_session, export_tz_cleanup):
    """V-02 Red→Green：UTC 会话下导出日期窗仍按北京日界命中 00:00–07:59 的记录。

    修复前：_apply_date_filters 绑 naive ``2026-11-01 00:00``，UTC 会话把
    timestamptz 列按 UTC 解释 → 北京 11-01 00:30（UTC 10-31 16:30）落在窗口外，
    导出漏行（Red）。修复后：aware 边界与会话时区解耦（Green）。
    """
    db = async_db_session
    db.add(Order(
        order_no=_EXPORT_TZ_ORDER_NO, customer=_EXPORT_TZ_CUSTOMER, quantity=5,
        order_date=_BEIJING_EARLY_AWARE, status="pending",
    ))
    await db.commit()  # 独立同步连接必须能看见这行

    logs, stats = await asyncio.to_thread(
        _run_export_in_session, "UTC", "2026-11-01", "2026-11-01")
    assert any(row["order_no"] == _EXPORT_TZ_ORDER_NO for row in logs), logs
    assert stats["total_count"] >= 1, stats


async def test_export_window_equivalent_in_shanghai_session(
        async_db_session, export_tz_cleanup):
    """生产语义等价性：Asia/Shanghai 会话下修复前后窗口必须一致。

    生产 postgresql.conf 把会话时区钉在 Asia/Shanghai（T-05 实测），此修复在该
    环境下必须零行为变化——naive→aware 绑定在 Asia/Shanghai 会话下等价。
    """
    db = async_db_session
    db.add(Order(
        order_no=_EXPORT_TZ_ORDER_NO, customer=_EXPORT_TZ_CUSTOMER, quantity=5,
        order_date=_BEIJING_EARLY_AWARE, status="pending",
    ))
    await db.commit()

    logs, stats = await asyncio.to_thread(
        _run_export_in_session, "Asia/Shanghai", "2026-11-01", "2026-11-01")
    assert any(row["order_no"] == _EXPORT_TZ_ORDER_NO for row in logs), logs
    assert stats["total_count"] >= 1, stats


def test_export_date_filter_bounds_are_aware():
    """V-02 单元级：_apply_date_filters 的绑定参数必须是业务时区 aware 边界。

    与 test_apply_date_filter_bounds_are_aware（case/_common）同构：直接编译
    语句断言绑定值，不依赖会话时区。修复前绑定 naive datetime（Red）。
    """
    from sqlalchemy.dialects import postgresql

    from fastapi_app.shared.report_data_service import _apply_date_filters
    from fastapi_app.shared_models import Order

    stmt = _apply_date_filters(
        select(Order.id), Order.order_date, "2026-11-01", "2026-11-01")
    compiled = stmt.compile(dialect=postgresql.dialect())
    values = list(compiled.params.values())
    assert len(values) == 2, values
    start, end = values
    tz = ZoneInfo("Asia/Shanghai")
    assert start == datetime(2026, 11, 1, 0, 0, tzinfo=tz), values
    assert end == datetime(2026, 11, 2, 0, 0, tzinfo=tz), values
