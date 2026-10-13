"""业务时区（北京时间）展示口径。

``order.order_date`` / ``staging_order.order_date`` 等列是 timestamptz，asyncpg
读回的是 aware UTC；直接 ``strftime`` 会按 UTC 渲染（早 8 小时）。展示统一走
:func:`fmt_business`，时区源与编号模块同源（``numbering_sequence._BUSINESS_TZ``），
不另起一套 —— 与报表屏幕 ``to_char`` 的会话时区（Asia/Shanghai）口径一致。
"""
from datetime import datetime

from fastapi_app.services.numbering_sequence import _BUSINESS_TZ


def fmt_business(dt: datetime | None, fmt: str = '%Y-%m-%d %H:%M') -> str:
    """把 aware-UTC 的 DB 时间转成北京时间字符串；``None`` → ``''``。"""
    if dt is None:
        return ''
    return dt.astimezone(_BUSINESS_TZ).strftime(fmt)
