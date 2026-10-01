"""P0-5：库存业务时间必须用北京时间（用 UTC 会让北京时间 00:00–08:00 落到前一天）。"""
from datetime import UTC, datetime, timedelta, timezone

from fastapi_app.services import stock_common


class _FrozenDatetime(datetime):
    """把 datetime.now(tz) 冻结在 2026-09-30 16:30 UTC（= 北京 2026-10-01 00:30）。"""

    @classmethod
    def now(cls, tz=None):
        frozen = datetime(2026, 9, 30, 16, 30, 0, tzinfo=UTC)
        return frozen.replace(tzinfo=None) if tz is None else frozen.astimezone(tz)

    @classmethod
    def strptime(cls, date_string, fmt):
        return datetime.strptime(date_string, fmt)


def test_business_now_is_beijing_wall_clock():
    now = stock_common.business_now()
    beijing = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    assert now.tzinfo is None
    assert abs(now - beijing) < timedelta(minutes=1)


def test_business_now_shares_timezone_source_with_numbering():
    """时区源必须是 numbering_sequence._BUSINESS_TZ，不另起一套（P0-5 明文要求）。"""
    from fastapi_app.services import numbering_sequence

    assert stock_common._BUSINESS_TZ is numbering_sequence._BUSINESS_TZ
    assert str(stock_common._BUSINESS_TZ) == "Asia/Shanghai"


def test_parse_date_preserve_time_uses_beijing_time_of_day(monkeypatch):
    """北京 2026-10-01 00:30（UTC 2026-09-30 16:30）→ 业务日仍是 2026-10-01。"""
    monkeypatch.setattr(stock_common, "datetime", _FrozenDatetime)
    result = stock_common._parse_date_preserve_time("2026-10-01")
    assert result == datetime(2026, 10, 1, 0, 30, 0)
    assert result.date() == datetime(2026, 10, 1).date()
    # 旧实现取 datetime.now(UTC) 的时分秒 → 16:30（差 8 小时，夜间入库会跨日）
    assert (result.hour, result.minute) == (0, 30)


def test_parse_date_preserve_time_keeps_explicit_old_time(monkeypatch):
    monkeypatch.setattr(stock_common, "datetime", _FrozenDatetime)
    old_time = datetime(2026, 10, 1, 8, 5, 0)
    assert stock_common._parse_date_preserve_time("2026-10-01", old_time) == old_time


def test_invalid_date_still_raises(monkeypatch):
    monkeypatch.setattr(stock_common, "datetime", _FrozenDatetime)
    try:
        stock_common._parse_date_preserve_time("2026/10/01")
    except ValueError as exc:
        assert "日期格式不正确" in str(exc)
    else:  # pragma: no cover - 明确断言必须抛
        raise AssertionError("非法日期格式必须抛 ValueError")
