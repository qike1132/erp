"""统一展示时区格式化：DB 存 UTC，页面/导出统一输出北京时间。"""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo('Asia/Shanghai')


def format_local_time(
    dt: datetime | None,
    fmt: str = '%Y-%m-%d %H:%M:%S',
    *,
    naive_is_utc: bool = True,
    none_value: str | None = '',
) -> str | None:
    """UTC（aware 或 naive-UTC）→ 北京时间字符串。

    ``naive_is_utc=False`` 时对 naive 值只格式化、不做时区换算（用于已本地化的值）。
    """
    if dt is None:
        return none_value
    if dt.tzinfo is None:
        if not naive_is_utc:
            return dt.strftime(fmt)
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(LOCAL_TZ).strftime(fmt)
