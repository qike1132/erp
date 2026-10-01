"""备份定时调度服务(M2)。

将 ARQ 硬编码 cron 迁移到 backup_schedule 表，由 scheduler_poller 每 5 分钟读取本表，
按 cron 表达式将到期任务入队。支持 full/incremental/integrity_check/cleanup 四类，
与现有 auto_* 任务函数一一映射，保证迁移后定时行为与现状等价。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

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
    # P1-4: 灾备演练月度例行化（迁移 037 种子 '30 3 1 * *'）
    'disaster_recovery_test': 'disaster_recovery_test_task',
}
VALID_TASK_TYPES = tuple(TASK_TYPE_TO_FUNC)

# cron 5 段取值范围:分 时 日 月 周
_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_DOW_FIELD_INDEX = 4


# ---------------------------------------------------------------------------
# cron 解析与匹配
# ---------------------------------------------------------------------------
def parse_cron(cron_expr: str) -> tuple[set[int] | None, ...] | None:
    """把 5 段 cron 解析为各字段取值集合；* 为 None(通配)。非法返回 None。"""
    parts = cron_expr.split()
    if len(parts) != 5:
        return None
    fields: list[set[int] | None] = []
    for idx, (part, (lo, hi)) in enumerate(zip(parts, _FIELD_RANGES, strict=False)):
        if part == '*':
            fields.append(None)
            continue
        vals: set[int] = set()
        for token in part.split(','):
            token = token.strip()
            if not token:
                return None
            if '-' in token:
                a_str, b_str = token.split('-', 1)
                if not (a_str.lstrip('-').isdigit() and b_str.lstrip('-').isdigit()):
                    return None
                a, b = int(a_str), int(b_str)
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
        # 周字段归一：标准 cron 里 0 与 7 都代表周日，而匹配侧用 isoweekday
        # (1=周一..7=周日)。不归一的话 `0 3 * * 0` 能通过校验却**永不命中** ——
        # 调度看起来配好了，实际一次都不会跑。归一放在解析处，匹配/回溯一次覆盖。
        if idx == _DOW_FIELD_INDEX and 0 in vals:
            vals.discard(0)
            vals.add(7)
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


def _last_match_before(cron_expr: str, now: datetime, max_days: int = 370) -> datetime | None:
    """返回 now 之前（含 now）最近一次命中 cron 的时刻；无则 None。

    - 逐天回溯（最多 max_days 天，覆盖月度/年度 cron），先匹配 日/月/周 字段；
    - 命中日在当天取「不大于 now 时分」的最大 时/分 组合；
    - 与 scheduler_poller 的 5 分钟采样解耦：只要窗口已过，后续任意采样都能发现。
    """
    fields = parse_cron(cron_expr)
    if fields is None:
        return None
    min_f, hour_f, dom_f, mon_f, dow_f = fields
    minutes = sorted(min_f, reverse=True) if min_f is not None else list(range(59, -1, -1))
    hours = sorted(hour_f, reverse=True) if hour_f is not None else list(range(23, -1, -1))
    for offset in range(max_days + 1):
        day = now - timedelta(days=offset)
        if not (
            _match(dom_f, day.day)
            and _match(mon_f, day.month)
            and _match(dow_f, day.isoweekday())
        ):
            continue
        # offset=0 时受 now 的时分限制：取「不大于 now」的最大匹配时分。
        if offset == 0:
            for h in hours:
                if h > now.hour:
                    continue
                if h < now.hour:
                    # 该小时已完全过去 → 取该小时最大匹配分钟（最近一次）。
                    return day.replace(hour=h, minute=minutes[0])
                for m in minutes:
                    if m <= now.minute:
                        return day.replace(hour=h, minute=m)
                break  # 当前小时无匹配分钟，当天无更早命中 → 回溯前一天
        else:
            return day.replace(hour=hours[0], minute=minutes[0])
    return None


def _as_local_naive(dt: datetime | None) -> datetime | None:
    """DB timestamptz 读出为 aware（UTC），归一为服务器本地 naive 以便与本地 cron 时间比较。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


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
    await db.flush()
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
    await db.flush()
    await db.refresh(row)
    return row


async def delete_schedule(db: AsyncSession, schedule_id: int) -> bool:
    row = await get_schedule(db, schedule_id)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def due_schedules(db: AsyncSession, now: datetime) -> list[BackupSchedule]:
    """返回 enabled 且「存在已过期未执行的 cron 窗口」的调度。

    判定：最近一次（<= now）命中 cron 的时刻 last_due 已产生，
    且该调度未在 last_due 之后执行过 → 触发（补跑错过的窗口）。
    与旧「当前分钟精确匹配」不同：worker 重启/采样错位错过窗口后，
    后续任意 poller 采样都会补跑，避免任务永久丢失。
    """
    out: list[BackupSchedule] = []
    for row in await list_schedules(db):
        if not row.enabled:
            continue
        last_due = _last_match_before(row.cron_expr, now)
        if last_due is None:
            continue
        last_run = _as_local_naive(row.last_run_at)
        if last_run is not None and last_run >= last_due:
            continue
        out.append(row)
    return out
