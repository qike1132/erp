"""
库存模块共享辅助工具

存放被入库/出库/退货多个子模块共用的工具函数，避免重复定义。
"""
from datetime import UTC, datetime


def _parse_date_preserve_time(date_str: str, old_time: datetime | None = None) -> datetime:
    """解析入库日期（保留原始时间部分）"""
    try:
        base = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError('日期格式不正确！') from None
    now = datetime.now(UTC)
    if old_time and (old_time.hour != 0 or old_time.minute != 0 or old_time.second != 0):
        return datetime(base.year, base.month, base.day, old_time.hour, old_time.minute, old_time.second)
    else:
        return datetime(base.year, base.month, base.day, now.hour, now.minute, now.second)
