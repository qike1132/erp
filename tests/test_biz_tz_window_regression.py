"""时区族回归（M-41 / M-26 / M-3，2026-11-21 全量审计）。

timestamptz 列 + naive date/字符串参数的窗口正确性耦合在会话时区（生产恰为
Asia/Shanghai 才对；迁移/新集群默认 UTC 即月窗漂移 −8h）；naive-UTC 列
（``batch_completed_at``）按北京日历日筛选必须走 ``business_day_bounds_utc_naive``
（AUD-02 已建标准，此前未在四处应用）。

本文件把会话时区强制 ``SET TIME ZONE 'UTC'`` 复现漂移：修复前这些窗口漏掉
北京 00:00–07:59 的记录（Red）；修复后窗口与会话时区解耦（Green）。
"""
import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

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
