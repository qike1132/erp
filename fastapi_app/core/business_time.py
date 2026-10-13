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
from datetime import datetime
from zoneinfo import ZoneInfo

_BUSINESS_TZ = ZoneInfo('Asia/Shanghai')


def fmt_business(dt: datetime | None, fmt: str = '%Y-%m-%d %H:%M') -> str:
    """把 aware-UTC 的 DB 时间转成北京时间字符串；``None`` → ``''``。"""
    if dt is None:
        return ''
    return dt.astimezone(_BUSINESS_TZ).strftime(fmt)
