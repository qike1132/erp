"""
日期处理工具模块
使用arrow库简化日期处理，支持人性化日期解析
"""

import arrow
from datetime import datetime
from typing import Tuple, Optional

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, MONTHLY


def parse_date_flexible(date_str: str) -> Optional[datetime]:
    """
    灵活解析日期字符串

    支持格式:
    - 2024-01-15
    - 2024/01/15
    - 昨天、今天、明天

    Args:
        date_str: 日期字符串

    Returns:
        datetime对象，解析失败返回None
    """
    if not date_str:
        return None

    date_str = date_str.strip()

    try:
        if date_str in ('今天', '今日'):
            return arrow.now().datetime
        elif date_str in ('昨天', '昨日'):
            return arrow.now().shift(days=-1).datetime
        elif date_str in ('明天', '明日'):
            return arrow.now().shift(days=1).datetime
        else:
            return arrow.get(date_str).datetime
    except Exception:
        return None


def get_date_range(period: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    获取日期范围

    Args:
        period: 时间段标识 (today/yesterday/week/month/quarter/year)

    Returns:
        (开始时间, 结束时间)
    """
    now = arrow.now()

    ranges = {
        'today': (now.floor('day'), now.ceil('day')),
        'yesterday': (now.shift(days=-1).floor('day'), now.shift(days=-1).ceil('day')),
        'week': (now.floor('week'), now.ceil('week')),
        'month': (now.floor('month'), now.ceil('month')),
        'quarter': (now.floor('quarter'), now.ceil('quarter')),
        'year': (now.floor('year'), now.ceil('year')),
    }

    if period in ranges:
        start, end = ranges[period]
        return start.datetime, end.datetime

    return None, None


def format_date_human(dt: datetime) -> str:
    """
    人性化日期格式化

    Args:
        dt: datetime对象

    Returns:
        人性化日期字符串，如"2小时前"
    """
    try:
        return arrow.get(dt).humanize(locale='zh')
    except Exception:
        return str(dt)


def get_last_day_of_month(dt: datetime) -> datetime:
    """
    获取月末日期

    Args:
        dt: datetime对象

    Returns:
        月末日期
    """
    return dt + relativedelta(day=31)


def add_months(dt: datetime, months: int) -> datetime:
    """
    增加月份（正确处理月末）

    Args:
        dt: datetime对象
        months: 增加的月份数

    Returns:
        增加月份后的日期
    """
    return dt + relativedelta(months=months)


def get_next_n_months(n: int) -> list:
    """
    获取未来N个月的月份列表

    Args:
        n: 月份数量

    Returns:
        月份日期列表
    """
    start = datetime.now().replace(day=1)
    return list(rrule(MONTHLY, dtstart=start, count=n))


def get_quarter_dates(year: int, quarter: int) -> Tuple[datetime, datetime]:
    """
    获取指定季度的起止日期

    Args:
        year: 年份
        quarter: 季度 (1-4)

    Returns:
        (季度开始日期, 季度结束日期)
    """
    start_month = (quarter - 1) * 3 + 1
    start = datetime(year, start_month, 1)
    end = start + relativedelta(months=3) - relativedelta(days=1)
    return start, end
