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
2. **归档先行**：该月先导出 ``audit_log_<YYYYMM>.jsonl.gz``（分批读 + 原子写
   + fsync），**归档成功且覆盖被删范围才删除**（见 3）。
3. **删除范围由归档覆盖决定，而非时间窗**：导出时记录本次归档的 ``max_id``，
   删除谓词带上 ``id <= max_id``——「删的行 ⊆ 归档过的行」由构造保证，不再
   依赖「先导出后删除」这一时序假设。复用既有归档时重新读回文件得到
   (行数, max_id) 并校验剩余行是其子集（``rows >= remaining`` 且
   ``max(remaining_id) <= max_id``），任何不满足都中止该月并留痕。
4. **分批删除**：pkey 游标分批（每批 ≤5000），避免长事务与锁放大；
   audit_log 无二级索引（106 治理后仅 pkey），游标走 pkey 顺序扫描。
5. **统计修复**：有删除时任务末尾 ``ANALYZE audit_log``（实测统计信息
   曾滞后到 n_live_tup=1693 vs 实际 26 万）。
6. **运维留痕**：状态文件 ``logs/audit_retention_state.json``（ARQ worker
   写 / API health 读的同机共享通道，与 prod_runner.json 同模式）记录
   last_success_at / 各月归档 sha256 与 max_id / 删除行数——证明是策略性
   滚动清理而非人为删证（等保检查要点）。
7. **失败可见**：距上次成功 >7 天、或 ``pending_errors`` 非空、或配置低于
   法定下限，/api/health 的 audit_retention 块 ok=false 且 status=degraded
   （沿用 F-BE-CORE-05 备份链停摆先例：仍 200，不触发监督器重启）。
   任务体无论成败都写状态文件（``last_attempt_at``），否则「次次失败」会
   被误读成「从未运行」而永久宽限。
8. **单实例**：会话级 advisory lock（不是事务级——本任务每批 commit，
   事务级锁会随首批提交释放）保证 cron 与日级补跑不会同时处理同一月。

时区口径
----
**全部显式 UTC**。注意 PG 的 ``date_trunc``/``to_char`` 对 ``timestamptz``
按**会话时区**折算（本机实测 ``SHOW TimeZone`` = ``Asia/Shanghai``，与 UTC
口径分桶相差约 8 小时的行数），所以月键一律写成
``to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM')``，不依赖会话默认值；
导出口径与删除窗口也用 aware UTC 常量，三者严格同口径。

事务边界：``run_retention_once(db)`` 在调用方会话上工作、每批删除后
commit（分批的意义就是小事务）；ARQ 入口 ``audit_retention_task`` 开会话、
持锁并负责最终 commit（与 numbering_audit_task 同模式）。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import sys
import zlib
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import require_async_session_local

logger = logging.getLogger(__name__)

# 每批删除/导出行数上限（小事务，防锁放大；导出分批避免整月物化进内存）
DELETE_BATCH_ROWS = 5000
EXPORT_BATCH_ROWS = 5000
# 状态文件（worker 写 / health 读）：距上次成功超过该天数 → health degraded
STALE_DAYS = 7
# 法定最低保留月数（网安法第 21 条：网络日志留存不少于六个月）。低于此值
# 视为误配：拒绝执行并让健康端点报 misconfigured，而不是悄悄按错值删数据。
MIN_RETENTION_MONTHS = 6
# 会话级 advisory lock 键（任意固定值；ASCII 'ARET' 便于在 pg_locks 里认出来）
RETENTION_LOCK_KEY = 0x4152455400000001
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# 状态文件锚定项目根而非 CWD：worker 与 API 的启动方式一旦不同（计划任务/
# 手工 arq），CWD 相对路径会静默读到另一个文件 → not_yet_run 恒绿。
STATE_PATH = _PROJECT_ROOT / 'logs' / 'audit_retention_state.json'

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
    'FROM audit_log WHERE created_at >= :ms AND created_at < :me AND id > :cursor '
    'ORDER BY id LIMIT :batch'
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


