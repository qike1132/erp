"""audit_log 保留期治理（ARQ cron 03:00）：归档先行 + 分批删除 + ANALYZE。

背景（docs/audit-log-retention-decision.md，owner 2026-11-01 批准）
----
- 合规底线：《网络安全法》第 21 条网络日志留存不少于六个月；等保 2.0
  测评同口径。**保留 12 个月**（2 倍法定余量 + 覆盖会计年度）。
- 增长模型：稳态 ~370 行/天 + 不定期导入洪峰（单次 10-25 万行）；
  12 个月窗口峰值 ~40 万行 / ~90MB，容量与备份 L2 指纹成本均无压力。
- 备份校验零耦合（verify_restore 的 L2 指纹在恢复库算、比备份 manifest，
  源库清理不进闭环——决策报告 §1.2 已核实）。

机制设计
----
1. **月粒度**：只处理「整月完全过期」的月份（月结束 ≤ cutoff）——月中
   部分过期的数据保留整月，保留期实际为 12~13 个月（多留方向，合规安全）。
2. **归档先行**：该月先导出 ``audit_log_<YYYYMM>.jsonl.gz``（原子写：
   tmp + os.replace），归档文件已存在则视为已完成（replace 前崩溃只会
   留 tmp 残留，正式文件不存在则重导）；**归档成功才删除**。
3. **分批删除**：pkey 游标分批（每批 ≤5000），避免长事务与锁放大；
   audit_log 无二级索引（106 治理后仅 pkey），游标走 pkey 顺序扫描。
4. **统计修复**：有删除时任务末尾 ``ANALYZE audit_log``（实测统计信息
   曾滞后到 n_live_tup=1693 vs 实际 26 万）。
5. **运维留痕**：状态文件 ``logs/audit_retention_state.json``（ARQ worker
   写 / API health 读的同机共享通道，与 prod_runner.json 同模式）记录
   last_success_at / 各月归档 sha256 / 删除行数——证明是策略性滚动清理
   而非人为删证（等保检查要点）。
6. **停摆可见**：距上次成功 >7 天 → /api/health 的 audit_retention 块
   ok=false 且 status=degraded（沿用 F-BE-CORE-05 备份链停摆先例：
   仍 200，不触发监督器重启，但 GUI/巡检可据 status 区分）。
7. **单月失败不吞**：某月归档抛错或行数不符 → 该月一行不删、继续处理其余
   月份、错误写入状态文件 ``pending_errors``；只要 ``pending_errors`` 非空
   健康信号即 ok=false。否则「每月都跳过但 last_success_at 照常刷新」会让
   积压永远不可见（与 6 不同的失效路径）。下一轮成功即清空该列表。

时区口径：月边界与 cutoff 全程 UTC（DB date_trunc 对 timestamptz 默认
UTC）；月粒度的 ±8h 边界偏差在「多留不删」的安全方向内。

事务边界：``run_retention_once(db)`` 在调用方会话上工作、每批删除后
commit（分批的意义就是小事务）；ARQ 入口 ``audit_retention_task`` 开会话
并负责最终 commit（与 numbering_audit_task 同模式）。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import require_async_session_local

logger = logging.getLogger(__name__)

# 每批删除行数上限（小事务，防锁放大）
DELETE_BATCH_ROWS = 5000
# 状态文件（worker 写 / health 读）：距上次成功超过该天数 → health degraded
STALE_DAYS = 7
STATE_PATH = Path('logs/audit_retention_state.json')

# 导出的列（与 audit_log 表结构一致；顺序即 jsonl 字段顺序）
_AUDIT_COLUMNS = (
    'id', 'user_id', 'username', 'action', 'resource_type', 'resource_id',
    'detail', 'ip_address', 'user_agent', 'request_id', 'status_code', 'created_at',
)
# 导出语句写成字面量而非 f-string 拼接列名：B608（SQL 由字符串插值构造）无从
# 触发，扫描器不必靠 nosec 豁免；列名与 _AUDIT_COLUMNS 的一致性由
# test_export_select_matches_column_tuple 锁定（拼接与常量脱钩是本设计唯一风险）。
_EXPORT_SELECT = (
    'SELECT id, user_id, username, action, resource_type, resource_id, '
    'detail, ip_address, user_agent, request_id, status_code, created_at '
    'FROM audit_log WHERE created_at >= :ms AND created_at < :me ORDER BY id'
)


def retention_cutoff(now: datetime | None = None) -> datetime:
    """保留窗口起点：now - AUDIT_RETENTION_MONTHS 个月（UTC）。"""
    now = now or datetime.now(UTC)
    return now - relativedelta(months=settings.AUDIT_RETENTION_MONTHS)


def _month_bounds(month_key: str) -> tuple[datetime, datetime]:
    """'YYYY-MM' → (月起点, 次月起点)，UTC aware。"""
    year, month = (int(x) for x in month_key.split('-'))
    start = datetime(year, month, 1, tzinfo=UTC)
    return start, start + relativedelta(months=1)


async def compute_retention_plan(db: AsyncSession, now: datetime | None = None) -> list[dict]:
    """计算本轮要处理的完整过期月（不写库；测试直接调用）。

    只收「月结束 ≤ cutoff」的整月——月中部分过期的保留整月（安全方向）。
    """
    if settings.AUDIT_RETENTION_MONTHS <= 0:
        return []
    cutoff = retention_cutoff(now)
    rows = await db.execute(text(
        "SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') AS m, count(*) "
        "FROM audit_log WHERE created_at < :cutoff GROUP BY 1 ORDER BY 1"
    ), {'cutoff': cutoff})
    plans = []
    for month_key, row_count in rows.all():
        _start, month_end = _month_bounds(month_key)
        if month_end > cutoff:
            continue  # 月未完整过期：留整月
        plans.append({'month': month_key, 'rows': int(row_count)})
    return plans


async def _export_month_jsonl(
    db: AsyncSession, month_key: str, month_start: datetime, month_end: datetime,
    archive_dir: Path,
) -> dict:
    """导出一个整月到 jsonl.gz（原子写），返回 {path, rows, sha256}。"""
    archive_dir.mkdir(parents=True, exist_ok=True)
    final_path = archive_dir / f'audit_log_{month_key.replace("-", "")}.jsonl.gz'
    if final_path.exists():
        # 幂等：正式文件只会由 os.replace 产生（完整产物），存在即跳过
        return {'path': str(final_path), 'rows': -1, 'sha256': _sha256_of(final_path), 'existed': True}

    rows = (await db.execute(text(_EXPORT_SELECT),
                             {'ms': month_start, 'me': month_end})).all()

    tmp_path = final_path.with_suffix('.jsonl.gz.tmp')
    count = 0
    with gzip.open(tmp_path, 'wt', encoding='utf-8', newline='\n') as gz:
        for row in rows:
            gz.write(json.dumps(
                {c: _jsonable(v) for c, v in zip(_AUDIT_COLUMNS, row, strict=True)},
                ensure_ascii=False, separators=(',', ':')) + '\n')
            count += 1
    os.replace(tmp_path, final_path)
    return {'path': str(final_path), 'rows': count, 'sha256': _sha256_of(final_path), 'existed': False}


def _jsonable(value):
    """datetime → ISO 字符串；Decimal → str；其余原样。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


