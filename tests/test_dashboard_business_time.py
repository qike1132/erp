"""仪表盘业务时区口径回归（2026-10-17 审计 AUD-23）

缺陷：桌面端 stats 用 UTC 日界、移动端 mobile 用服务器本地日界，
UTC+8 部署下每天 00:00–08:00「今日」指标两端分叉。
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi_app.core.business_time import (
    business_day_range,
    business_month_range,
    business_today,
)

TZ = ZoneInfo('Asia/Shanghai')


def test_day_range_is_local_midnight_aware():
    start, end = business_day_range(date(2026, 10, 17))

    assert start == datetime(2026, 10, 17, 0, 0, tzinfo=TZ)
    assert end == datetime(2026, 10, 18, 0, 0, tzinfo=TZ)
    assert end - start == timedelta(days=1)
    assert start.utcoffset() == timedelta(hours=8)


def test_month_range_crosses_year():
    start, end = business_month_range(date(2026, 12, 15))

    assert start == datetime(2026, 12, 1, 0, 0, tzinfo=TZ)
    assert end == datetime(2027, 1, 1, 0, 0, tzinfo=TZ)


def test_business_today_matches_local_clock():
    expected = datetime.now(TZ).date()
    assert business_today() == expected


def test_utc_1630_belongs_to_next_local_day():
    """UTC 16:30 = 本地次日 00:30 —— 应落在次日的业务日区间内"""
    utc_dt = datetime(2026, 10, 17, 16, 30, tzinfo=ZoneInfo('UTC'))
    local = utc_dt.astimezone(TZ)

    start, end = business_day_range(local.date())

    assert start <= local < end
    assert local.date() == date(2026, 10, 18)
