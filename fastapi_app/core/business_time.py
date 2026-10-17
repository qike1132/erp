"""业务时区（北京时间）口径 —— stdlib-only 叶子模块。

时区源的**唯一定义点**（2026-10-13 由 ``numbering_sequence`` 下沉到 core，使
``shared_models`` 也能引用而**不反向依赖 services**）。``numbering_sequence`` 与
``services.business_time`` 均从此处 re-export，不另起一套。

展示口径：DB 的 timestamptz 列经 asyncpg 读回为 aware-UTC，直接 ``strftime`` 会按
UTC 渲染（早 8 小时）；展示统一走 :func:`fmt_business`，与报表屏幕 ``to_char`` 的
会话时区（Asia/Shanghai）一致。

Windows 无系统 tz 库，``ZoneInfo('Asia/Shanghai')`` 依赖 requirements/base.txt 的
tzdata 包。
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_BUSINESS_TZ = ZoneInfo('Asia/Shanghai')


def business_today() -> date:
    """业务时区（Asia/Shanghai）的「今天」。

    2026-10-17 审计 AUD-23：仪表盘此前一端用 UTC 日界、一端用服务器本地日界，
    UTC+8 部署下每天 00:00–08:00 两端「今日」数字不一致。所有「今日/本月」
    口径统一从本模块取业务时区，禁止再用裸 date.today() / datetime.now(UTC)。
    """
    return datetime.now(_BUSINESS_TZ).date()


def business_day_range(day: date | None = None) -> tuple[datetime, datetime]:
    """返回业务时区下 [day 00:00, day+1 00:00) 的 aware 边界。"""
    target = day or business_today()
    start = datetime(target.year, target.month, target.day, tzinfo=_BUSINESS_TZ)
    return start, start + timedelta(days=1)


def business_month_range(day: date | None = None) -> tuple[datetime, datetime]:
    """返回业务时区下 [本月 1 日 00:00, 次月 1 日 00:00) 的 aware 边界。"""
    target = day or business_today()
    start = datetime(target.year, target.month, 1, tzinfo=_BUSINESS_TZ)
    if target.month == 12:
        end = datetime(target.year + 1, 1, 1, tzinfo=_BUSINESS_TZ)
    else:
        end = datetime(target.year, target.month + 1, 1, tzinfo=_BUSINESS_TZ)
    return start, end


def fmt_business(dt: datetime | None, fmt: str = '%Y-%m-%d %H:%M') -> str:
    """把 aware-UTC 的 DB 时间转成北京时间字符串；``None`` → ``''``。"""
    if dt is None:
        return ''
    return dt.astimezone(_BUSINESS_TZ).strftime(fmt)