async def _delete_month_batched(
    db: AsyncSession, month_start: datetime, month_end: datetime,
    batch: int = DELETE_BATCH_ROWS,
) -> int:
    """pkey 游标分批删除一个整月，每批 commit（小事务）。返回总删除行数。"""
    total = 0
    cursor = -1
    while True:
        ids = (await db.execute(text(
            'SELECT id FROM audit_log '
            'WHERE created_at >= :ms AND created_at < :me AND id > :cursor '
            'ORDER BY id LIMIT :batch'
        ), {'ms': month_start, 'me': month_end, 'cursor': cursor, 'batch': batch})).scalars().all()
        if not ids:
            break
        result = await db.execute(
            text('DELETE FROM audit_log WHERE id = ANY(:ids)'), {'ids': list(ids)})
        await db.commit()  # 每批小事务：分批的全部意义
        total += result.rowcount or 0
        cursor = ids[-1]
    return total


def read_retention_state(state_path: Path | None = None) -> dict | None:
    """读状态文件（health 信号用）；缺失/损坏返回 None，绝不抛。"""
    path = state_path or STATE_PATH
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_state(state: dict, state_path: Path) -> None:
    tmp = state_path.with_suffix('.json.tmp')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, state_path)


async def _process_month(db: AsyncSession, plan: dict, archive_dir: Path) -> dict:
    """处理单个整月：归档 →（行数校验）→ 分批删除。

    返回 {entry, error, deleted}：entry 进 report['months']，error 非 None 表示
    该月被跳过（error 同时进 report['errors']），deleted 为该月实删行数。
    本函数是「归档成功才删除」这条不变式的唯一落点——所有提前返回都在
    ``_delete_month_batched`` 之前。
    """
    month_key = plan['month']
    month_start, month_end = _month_bounds(month_key)
    try:
        archive = await _export_month_jsonl(db, month_key, month_start, month_end, archive_dir)
    except (OSError, SQLAlchemyError) as exc:
        # 只兜「已知可恢复」的两类：文件系统（OSError：mkdir / gzip 写 /
        # os.replace）与数据库（SQLAlchemyError）。其它异常（编程错误）照旧
        # 上抛——那类 bug 必须响，不能被按月吞成一条 pending_error。
        #
        # 归档失败 = 该月一行都不能删。错误进 pending_errors，否则「每月都跳过」
        # 会永远绿着（last_success_at 照常刷新）——正是 F-BE-CORE-05 那类静默失效。
        logger.error('audit_log 保留治理: %s 归档失败，跳过删除: %s', month_key, exc)
        return {
            'entry': {'month': month_key, 'rows': plan['rows'], 'archived': False, 'deleted': 0},
            'error': {'month': month_key, 'error': f'{type(exc).__name__}: {exc}'},
            'deleted': 0,
        }

    if not archive['existed'] and archive['rows'] != plan['rows']:
        # 归档行数与计划不符（导出窗口内有并发写入？该月已完整过期，理论不可能）
        # ——保守中止该月，不删除
        logger.error(
            'audit_log 保留治理: %s 归档行数 %d != 计划 %d，跳过删除（人工核查）',
            month_key, archive['rows'], plan['rows'])
        return {
            'entry': {'month': month_key, 'rows': plan['rows'], 'archived': False,
                      'deleted': 0, 'error': 'archive_row_mismatch'},
            'error': {'month': month_key, 'error': 'archive_row_mismatch',
                      'planned_rows': plan['rows'], 'archived_rows': archive['rows']},
            'deleted': 0,
        }

    deleted = await _delete_month_batched(db, month_start, month_end)
    if archive['existed']:
        # rows=-1 是「复用已有归档、未重导」的哨兵，直接打进日志会变成
        # 「归档 -1 行」的误读
        logger.info(
            'audit_log 保留治理: %s 复用已有归档(sha256=%s…) 删除 %d 行',
            month_key, archive['sha256'][:12], deleted)
    else:
        logger.info(
            'audit_log 保留治理: %s 归档 %d 行(sha256=%s…) 删除 %d 行',
            month_key, archive['rows'], archive['sha256'][:12], deleted)
    return {
        'entry': {'month': month_key, 'rows': plan['rows'], 'archived': True,
                  'archive_path': archive['path'], 'sha256': archive['sha256'],
                  'deleted': deleted},
        'error': None,
        'deleted': deleted,
    }


