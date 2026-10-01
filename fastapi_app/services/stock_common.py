"""
库存模块共享辅助工具

存放被入库/出库/退货多个子模块共用的工具函数，避免重复定义。
"""
from datetime import datetime

from fastapi_app.services.numbering_sequence import _BUSINESS_TZ


def business_now() -> datetime:
    """业务口径（北京时间）当前时间，naive（DB 列为 TIMESTAMP WITHOUT TIME ZONE）。

    用 UTC 的时分秒去拼 naive 业务时间，会让北京时间 00:00–08:00 的入库
    落到前一天（UTC 落后 8 小时）。时区源与编号模块同源，不另起一套
    （fastapi_app/services/numbering_sequence.py::_BUSINESS_TZ，2026-10-01 P0-5）。
    """
    return datetime.now(_BUSINESS_TZ).replace(tzinfo=None)


def _parse_date_preserve_time(date_str: str, old_time: datetime | None = None) -> datetime:
    """解析入库日期（保留原始时间部分）"""
    try:
        base = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('日期格式不正确！') from None
    now = business_now()
    if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
        return datetime(base.year, base.month, base.day, old_time.hour, old_time.minute, old_time.second)
    else:
        return datetime(base.year, base.month, base.day, now.hour, now.minute, now.second)
