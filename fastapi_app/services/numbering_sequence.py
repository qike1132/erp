"""
编号序号原子分配（numbering_counter 表）

跨进程安全的序号水位管理：以 (prefix, number_date) 为粒度，通过
INSERT ... ON CONFLICT DO UPDATE ... RETURNING 原子递增。计数独立短事务
提交，与业务事务解耦——业务回滚仅产生跳号、不回收序号，消除多 worker
下"读到最大编号后未等业务提交即放锁"导致的重号窗口。

水位单调（P1-4）：冲突分支取 ``GREATEST(numbering_counter.last_seq, :seed)``
再递增。当计数行落后于当日已落库最大编号（历史编号、计数行被重建、
手工导入/清理）时，旧实现 ``last_seq + 1`` 会把序号拉回到历史编号之下
（唯一约束报错或直接重号），现改为先追平 seed 再递增，任何 counter 与
seed 组合下都只前进。

SQL 为常量文本，所有值经 :prefix/:number_date/:last_seq 绑定参数传递。
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 编号日期段的业务口径时区。Windows 无系统 tz 库，ZoneInfo('Asia/Shanghai')
# 依赖 requirements/base.txt 的 tzdata 包。
_BUSINESS_TZ = ZoneInfo('Asia/Shanghai')


def business_date_str() -> str:
    """业务口径（北京时间）的 YYYYMMDD —— 编号日期段的唯一来源（spec §4.1）。"""
    return datetime.now(_BUSINESS_TZ).strftime('%Y%m%d')

# 常量 SQL：表名/列名为字面量，全部值经绑定参数传递（无用户输入拼接）
_ALLOCATE_SQL = text(
    'INSERT INTO numbering_counter (prefix, number_date, last_seq) '
    'VALUES (:prefix, :number_date, :last_seq) '
    'ON CONFLICT (prefix, number_date) '
    'DO UPDATE SET last_seq = GREATEST(numbering_counter.last_seq, CAST(:seed AS BIGINT)) + 1 '
    'RETURNING numbering_counter.last_seq'
)  # nosec B608 - 常量 SQL 文本 + 绑定参数

# 批量版：一次 +count。**必须单语句原子完成** —— 循环调用单号版只是把 N 次
# 往返搬进本函数内部，既失去批量化的全部收益，又在并发下不再保证是一段连号。
_ALLOCATE_RANGE_SQL = text(
    'INSERT INTO numbering_counter (prefix, number_date, last_seq) '
    'VALUES (:prefix, :number_date, :last_seq) '
    'ON CONFLICT (prefix, number_date) '
    'DO UPDATE SET last_seq = GREATEST(numbering_counter.last_seq, CAST(:seed AS BIGINT)) + :count '
    'RETURNING numbering_counter.last_seq'
)  # nosec B608 - 常量 SQL 文本 + 绑定参数


async def allocate_sequence(prefix: str, date_str: str, seed: int = 0) -> int:
    """分配下一个序号（跨进程安全，允许跳号、杜绝重号）。

    seed 为当日已落库编号的最大序号，保证计数表首次使用时与历史编号连续；
    冲突分支的原子递增为 ``GREATEST(last_seq, seed) + 1``：计数行落后于
    seed 时先追平再递增，于是任何 counter/seed 组合下都不倒退、不重号。
    """
    from fastapi_app.core.database import require_async_session_local

    session_factory = require_async_session_local()
    async with session_factory() as short_session:
        row = await short_session.execute(
            _ALLOCATE_SQL,
            {
                'prefix': prefix,
                'number_date': date_str,
                'last_seq': seed + 1,
                'seed': seed,
            },
        )
        seq = row.scalar_one()
        await short_session.commit()  # manual-tx: 计数表独立短事务（有意与业务事务解耦）
    return seq


async def allocate_sequence_range(prefix: str, date_str: str, count: int, seed: int = 0) -> int:
    """一次性预留 ``count`` 个**连续**序号，返回该段的起始序号（含）。

    与 :func:`allocate_sequence` 共用同一张 ``numbering_counter`` 表与同一套
    冲突语义，因此两者混用也不会重号：单号版占用 ``last_seq`` 的下一格，
    批量版一次推进 ``count`` 格。

    语义与单号版一致：
    - 首次使用（表中无该 prefix+date 行）以 ``seed + count`` 落库，
      于是返回 ``seed + 1``，与单号版的 ``seed + 1`` 对齐；
    - 已有计数时从 ``GREATEST(last_seq, seed) + 1`` 起算：counter 落后于
      seed（水位被重建/历史编号更大）时先追平 seed 再占用，绝不倒退；
    - 业务事务回滚只产生跳号，不回收序号（既有语义，不变）。

    Args:
        prefix: 编号前缀，如 ``'PO'``。
        date_str: 日期串，如 ``'20260913'``。
        count: 需要预留的个数，必须 ≥ 1。
        seed: 当日已落库编号的最大序号（连续性种子）。

    Returns:
        该段的起始序号 ``start``；调用方可用 ``start + i`` (i ∈ [0, count)) 取号。

    Raises:
        ValueError: ``count < 1``。批量取 0 个号属于调用方逻辑错误，
            静默返回会让「导入 0 条」和「忘了取号」无法区分。
    """
    if count < 1:
        raise ValueError(f'allocate_sequence_range 的 count 必须 >= 1，收到 {count}')

    from fastapi_app.core.database import require_async_session_local

    session_factory = require_async_session_local()
    async with session_factory() as short_session:
        row = await short_session.execute(
            _ALLOCATE_RANGE_SQL,
            {
                'prefix': prefix,
                'number_date': date_str,
                'last_seq': seed + count,
                'count': count,
                'seed': seed,
            },
        )
        end_seq = row.scalar_one()
        await short_session.commit()  # manual-tx: 计数表独立短事务（有意与业务事务解耦）
    return end_seq - count + 1


async def read_daily_max(db: AsyncSession, model, number_field: str, date_str: str) -> int:
    """当日已落库的最大序号（按数值排序，无锁读，仅作连续性种子）。

    以编号自身的日期段过滤（split_part 第 2 段），与日期列的时区口径无关；
    正则守卫保证进入 cast 的序号段必为数字（脏行不抛 invalid input syntax）。

    使用调用方会话：同一业务事务内连续生成编号时能看到未提交行，批内连续。
    """
    col = getattr(model, number_field)
    seq = func.cast(func.split_part(col, '-', 3), BigInteger)
    result = await db.execute(
        select(func.max(seq)).where(col.op('~')(f'^[A-Z]+-{date_str}-[0-9]+$'))
    )
    return int(result.scalar() or 0)