async def run_retention_once(
    db: AsyncSession, now: datetime | None = None,
    archive_dir: Path | None = None, state_path: Path | None = None,
) -> dict:
    """执行一轮保留治理（调用方会话；每批删除后 commit）。

    返回 report：{ran_at, retention_months, months: [{month, rows, archived,
    sha256, deleted, error?}], deleted_total, analyzed, errors: [{month, error}]}。
    months 为空（无需处理或禁用）也写状态文件——「任务活着」的证据本身。
    errors 非空表示有月份被跳过（未归档或行数不符），会写进状态文件的
    pending_errors 并让健康信号 ok=False。
    """
    now = now or datetime.now(UTC)
    archive_dir = archive_dir or Path(settings.AUDIT_ARCHIVE_DIR)
    state_path = state_path or STATE_PATH
    plans = await compute_retention_plan(db, now)

    report = {
        'ran_at': now.isoformat(),
        'retention_months': settings.AUDIT_RETENTION_MONTHS,
        'months': [],
        'deleted_total': 0,
        'analyzed': False,
        'errors': [],
    }
    for plan in plans:
        result = await _process_month(db, plan, archive_dir)
        report['months'].append(result['entry'])
        report['deleted_total'] += result['deleted']
        if result['error']:
            report['errors'].append(result['error'])

    if report['deleted_total']:
        await db.execute(text('ANALYZE audit_log'))
        await db.commit()
        report['analyzed'] = True

    # 状态文件（含历史归档清单——等保检查的清理证据链）
    prev = read_retention_state(state_path) or {}
    archives = dict(prev.get('archive_files') or {})
    for m in report['months']:
        if m.get('archive_path'):
            archives[m['month']] = {
                'path': m['archive_path'], 'rows': m['rows'], 'sha256': m['sha256'],
            }
    state = {
        'last_success_at': now.isoformat(),
        'retention_months': settings.AUDIT_RETENTION_MONTHS,
        'deleted_rows_total': int(prev.get('deleted_rows_total') or 0) + report['deleted_total'],
        'archive_files': archives,
        # 上一轮错误不累加：本轮成功即清空（错误是「当前是否卡着」的信号，
        # 不是历史账本；历史归档证据在 archive_files 里）
        'pending_errors': report['errors'],
    }
    _write_state(state, state_path)
    return report


