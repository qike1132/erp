"""cron 周字段：`0` 必须等价于 `7`（周日），不能"校验通过却永不命中"。

背景（/backup 审计，high）
-------------------------
`_FIELD_RANGES` 给周字段的范围是 `(0, 7)`，于是 `0` 能通过 `parse_cron` 校验；
但匹配用的是 `datetime.isoweekday()`（1=周一 … 7=周日），`0` 永远比不出 True。
结果：`0 3 * * 0`（每周日）这类调度**静默地一次都不会执行** —— 配置看起来正常，
备份/巡检却从没跑过，比报错更难发现。

修法放在解析处（`parse_cron`）：周字段里的 0 归一为 7，`cron_matches` 与
`_last_match_before` 两个匹配入口一次性覆盖。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from fastapi_app.services.backup.schedule_service import (
    _last_match_before,
    cron_matches,
    parse_cron,
)

# 2026-09-27 是周日，2026-09-28 是周一
_SUNDAY = datetime(2026, 9, 27, 3, 0)
_MONDAY = datetime(2026, 9, 28, 3, 0)


def test_sunday_via_zero_matches() -> None:
    assert cron_matches('0 3 * * 0', _SUNDAY) is True


def test_sunday_via_seven_matches() -> None:
    assert cron_matches('0 3 * * 7', _SUNDAY) is True


def test_zero_is_not_monday() -> None:
    """0 归一成周日后，绝不能再误配到周一（1 才是周一）。"""
    assert cron_matches('0 3 * * 0', _MONDAY) is False


def test_one_is_monday() -> None:
    assert cron_matches('0 3 * * 1', _MONDAY) is True
    assert cron_matches('0 3 * * 1', _SUNDAY) is False


def test_parse_normalizes_zero_to_seven() -> None:
    assert parse_cron('* * * * 0')[4] == {7}
    assert parse_cron('* * * * 0,3')[4] == {3, 7}


def test_zero_and_seven_are_equivalent_across_the_week() -> None:
    """用 7 天逐一对比两种写法，行为必须完全一致。"""
    import datetime as _dt

    base = datetime(2026, 9, 21, 3, 0)  # 周一
    for offset in range(7):
        day = base + _dt.timedelta(days=offset)
        assert cron_matches('0 3 * * 0', day) == cron_matches('0 3 * * 7', day), day
        assert cron_matches('0 3 * * 0', day) == (day.isoweekday() == 7), day


@pytest.mark.parametrize('expr', ['0 3 * * 5-7', '0 3 * * 6,0', '0 3 * * 1-7'])
def test_sunday_is_reachable_via_ranges_and_lists(expr: str) -> None:
    """范围/列表里的 0 同样要能被匹配到。"""
    assert cron_matches(expr, _SUNDAY) is True


def test_last_match_before_finds_sunday() -> None:
    """回溯也必须认 0 —— 否则「本周日已过」的判断永远为假，调度永不触发。"""
    # 从周一看，最近一次周日 03:00 命中应当是 2026-09-27 03:00
    found = _last_match_before('0 3 * * 0', _MONDAY)

    assert found == _SUNDAY


def test_invalid_weekday_still_rejected() -> None:
    assert parse_cron('0 3 * * 8') is None
    assert cron_matches('0 3 * * 8', _SUNDAY) is False