async def window_stats(
    db: AsyncSession, month_start: datetime, month_end: datetime,
) -> tuple[int, int]:
    """某时间窗内的 (行数, 最大 id)；空窗返回 (0, 0)。"""
    row = (await db.execute(text(
        'SELECT count(*), coalesce(max(id), 0) FROM audit_log '
        'WHERE created_at >= :ms AND created_at < :me'
    ), {'ms': month_start, 'me': month_end})).one()
    return int(row[0]), int(row[1])


async def compute_retention_plan(db: AsyncSession, now: datetime | None = None) -> list[dict]:
    """计算本轮要处理的完整过期月（不写库；测试直接调用）。

    只收「月结束 ≤ cutoff」的整月——月中部分过期的保留整月（安全方向）。
    月键显式按 UTC 折算，与会话时区无关（本机会话时区是 Asia/Shanghai）。
    """
    if settings.AUDIT_RETENTION_MONTHS <= 0:
        return []
    if settings.AUDIT_RETENTION_MONTHS < MIN_RETENTION_MONTHS:
        logger.error(
            'AUDIT_RETENTION_MONTHS=%d 低于法定下限 %d 个月，本轮拒绝执行'
            '（误配不能变成静默的过度删除）',
            settings.AUDIT_RETENTION_MONTHS, MIN_RETENTION_MONTHS)
        return []
    cutoff = retention_cutoff(now)
    rows = await db.execute(text(
        "SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM') AS m, count(*) "
        "FROM audit_log WHERE created_at < :cutoff GROUP BY 1 ORDER BY 1"
    ), {'cutoff': cutoff})
    plans = []
    for month_key, row_count in rows.all():
        _start, month_end = _month_bounds(month_key)
        if month_end > cutoff:
            continue  # 月未完整过期：留整月
        plans.append({'month': month_key, 'rows': int(row_count)})
    return plans


def archive_stats(path: Path) -> dict:
    """校验并读回既有归档：{path, rows, max_id, sha256}。

    读到底即触发 gzip 的 CRC 校验——截断/损坏的归档在这里就抛 OSError，
    而不是被「文件存在」当成完整产物继续往下删源数据。
    逐行流式处理，不把整月装进内存。同步实现：仅在复用既有归档时调用，
    一个月一次、百毫秒级，不值得为它引入线程池。
    """
    rows = 0
    max_id = 0
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as gz:
            for line in gz:
                if not line.strip():
                    continue
                rows += 1
                row_id = json.loads(line).get('id')
                if isinstance(row_id, int) and row_id > max_id:
                    max_id = row_id
    except (zlib.error, EOFError) as exc:
        # 完整性失败与「文件读不了」是同一类数据条件，统一成 OSError：
        # zlib.error / EOFError 都不继承 OSError，不归一就会穿透整轮任务
        # （所有月份一起失败），而不是只跳过坏掉的这个月。
        raise OSError(f'归档损坏或截断: {path}（{exc}）') from exc
    return {'path': str(path), 'rows': rows, 'max_id': max_id, 'sha256': _sha256_of(path)}