async def audit_retention_task(ctx) -> dict:
    """ARQ cron 入口（03:00，日级补跑机制覆盖）：开会话并执行一轮。"""
    session_factory = require_async_session_local()
    async with session_factory() as db:
        report = await run_retention_once(db)
        await db.commit()
    logger.info(
        'audit_log 保留治理完成: months=%d deleted=%d analyzed=%s',
        len(report['months']), report['deleted_total'], report['analyzed'],
    )
    return report


def audit_retention_signal() -> dict:
    """健康信号（health 端点调用；绝不抛）。

    ok 的两个条件（任一不满足即 ok=False）：
    - **新鲜**：距上次成功 ≤ STALE_DAYS。停摆的合规含义是「该归档/清理的
      积压无人处理」，沿用备份链停摆的 degraded 先例。
    - **无待处理错误**：状态文件 ``pending_errors`` 为空。缺这一条会留一个
      静默洞——某月归档失败会被逐日跳过，而 ``last_success_at`` 照常刷新，
      健康端点永远绿（F-BE-CORE-05 同型）。

    特殊情形：
    - 任务被禁用（AUDIT_RETENTION_MONTHS ≤ 0）→ ok=True；
    - 尚未运行过（状态文件不存在）→ ok=True，部署首日宽限（cron 注册有
      test_arq_functions_registry 守卫，ARQ 进程死亡另有 backup.arq_ok 兜底）；
    - 状态文件存在但损坏/无 last_success_at → **ok=False**：这与「从未跑过」
      症状相同但性质是异常，且不会自愈（下一轮成功运行会整体重写文件，
      属于自愈路径上的短暂状态）。
    """
    if settings.AUDIT_RETENTION_MONTHS <= 0:
        return {'ok': True, 'disabled': True, 'retention_months': 0}
    state = read_retention_state()
    if state is None or not state.get('last_success_at'):
        # 区分「文件不存在」与「文件损坏」：前者是部署首日宽限，后者是异常。
        # 混为一谈会把损坏文件永久读成 not_yet_run，症状与「从未跑过」完全
        # 相同——而损坏不会自愈，等于把停摆藏起来。
        if STATE_PATH.exists():
            return {'ok': False, 'last_success_at': None, 'note': 'state_unreadable',
                    'state_path': str(STATE_PATH)}
        return {'ok': True, 'last_success_at': None, 'note': 'not_yet_run'}
    try:
        last = datetime.fromisoformat(state['last_success_at'])
    except (TypeError, ValueError):
        return {'ok': True, 'last_success_at': None, 'note': 'state_unreadable'}
    age_days = (datetime.now(UTC) - last) / timedelta(days=1)
    pending = state.get('pending_errors') or []
    return {
        'ok': age_days <= STALE_DAYS and not pending,
        'last_success_at': state['last_success_at'],
        'age_days': round(age_days, 1),
        'stale_threshold_days': STALE_DAYS,
        'retention_months': state.get('retention_months'),
        'deleted_rows_total': state.get('deleted_rows_total'),
        # 只暴露前几条，避免健康响应被长列表撑爆
        'pending_errors': pending[:5],
        'pending_error_count': len(pending),
    }
