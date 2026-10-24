"""备份定时调度服务(M2)。

将 ARQ 硬编码 cron 迁移到 backup_schedule 表，由 scheduler_poller 每 5 分钟读取本表，
按 cron 表达式将到期任务入队。支持 full/integrity_check/cleanup 等类，
与现有 auto_* 任务函数一一映射，保证迁移后定时行为与现状等价。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.schedule_status import STATUS_RUNNING
from fastapi_app.shared_models.backup_schedule import BackupSchedule

from .settings_service import BackupSettingsError

logger = logging.getLogger(__name__)

# 任务类型 → ARQ 任务函数名（与 arq_app.WorkerSettings.functions 对齐）
TASK_TYPE_TO_FUNC: dict[str, str] = {
    'full': 'auto_daily_backup_task',
    'integrity_check': 'backup_integrity_check_task',
    'cleanup': 'backup_cleanup_task',
    # P1-4: 灾备演练月度例行化（迁移 037 种子 '30 3 1 * *'）
    'disaster_recovery_test': 'disaster_recovery_test_task',
}
VALID_TASK_TYPES = tuple(TASK_TYPE_TO_FUNC)

# 删除守卫：这两类任务**整类**不许从界面删除（不论还剩几条、是否已禁用）。
# 背景：2026-10-12 与 2026-10-16 两次实测，生产 backup_schedule 都只剩 2 行
# （full + cleanup）——完整性巡检 integrity_check 与月度灾备演练
# disaster_recovery_test 都不在。删除路径只有 UI 的 DELETE /backup/schedule/{id}，
# 无任何保护，误删后无人告警，备份到底能不能还原只能靠人想起来手工跑。
# schedule_delete_guard_test 锁死此行为。
GUARDED_TASK_TYPES = ('integrity_check', 'disaster_recovery_test')

# 调度任务卡在 running 超过该时长即视为「未执行」，允许补跑（见 due_schedules）。
# 背景：last_run_at 在**入队时**写入，终态靠 ARQ 回调回写；任务执行中 worker 被
# 服务重启杀死时回调永远不会来，状态卡 running 且窗口被误判为已消费。
# 阈值须大于最慢任务的正常时长（并发双跑由任务函数内部 advisory lock 兜底）；
# 当前全量备份约 5 秒量级，2 小时已留足增长余量。
STALE_RUNNING_AFTER = timedelta(hours=2)

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
                # 当前小时无匹配分钟 → 继续看**当天更早**的小时，不要 break。
                # 原先 break 会放弃当天更早的命中、转算前一天：`30 6,18 * * *` 在 18:15
                # 会算成"昨天 18:30"而非"今天 06:30" → due_schedules 可能漏掉本应补跑的窗口。
                continue
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


async def _assert_hourly_single_hit(cron_expr: str) -> None:
    """B2-02（2026-10-24 审计）：拒绝同一小时内多次命中的 cron。

    调度侧的幂等键是小时粒度（poller mark 与 ARQ _job_id 均为 %Y%m%d%H），
    配置 ``0,30 * * * *`` 这类亚小时 cron 时第二次触发会被静默丢弃——频率
    意图悄悄减半。入口直接拒绝，防患于然。
    """
    spec = parse_cron(cron_expr)
    if spec is None:
        return  # 非法表达式由调用方另行报错
    minutes = spec[0]  # 分钟字段取值集合；None = *（每分钟，同样多次命中）
    minute_hits = len(minutes) if minutes is not None else 60
    if minute_hits > 1:
        shown = sorted(minutes) if minutes is not None else '*'
        raise BackupSettingsError(
            f'cron {cron_expr!r} 在同一小时内多次触发（分钟字段 {shown}）；'
            f'调度幂等键为小时粒度，多出的触发会被静默丢弃。'
            f'请改为每小时单次，或拆成多个 schedule。'
        )


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
    _assert_hourly_single_hit(cron_expr)  # B2-02
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
        _assert_hourly_single_hit(cron_expr)  # B2-02
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
    if await _is_irreplaceable(db, row):
        logger.error(
            '拒绝删除备份调度 %s(name=%s, task_type=%s)：该任务是备份可用性/灾备能力的'
            '唯一自动保障。历史上生产曾因此丢失自动巡检与灾备演练，只能靠人想起来手工跑'
            '（见迁移 056 的漂移修复记录）',
            row.id, row.name, row.task_type,
        )
        raise BackupSettingsError(
            f'"{row.name}"（{row.task_type}）不允许删除：它是「备份是否真能还原」的'
            '自动保障，误删后无人告警。校验与演练停用后仍会留档可随时恢复，'
            '确需删除请联系管理员。'
        )
    await db.delete(row)
    await db.flush()
    return True


async def _is_irreplaceable(db: AsyncSession, row: BackupSchedule) -> bool:
    """该行是否属于「删了就失去自动保障」的不可替代调度。

    口径按 **task_type**（而非 name）：name 是用户可改字段，按它匹配会被改名绕过
    （迁移 057 正是为此才把匹配键从 name 换成 task_type）。

    整类禁止删除，不采用「留一条就行」的宽松口径：这两类任务的意义是「校验备份
    是否真能还原」，而不是「某条备份计划」。宽松口径下运维把 5 条巡检删到剩 1 条
    就再也删不动，而残留那条还可能 cron 写错永不触发 —— 问题依旧存在且更难发现。
    行数多少不改变「这类任务必须有人自动跑」的事实，故不看其他行。
    """
    return row.task_type in GUARDED_TASK_TYPES


async def due_schedules(db: AsyncSession, now: datetime) -> list[BackupSchedule]:
    """返回 enabled 且「存在已过期未执行的 cron 窗口」的调度。

    判定：最近一次（<= now）命中 cron 的时刻 last_due 已产生，
    且该调度未在 last_due 之后执行过 → 触发（补跑错过的窗口）。
    与旧「当前分钟精确匹配」不同：worker 重启/采样错位错过窗口后，
    后续任意 poller 采样都会补跑，避免任务永久丢失。

    「未执行过」以 last_run_at 为准 —— 它在**入队时**就写入，终态由 ARQ 回调
    回写（core/schedule_status.py）。若 worker 在任务执行中被服务重启/崩溃杀死，
    回调永远不会执行，调度卡在 running 且窗口被误判为已消费；因此卡在
    'running' 超过 STALE_RUNNING_AFTER 的调度视为未执行并放行补跑
    （poller 重新入队时会刷新 last_run_at/last_status）。
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
            # 窗口已入队 → 正常不补跑。仅当卡在 'running' 超过阈值（任务疑似
            # 被杀死、终态回写不会再来）才视为未执行放行；'failed'/'success'
            # 是真实终态，不补跑，避免失败任务被 poller 每 5 分钟反复重试。
            if not (row.last_status == STATUS_RUNNING and now - last_run >= STALE_RUNNING_AFTER):
                continue
            logger.warning(
                '调度 %s(%s) 卡在 running 超过 %s，疑似被 worker 重启杀死，本次采样视为未执行并补跑',
                row.id, row.name, STALE_RUNNING_AFTER,
            )
        out.append(row)
    return out
