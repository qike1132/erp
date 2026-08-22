"""备份定时调度服务(M2)。

将 ARQ 硬编码 cron 迁移到 backup_schedule 表，由 scheduler_poller 每 5 分钟读取本表，
按 cron 表达式将到期任务入队。支持 full/incremental/integrity_check/cleanup 四类，
与现有 auto_* 任务函数一一映射，保证迁移后定时行为与现状等价。
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models.backup_schedule import BackupSchedule

from .settings_service import BackupSettingsError

logger = logging.getLogger(__name__)

# 任务类型 → ARQ 任务函数名（与 arq_app.WorkerSettings.functions 对齐）
TASK_TYPE_TO_FUNC: dict[str, str] = {
    'full': 'auto_daily_backup_task',
    'incremental': 'auto_incremental_backup_task',
    'integrity_check': 'backup_integrity_check_task',
    'cleanup': 'backup_cleanup_task',
}
VALID_TASK_TYPES = tuple(TASK_TYPE_TO_FUNC)

# cron 5 段取值范围:分 时 日 月 周
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


# ---------------------------------------------------------------------------
# cron 解析与匹配
# ---------------------------------------------------------------------------
def parse_cron(cron_expr: str) -> tuple[set[int] | None, ...] | None:
    """把 5 段 cron 解析为各字段取值集合；* 为 None(通配)。非法返回 None。"""
    parts = cron_expr.split()
    if len(parts) != 5:
        return None
    fields: list[set[int] | None] = []
    for part, (lo, hi) in zip(parts, _FIELD_RANGES):
        if part == '*':
            fields.append(None)
            continue
        vals: set[int] = set()
        ok = True
        for token in part.split(','):
            token = token.strip()
            if not token:
                return None
            if '-' in token:
                a, b = token.split('-', 1)
                if not (a.lstrip('-').isdigit() and b.lstrip('-').isdigit()):
                    return None
                a, b = int(a), int(b)
                if a < lo or b > hi or a > b:
                    return None
                vals.update(range(a, b + 1))
            elif token.isdigit():
                v = int(token)
                if v < lo or v > hi:
                    return None
                vals.add(v)
            else:
                return None
        if not vals:
            return None
        fields.append(vals)
    return tuple(fields)


def _match(field: set[int] | None, value: int) -> bool:
    return field is None or value in field


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """dt 是否命中 cron 表达式。cron 周字段约定(0/7=周日),用 isoweekday(1=周一..7=周日)。"""
    fields = parse_cron(cron_expr)
    if fields is None:
        return False
    min_f, hour_f, dom_f, mon_f, dow_f = fields
    dow = dt.isoweekday()
    return (
        _match(min_f, dt.minute)
        and _match(hour_f, dt.hour)
        and _match(dom_f, dt.day)
        and _match(mon_f, dt.month)
        and _match(dow_f, dow)
    )


def _period(dt: datetime) -> tuple[int, int, int, int]:
    """固定分钟类 cron 的天然幂等粒度:年-月-日-时。"""
    return (dt.year, dt.month, dt.day, dt.hour)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
async def list_schedules(db: AsyncSession) -> list[BackupSchedule]:
    rows = (await db.execute(select(BackupSchedule).order_by(BackupSchedule.id))).scalars().all()
    return list(rows)


async def get_schedule(db: AsyncSession, schedule_id: int) -> BackupSchedule | None:
    return await db.get(BackupSchedule, schedule_id)


async def create_schedule(
    db: AsyncSession,
    *,
    name: str,
    task_type: str,
    cron_expr: str,
    enabled: bool = True,
) -> BackupSchedule:
    if not name or not name.strip():
        raise BackupSettingsError('任务名称不能为空')
    if task_type not in TASK_TYPE_TO_FUNC:
        raise BackupSettingsError(
            f'不支持的调度任务类型: {task_type}(可选 {", ".join(VALID_TASK_TYPES)})'
        )
    if parse_cron(cron_expr) is None:
        raise BackupSettingsError(f'非法 cron 表达式: {cron_expr}')
    row = BackupSchedule(
        name=name.strip(),
        task_type=task_type,
        cron_expr=cron_expr,
        enabled=enabled,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_schedule(
    db: AsyncSession,
    schedule_id: int,
    *,
    name: str | None = None,
    task_type: str | None = None,
    cron_expr: str | None = None,
    enabled: bool | None = None,
) -> BackupSchedule:
    row = await get_schedule(db, schedule_id)
    if row is None:
        raise BackupSettingsError('调度任务不存在')
    if name is not None:
        if not name.strip():
            raise BackupSettingsError('任务名称不能为空')
        row.name = name.strip()
    if task_type is not None:
        if task_type not in TASK_TYPE_TO_FUNC:
            raise BackupSettingsError(
                f'不支持的调度任务类型: {task_type}(可选 {", ".join(VALID_TASK_TYPES)})'
            )
        row.task_type = task_type
    if cron_expr is not None:
        if parse_cron(cron_expr) is None:
            raise BackupSettingsError(f'非法 cron 表达式: {cron_expr}')
        row.cron_expr = cron_expr
    if enabled is not None:
        row.enabled = enabled
    await db.commit()
    await db.refresh(row)
    return row


async def delete_schedule(db: AsyncSession, schedule_id: int) -> bool:
    row = await get_schedule(db, schedule_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def due_schedules(db: AsyncSession, now: datetime) -> list[BackupSchedule]:
    """返回 enabled 且 cron 命中当前时刻且未在本小时窗口执行过的调度。"""
    out: list[BackupSchedule] = []
    for row in await list_schedules(db):
        if not row.enabled:
            continue
        if not cron_matches(row.cron_expr, now):
            continue
        if row.last_run_at is not None and _period(row.last_run_at) == _period(now):
            continue
        out.append(row)
    return out