async def _export_month_jsonl(
    db: AsyncSession, month_key: str, month_start: datetime, month_end: datetime,
    archive_dir: Path,
) -> dict:
    """导出一个整月到 jsonl.gz（分批读 + 原子写 + fsync）。

    返回 {path, rows, max_id, sha256, existed}；existed=True 表示复用既有
    归档（rows/max_id 从文件读回，不是计划值）。
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    final_path = archive_dir / f'audit_log_{month_key.replace("-", "")}.jsonl.gz'
    if final_path.exists():
        return {**archive_stats(final_path), 'existed': True}

    tmp_path = final_path.parent / (final_path.name + '.tmp')
    count = 0
    max_id = 0
    cursor = -1
    with open(tmp_path, 'wb') as raw:
        # gzip 必须嵌套在 raw 里关闭：GzipFile 关闭时才写 CRC 尾部，若在它
        # 关闭前 fsync，落盘的是没有尾部的半截归档，而下一轮会凭「文件存在」
        # 删掉源数据。
        with gzip.GzipFile(fileobj=raw, mode='wb') as gz:
            while True:
                rows = (await db.execute(text(_EXPORT_SELECT), {
                    'ms': month_start, 'me': month_end,
                    'cursor': cursor, 'batch': EXPORT_BATCH_ROWS,
                })).all()
                if not rows:
                    break
                for row in rows:
                    gz.write(json.dumps(
                        {c: _jsonable(v) for c, v in zip(_AUDIT_COLUMNS, row, strict=True)},
                        ensure_ascii=False, separators=(',', ':')).encode() + b'\n')
                    count += 1
                cursor = rows[-1][0]
                max_id = cursor
        # 尾部已写全，再落盘：先 fsync 后 rename，避免掉电后留下
        # 「正式文件存在但内容截断」的证据黑洞。
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(tmp_path, final_path)
    return {'path': str(final_path), 'rows': count, 'max_id': max_id,
            'sha256': _sha256_of(final_path), 'existed': False}


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
    db: AsyncSession, month_start: datetime, month_end: datetime, max_id: int,
    batch: int = DELETE_BATCH_ROWS,
) -> int:
    """pkey 游标分批删除一个整月，每批 commit（小事务）。返回总删除行数。

    ``id <= max_id``：只删归档覆盖到的行。导出之后才落进该窗口的行（补录/
    回放/旧备份恢复）不会被删——下一轮会因为「归档不完整」被显式报错。
    """
    total = 0
    cursor = -1
    while True:
        ids = (await db.execute(text(
            'SELECT id FROM audit_log '
            'WHERE created_at >= :ms AND created_at < :me AND id > :cursor AND id <= :max_id '
            'ORDER BY id LIMIT :batch'
        ), {'ms': month_start, 'me': month_end, 'cursor': cursor,
            'max_id': max_id, 'batch': batch})).scalars().all()
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
    tmp = state_path.parent / (state_path.name + '.tmp')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, state_path)


def write_failure_state(
    exc: BaseException | None, state_path: Path | None = None,
) -> None:
    """任务整体失败时也留痕：写 last_attempt_at + last_error，保留既有账本。

    没有这一步，「每天在 compute_retention_plan 上抛错」会让状态文件永不生成，
    健康端点永远停在 not_yet_run 宽限而恒绿——与 F-BE-CORE-05 同型。
    """
    state_path = state_path or STATE_PATH
    prev = read_retention_state(state_path) or {}
    prev.update({
        'last_attempt_at': datetime.now(UTC).isoformat(),
        'last_error': f'{type(exc).__name__}: {exc}' if exc is not None else 'aborted',
    })
    prev.setdefault('archive_files', {})
    try:
        _write_state(prev, state_path)
    except OSError:
        logger.exception('audit_log 保留治理: 失败状态写入失败（%s）', state_path)


async def _try_lock(db: AsyncSession) -> bool:
    """会话级 advisory lock：cron 与日级补跑不会同时处理同一批月份。"""
    return bool((await db.execute(
        text('SELECT pg_try_advisory_lock(:k)'), {'k': RETENTION_LOCK_KEY})).scalar())


async def _unlock(db: AsyncSession) -> None:
    """释放会话锁。必须显式释放：连接回池后会话仍在，锁不会自己消失。"""
    await db.execute(text('SELECT pg_advisory_unlock(:k)'), {'k': RETENTION_LOCK_KEY})


async def _process_month(db: AsyncSession, plan: dict, archive_dir: Path) -> dict:
    """处理单个整月：归档 →（覆盖校验）→ 分批删除。

    返回 {entry, error, deleted}：entry 进 report['months']，error 非 None 表示
    该月被跳过（error 同时进 report['errors']），deleted 为该月实删行数。
    本函数是「只删归档覆盖到的行」这条不变式的唯一落点——所有提前返回都在
    ``_delete_month_batched`` 之前，且删除动作带 ``id <= archive max_id`` 上界。
    """
    month_key = plan['month']
    month_start, month_end = _month_bounds(month_key)
    try:
        archive = await _export_month_jsonl(db, month_key, month_start, month_end, archive_dir)
        if archive['existed']:
            # 复用既有归档：不能假定「文件存在 = 内容完整」。读回文件（上一步
            # 已校验 CRC 并取得行数/max_id），再确认待删剩余行是它的子集。
            remaining, max_remaining = await window_stats(db, month_start, month_end)
            if archive['rows'] < remaining or max_remaining > archive['max_id']:
                logger.error(
                    'audit_log 保留治理: %s 归档不完整（归档 %d 行/max_id=%d，'
                    '库内剩余 %d 行/max_id=%d），跳过删除（人工核查）',
                    month_key, archive['rows'], archive['max_id'],
                    remaining, max_remaining)
                return _skip(month_key, plan,
                             {'month': month_key, 'error': 'archive_incomplete',
                              'archived_rows': archive['rows'],
                              'archive_max_id': archive['max_id'],
                              'remaining_rows': remaining,
                              'remaining_max_id': max_remaining})
        elif archive['rows'] != plan['rows']:
            # 本次导出的行数与计划不符：导出窗口内有并发写入（补录/回放）时
            # 会命中——保守中止该月，不删除
            logger.error(
                'audit_log 保留治理: %s 归档行数 %d != 计划 %d，跳过删除（人工核查）',
                month_key, archive['rows'], plan['rows'])
            return _skip(month_key, plan,
                         {'month': month_key, 'error': 'archive_row_mismatch',
                          'planned_rows': plan['rows'], 'archived_rows': archive['rows']})

        deleted = await _delete_month_batched(
            db, month_start, month_end, max_id=archive['max_id'])
    except (OSError, SQLAlchemyError) as exc:
        # 只兜「已知可恢复」的两类：文件系统（OSError：mkdir / gzip 写 / fsync /
        # os.replace / 归档 CRC 校验失败）与数据库（SQLAlchemyError：查询、
        # 删除、锁等待超时）。其它异常（编程错误）照旧上抛——那类 bug 必须响，
        # 不能被按月吞成一条 pending_error。
        #
        # 该月不删（若已删了前几批，剩余行仍在归档覆盖范围内，下一轮安全续删）。
        logger.error('audit_log 保留治理: %s 归档/删除失败，跳过该月: %s', month_key, exc)
        return _skip(month_key, plan,
                     {'month': month_key, 'error': f'{type(exc).__name__}: {exc}'})

    if archive['existed']:
        # rows=-1 之类的哨兵不存在了（复用也读回真实行数），如实记录
        logger.info(
            'audit_log 保留治理: %s 复用归档(%d 行, max_id=%d) 删除 %d 行',
            month_key, archive['rows'], archive['max_id'], deleted)
    else:
        logger.info(
            'audit_log 保留治理: %s 归档 %d 行(max_id=%d, sha256=%s…) 删除 %d 行',
            month_key, archive['rows'], archive['max_id'], archive['sha256'][:12], deleted)
    return {
        'entry': {'month': month_key, 'rows': plan['rows'],
                  'archive_rows': archive['rows'], 'archive_max_id': archive['max_id'],
                  'archived': True, 'archive_path': archive['path'],
                  'sha256': archive['sha256'], 'deleted': deleted},
        'error': None,
        'deleted': deleted,
    }


def _skip(month_key: str, plan: dict, error: dict) -> dict:
    """被跳过月份的返回结构（entry + error + deleted=0）。"""
    return {
        'entry': {'month': month_key, 'rows': plan['rows'], 'archived': False, 'deleted': 0},
        'error': error,
        'deleted': 0,
    }


async def run_retention_once(
    db: AsyncSession, now: datetime | None = None,
    archive_dir: Path | None = None, state_path: Path | None = None,
) -> dict:
    """执行一轮保留治理（调用方会话；每批删除后 commit）。

    返回 report：{ran_at, retention_months, months: [{month, rows, archive_rows,
    archive_max_id, archived, sha256, deleted, error?}], deleted_total, analyzed,
    errors: [{month, error}]}。months 为空（无需处理或禁用）也写状态文件
    ——「任务活着」的证据本身。errors 非空表示有月份被跳过，会写进状态文件的
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

    prev = read_retention_state(state_path)
    if prev is None and state_path.exists():
        # 状态文件存在却读不出来：先改名留现场（等保取证要的是这份账本），
        # 再重建。旧实现直接 or {} 会把 archive_files / deleted_rows_total
        # 静默清零——「自愈」得毫无痕迹。
        corrupt = state_path.parent / f'{state_path.name}.corrupt-{now:%Y%m%d%H%M%S}'
        try:
            os.replace(state_path, corrupt)
            logger.error('audit_log 保留治理: 状态文件损坏，已另存为 %s', corrupt)
        except OSError:
            logger.exception('audit_log 保留治理: 状态文件损坏且无法另存')
        report['errors'].append({'month': None, 'error': 'state_corrupt_recovered'})
        prev = None
    prev = prev or {}
    archives = dict(prev.get('archive_files') or {})
    for m in report['months']:
        if m.get('archive_path'):
            archives[m['month']] = {
                'path': m['archive_path'], 'rows': m['archive_rows'],
                'max_id': m['archive_max_id'], 'sha256': m['sha256'],
            }
    state = {
        'last_success_at': now.isoformat(),
        'last_attempt_at': now.isoformat(),
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
    """ARQ cron 入口（03:00，日级补跑机制覆盖）：持锁开会话执行一轮。"""
    session_factory = require_async_session_local()
    report: dict | None = None
    locked = False
    async with session_factory() as db:
        try:
            locked = await _try_lock(db)
            if not locked:
                # 另一实例在跑（cron 与日级补跑重叠）：让它写状态，本实例干净退出
                logger.warning('audit_log 保留治理: 已有实例持锁，跳过本轮')
                report = {'skipped': 'lock_busy'}
                return report
            report = await run_retention_once(db)
            await db.commit()
        finally:
            if locked:
                # 释放失败不能让原始异常被掩盖（会话已坏时 unlock 也可能抛）
                with suppress(SQLAlchemyError, OSError):
                    await _unlock(db)
            if report is None:
                # 任何异常（含 CancelledError）走到这里：先留痕再让异常继续上抛。
                # 没有这一步，「天天失败」会一直显示成「从未运行过」而免于降级。
                write_failure_state(sys.exc_info()[1])
    logger.info(
        'audit_log 保留治理完成: months=%d deleted=%d analyzed=%s',
        len(report['months']), report['deleted_total'], report['analyzed'],
    )
    return report


def audit_retention_signal() -> dict:
    """健康信号（health 端点调用；绝不抛）。

    ok=False 的三种情形（任一即降级）：
    - **配置低于法定下限**（0 < months < 6）：误配必须可见，否则一次运行就能
      把留存压到法定线以下；
    - **停摆**：距上次成功 > STALE_DAYS（沿用备份链停摆先例）；
    - **有待处理错误**：``pending_errors`` 非空（某月归档失败会被逐日跳过，
      若只看 staleness，``last_success_at`` 照常刷新会让积压永远不可见）。
    ok=True 的情形：任务被禁用（months ≤ 0，明确的人工选择）；状态文件不存在
    （部署首日宽限——注意任务体失败时也会写 ``last_attempt_at``，所以「文件
    持续不存在」只可能是从未部署过该任务，不是「天天失败」）。

    状态文件存在但读不出来（JSON 坏 / 缺 last_success_at / 时间戳不可解析）
    → ok=False：这与「从未运行」症状相同但性质是异常，且不会自愈。
    """
    months = settings.AUDIT_RETENTION_MONTHS
    if months <= 0:
        return {'ok': True, 'disabled': True, 'retention_months': 0}
    if months < MIN_RETENTION_MONTHS:
        return {'ok': False, 'misconfigured': True, 'retention_months': months,
                'min_retention_months': MIN_RETENTION_MONTHS,
                'note': 'below_statutory_minimum'}
    state = read_retention_state()
    if state is None or not state.get('last_success_at'):
        # 区分「文件不存在」（宽限）与「文件存在但无成功记录/读不出」（异常）
        if STATE_PATH.exists():
            return {'ok': False, 'last_success_at': None, 'note': 'state_unreadable',
                    'last_error': (state or {}).get('last_error'),
                    'state_path': str(STATE_PATH)}
        return {'ok': True, 'last_success_at': None, 'note': 'not_yet_run'}
    try:
        last = datetime.fromisoformat(state['last_success_at'])
    except (TypeError, ValueError):
        return {'ok': False, 'last_success_at': None, 'note': 'state_unreadable',
                'state_path': str(STATE_PATH)}
    if last.tzinfo is None:
        # 手改/旧格式写入的 naive 时间戳：按 UTC 解释，而不是让
        # datetime.now(UTC) - last 抛 TypeError 逃出「绝不抛」的承诺
        last = last.replace(tzinfo=UTC)
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
