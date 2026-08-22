"""
编号序号原子分配（numbering_counter 表）

跨进程安全的序号水位管理：以 (prefix, number_date) 为粒度，通过
INSERT ... ON CONFLICT DO UPDATE ... RETURNING 原子递增。计数独立短事务
提交，与业务事务解耦——业务回滚仅产生跳号、不回收序号，消除多 worker
下"读到最大编号后未等业务提交即放锁"导致的重号窗口。

SQL 为常量文本，所有值经 :prefix/:number_date/:last_seq 绑定参数传递。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models.numbering_counter import NumberingCounter

logger = logging.getLogger(__name__)

# 常量 SQL：表名/列名为字面量，全部值经绑定参数传递（无用户输入拼接）
_ALLOCATE_SQL = text(
    'INSERT INTO numbering_counter (prefix, number_date, last_seq) '
    'VALUES (:prefix, :number_date, :last_seq) '
    'ON CONFLICT (prefix, number_date) '
    'DO UPDATE SET last_seq = numbering_counter.last_seq + 1 '
    'RETURNING numbering_counter.last_seq'
)  # nosec B608 - 常量 SQL 文本 + 绑定参数


async def allocate_sequence(prefix: str, date_str: str, seed: int = 0) -> int:
    """分配下一个序号（跨进程安全，允许跳号、杜绝重号）。

    seed 为当日已落库编号的最大序号，保证计数表首次使用时与历史编号连续；
    并发首次写入时，冲突分支的原子递增（last_seq + 1）保证唯一性。
    """
    from fastapi_app.core.database import _AsyncSessionLocal

    async with _AsyncSessionLocal() as short_session:
        row = await short_session.execute(
            _ALLOCATE_SQL,
            {'prefix': prefix, 'number_date': date_str, 'last_seq': seed + 1},
        )
        seq = row.scalar_one()
        await short_session.commit()  # manual-tx: 计数表独立短事务（有意与业务事务解耦）
    return seq


async def read_daily_max(db: AsyncSession, model, date_field: str, number_field: str) -> int:
    """读取调用方会话中当日已存在的最大编号序号（无锁读，仅作连续性种子）。

    使用调用方会话：同一业务事务内连续生成编号时能看到未提交行，批内连续。
    """
    today = datetime.now(UTC).replace(tzinfo=None)
    result = await db.execute(
        select(getattr(model, number_field))
        .where(func.date(getattr(model, date_field)) == today.date())
        .order_by(getattr(model, number_field).desc())
        .limit(1)
    )
    last_number = result.scalar()
    if not last_number:
        return 0
    tail = str(last_number).rsplit('-', 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return 0
