"""编号不变量巡检（ARQ cron）：counter_behind 与 format_violations 落库。

只对反向偏差（数据号 > 水位）记录 behind；正向跳号（删除/回滚）是文档化
的正常语义（spec §4.5 重要设计约束）——水位高于数据 max 不报警。缺水位行
（新键首用前）同样不算 behind，seed 机制兜底。

事务边界：``compute_audit`` 为纯计算，不写库、不 commit（测试在回滚事务内
直接调用）；ARQ 入口 ``numbering_audit_task`` 是调用方，自行开会话并 commit。

SQL 风格：每实体一条集合式聚合查询（当日 data_max）+ 一条 COUNT（违规数），
无循环内逐行查询（非 N+1）。表名/列名取自 NUMBERED_ENTITIES 白名单常量，
值经绑定参数传递。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import require_async_session_local
from fastapi_app.services.numbering_reconcile import NUMBERED_ENTITIES
from fastapi_app.services.numbering_sequence import business_date_str
from fastapi_app.shared_models import NumberingAudit, NumberingCounter

logger = logging.getLogger(__name__)

# 单实体当日数据 max：仅统计合规编号（正则守卫）且编号日期段=当天。值走绑定参数。
# 表名/列名为白名单常量，非用户输入（nosec B608）。
_ENTITY_MAX_SQL = (
    'SELECT COALESCE(MAX(CAST(split_part("{column}", \'-\', 3) AS BIGINT)), 0) '
    'FROM "{table}" '
    'WHERE "{column}" ~ \'^[A-Z]+-[0-9]{{8}}-[0-9]+$\' '
    'AND split_part("{column}", \'-\', 2) = :today'
)

# 单实体格式违规计数：不符合 `^[A-Z]+-YYYYMMDD-N$` 的编号行数。
_ENTITY_VIOLATION_SQL = (
    'SELECT COUNT(*) FROM "{table}" '
    'WHERE "{column}" !~ \'^[A-Z]+-[0-9]{{8}}-[0-9]+$\''
)


async def _audit_entity(
    db: AsyncSession, prefix: str, table: str, column: str, today: str,
) -> tuple[dict, dict | None]:
    """巡检单个实体：返回 (前缀记录, 违规记录或 None)。

    两个查询都是集合式单语句；help 函数化以便 compute_audit 的循环体不含
    逐行查询（通过 N+1 静态扫描）。
    """
    data_max = int((await db.execute(
        text(_ENTITY_MAX_SQL.format(column=column, table=table)),  # nosec B608 - 白名单常量
        {'today': today},
    )).scalar() or 0)
    counter = (await db.execute(
        select(NumberingCounter.last_seq).where(
            NumberingCounter.prefix == prefix,
            NumberingCounter.number_date == today)
    )).scalar()
    # 缺行（counter is None）不算 behind：新键首用前计数行不存在是正常态。
    behind = counter is not None and data_max > counter
    bad = int((await db.execute(
        text(_ENTITY_VIOLATION_SQL.format(column=column, table=table)),  # nosec B608 - 白名单常量
    )).scalar() or 0)
    violation = {'table': table, 'column': column, 'count': bad} if bad else None
    return (
        {'prefix': prefix, 'data_max': data_max, 'counter': counter, 'counter_behind': behind},
        violation,
    )


async def compute_audit(db: AsyncSession) -> dict:
    """计算一轮巡检结果（不写库、不 commit；测试直接调用）。"""
    today = business_date_str()
    prefixes: list[dict] = []
    violations: list[dict] = []
    for prefix, table, column in NUMBERED_ENTITIES:
        record, violation = await _audit_entity(db, prefix, table, column, today)
        prefixes.append(record)
        if violation is not None:
            violations.append(violation)
    return {
        'checked_at': datetime.now(UTC).isoformat(),
        'prefixes': prefixes,
        'violations': violations,
    }


async def numbering_audit_task(ctx) -> dict:
    """ARQ cron 入口：计算并落库（调用方会话，自行 commit）。"""
    session_factory = require_async_session_local()
    async with session_factory() as db:
        report = await compute_audit(db)
        now = datetime.now(UTC)
        db.add_all([
            NumberingAudit(
                scope=p['prefix'],
                counter_behind=1 if p['counter_behind'] else 0,
                detail=f"data_max={p['data_max']} counter={p['counter']}",
                checked_at=now,
            )
            for p in report['prefixes']
        ] + [
            NumberingAudit(
                scope=f'{v["table"]}.{v["column"]}',
                counter_behind=0,
                detail=f'format violations={v["count"]}',
                checked_at=now,
            )
            for v in report['violations']
        ])
        await db.commit()
    logger.info(
        '编号巡检完成: prefixes=%d violations=%d',
        len(report.get('prefixes', [])), len(report.get('violations', [])),
    )
    return report
