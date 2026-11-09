"""
编号序号原子分配（numbering_counter 表）

跨进程安全的序号水位管理：以 (prefix, number_date) 为粒度——``number_date``
是历史列名，值现在是**期间键**（新号 ``'2611'``、存量 ``'20261109'``）——通过
INSERT ... ON CONFLICT DO UPDATE ... RETURNING 原子递增。计数独立短事务
提交，与业务事务解耦——业务回滚仅产生跳号、不回收序号，消除多 worker
下"读到最大编号后未等业务提交即放锁"导致的重号窗口。

水位单调（P1-4）：冲突分支取 ``GREATEST(numbering_counter.last_seq, :seed)``
再递增。当计数行落后于当期已落库最大编号（历史编号、计数行被重建、
手工导入/清理）时，旧实现 ``last_seq + 1`` 会把序号拉回到历史编号之下
（唯一约束报错或直接重号），现改为先追平 seed 再递增，任何 counter 与
seed 组合下都只前进。

SQL 为常量文本，所有值经 :prefix/:number_date/:last_seq 绑定参数传递。
"""
import logging
import warnings
from datetime import datetime

from sqlalchemy import BigInteger, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import _BUSINESS_TZ  # 业务时区唯一定义点已下沉到 core.business_time
from fastapi_app.shared.numbering_format import NUMBERING_FORMAT_REGEX

logger = logging.getLogger(__name__)


def business_period_str() -> str:
    """业务口径（北京时间）的 YYMM —— 编号期间段的唯一来源。

    2026-11 起单号改为**月流水**（``PO-2611-001``），期间段是"年月"而非"日"。
    存量单号的 8 位日期段不受影响：``read_period_max`` 按编号自身分段过滤，
    ``'2611'`` 永远不会命中 ``'20261109'``，两个键空间互不覆盖。
    """
    return datetime.now(_BUSINESS_TZ).strftime('%y%m')


def business_date_str() -> str:
    """**已废弃**：改用 :func:`business_period_str`。

    名字仍在承诺"业务日期"，但返回值已经是 YYMM 期间（2026-11 是 ``'2611'``，
    不是 ``'20261109'``）。照旧名使用会把 4 位期间当成 8 位日期——例如拿去和
    日期列比较、或按 8 位截取，都是静默错。

    保留本函数只为兼容尚未迁移的调用方；每次调用都会发 FutureWarning。
    选 FutureWarning 而非 DeprecationWarning，是因为本仓 ``pytest.ini`` 显式
    ``ignore::DeprecationWarning``（与 UserWarning），只有 FutureWarning 会落到
    ``error`` 上——残留调用在测试里直接变红，而不是静默通过。
    """
    warnings.warn(
        'business_date_str() 已废弃且语义已变：返回 YYMM 期间（如 "2611"），'
        '不是 YYYYMMDD 日期。请改用 business_period_str()。',
        FutureWarning,
        stacklevel=2,
    )
    return business_period_str()


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


async def allocate_sequence(prefix: str, period: str, seed: int = 0) -> int:
    """分配下一个序号（跨进程安全，允许跳号、杜绝重号）。

    seed 为当期已落库编号的最大序号，保证计数表首次使用时与历史编号连续；
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
                'number_date': period,
                'last_seq': seed + 1,
                'seed': seed,
            },
        )
        seq = row.scalar_one()
        await short_session.commit()  # manual-tx: 计数表独立短事务（有意与业务事务解耦）
    return seq


async def allocate_sequence_range(prefix: str, period: str, count: int, seed: int = 0) -> int:
    """一次性预留 ``count`` 个**连续**序号，返回该段的起始序号（含）。

    与 :func:`allocate_sequence` 共用同一张 ``numbering_counter`` 表与同一套
    冲突语义，因此两者混用也不会重号：单号版占用 ``last_seq`` 的下一格，
    批量版一次推进 ``count`` 格。

    语义与单号版一致：
    - 首次使用（表中无该 (prefix, period) 行）以 ``seed + count`` 落库，
      于是返回 ``seed + 1``，与单号版的 ``seed + 1`` 对齐；
    - 已有计数时从 ``GREATEST(last_seq, seed) + 1`` 起算：counter 落后于
      seed（水位被重建/历史编号更大）时先追平 seed 再占用，绝不倒退；
    - 业务事务回滚只产生跳号，不回收序号（既有语义，不变）。

    Args:
        prefix: 编号前缀，如 ``'PO'``。
        period: 期间串，如 ``'2611'``（存量 8 位日期 ``'20260913'`` 亦可）。
        count: 需要预留的个数，必须 ≥ 1。
        seed: 当期已落库编号的最大序号（连续性种子）。

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
                'number_date': period,
                'last_seq': seed + count,
                'count': count,
                'seed': seed,
            },
        )
        end_seq = row.scalar_one()
        await short_session.commit()  # manual-tx: 计数表独立短事务（有意与业务事务解耦）
    return end_seq - count + 1


async def read_period_max(db: AsyncSession, model, number_field: str, period_str: str) -> int:
    """当期（本月）已落库的最大序号（按数值排序，无锁读，仅作连续性种子）。

    以编号自身的期间段过滤（split_part 第 2 段），与日期列的时区口径无关；
    正则守卫保证进入 cast 的序号段必为数字（脏行不抛 invalid input syntax）。

    2026-11-01（P3）：过滤器从「动态日期正则」改为「静态格式正则 +
    split_part 期间段等值」——语义等价，但静态谓词与各编号表的
    ``idx_*_no_date_seq`` 部分表达式索引（迁移 pg_standalone_116 重建）逐字匹配：
    PG 不做正则蕴含推断，动态日期正则永远用不上该索引（体检报告 §4-P3）。
    2026-11 起期间段由 8 位日期改为 4 位年月（YYMM），函数名随之从
    ``read_daily_max`` 改为 ``read_period_max``（旧名保留为会告警的废弃包装）。

    使用调用方会话：同一业务事务内连续生成编号时能看到未提交行，批内连续。
    """
    col = getattr(model, number_field)
    seq = func.cast(func.split_part(col, '-', 3), BigInteger)
    result = await db.execute(
        select(func.max(seq)).where(
            col.op('~')(NUMBERING_FORMAT_REGEX),
            func.split_part(col, '-', 2) == period_str,
        )
    )
    return int(result.scalar() or 0)


async def read_daily_max(db: AsyncSession, model, number_field: str, period: str) -> int:
    """**已废弃**：改用 :func:`read_period_max`。

    语义已从"当日最大序号"变为"当期（本月）最大序号"：留着旧名，半年后一定
    有人按"日"去用它、或按日去读一张按月的表。用 FutureWarning 而非
    DeprecationWarning——后者被 ``pytest.ini`` 显式忽略，起不到拦阻作用。
    """
    warnings.warn(
        'read_daily_max() 已废弃：语义已从"当日"改为"当期（本月）"，'
        '请改用 read_period_max()。',
        FutureWarning,
        stacklevel=2,
    )
    return await read_period_max(db, model, number_field, period)
