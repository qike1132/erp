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

#: SQL 显式时区转换用（与 _BUSINESS_TZ 单源；M-41 分桶 timezone(BUSINESS_TZ_NAME, col)）
BUSINESS_TZ_NAME = 'Asia/Shanghai'


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


def isoformat_business(dt: datetime | None) -> str:
    """统一渲染为**北京显式偏移**的 ISO-8601（L-33/N-55，2026-11-21 审计）。

    此前备份域三种时间口径并存（naive ``isoformat()`` / ``'%Y-%m-%d %H:%M:%S'``
    / 裸 mtime ``isoformat()``），消费方无法判断时区。本函数统一输出形如
    ``2026-11-21T14:30:00+08:00``：

    - aware 输入：转业务时区后 ``isoformat()``（偏移显式随行）；
    - naive 输入（``datetime.now()``、``datetime.fromtimestamp(mtime)`` 等本地
      墙钟来源）：按系统本地时区解释后转业务时区——墙面时刻与旧口径渲染一致，
      只是补上了偏移标记；
    - ``None`` → ``''``。

    注意：``.meta`` sidecar 的 ``created_at`` 仍保持 ``'%Y-%m-%d %H:%M:%S'`` naive
    （records.write_backup_meta_file）——那是与 ``_backup_created_time`` 的 strptime
    读写契约，改动会让存量 sidecar 解析失败，不属本统一范围。
    """
    if dt is None:
        return ''
    return dt.astimezone(_BUSINESS_TZ).isoformat()


def fmt_business_naive_utc(dt: datetime | None, fmt: str = '%Y-%m-%d %H:%M') -> str:
    """把 **naive-UTC** 列（TIMESTAMP WITHOUT TIME ZONE、墙钟即 UTC）转成北京时间。

    AUD-02（2026-10-24 审计）：completed_at 等 20 个 naive 列存的是 UTC 墙钟，
    直接 strftime 恒慢 8 小时、北京 00:00–07:59 的记录落错天。naive 值必须先
    显式标记 UTC 再转业务时区——直接 astimezone 会按服务器本地时区解释，错得
    更远。aware 值请用 :func:`fmt_business`。
    """
    if dt is None:
        return ''
    from datetime import UTC as _UTC
    return dt.replace(tzinfo=_UTC).astimezone(_BUSINESS_TZ).strftime(fmt)


def business_day_bounds_utc_naive(day: date | None = None) -> tuple[datetime, datetime]:
    """业务日界的 **naive-UTC** 边界（供 naive-UTC 列的 SQL 比较）。

    北京 [day 00:00, day+1 00:00) → UTC naive [前日 16:00, 当日 16:00)。
    completed_at 这类 naive-UTC 列按北京日历日筛选时必须用本边界，否则
    北京 00:00–07:59 完成的记录落到前一天（AUD-02）。返回 (start, end)，
    比较用 ``>= start AND < end``（替代 '... 23:59:59' 闭区间——后者带 1 秒
    微秒洞且时区语义错位）。
    """
    from datetime import UTC as _UTC
    start_aware, end_aware = business_day_range(day)
    return (
        start_aware.astimezone(_UTC).replace(tzinfo=None),
        end_aware.astimezone(_UTC).replace(tzinfo=None),
    )
