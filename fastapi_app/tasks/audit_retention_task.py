"""audit_log 保留期治理（ARQ cron 03:00）：归档先行 + 按归档 id 删除 + ANALYZE。

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
   + fsync）。
3. **删除的对象就是归档里的 id**：导出时收集全部 id，删除按这些 id 分批执行
   （``DELETE ... WHERE id = ANY(:ids)``）。「删的行 ⊆ 归档过的行」因此不是
   被校验出来的，而是**同义反复**——不需要时间窗、不需要 max_id 上界、不需要
   游标算术，也就不存在「导出后新落进行、却被时间窗带走」的缝。
4. **删完复核**：删除后统计该月窗口剩余行数；>0 说明有行从未归档（补录/回放/
   旧备份恢复），记 ``archive_incomplete`` 并让它出现在健康信号里，**绝不删**。
5. **幂等**：正式归档文件存在即不重导（不覆盖证据）；复用时重读文件（gzip 读到
   底即 CRC 校验）重建 id 集合，已删过的 id 自然不再命中，崩溃后可直接续删。
6. **分批**：导出与删除都按批（≤5000），删除每批一次 commit（小事务，避免
   锁放大）；audit_log 经 106 治理后仅剩 pkey。
7. **单实例**：advisory lock 绑在**专用连接**上。会话级锁的生命周期跟 DBAPI
   连接走，而 ``Session.commit()`` 会把连接归还池——把连接握在调用方手里，
   锁才不会「跟着 commit 换连接」。
8. **统计修复**：有删除时 ``ANALYZE audit_log``（实测统计信息曾滞后到
   n_live_tup=1693 vs 实际 26 万）。
9. **运维留痕**：状态文件 ``logs/audit_retention_state.json``（ARQ worker 写 /
   API health 读的同机共享通道，与 prod_runner.json 同模式）记录
   last_success_at / 各月归档 sha256 与行数 / 删除行数——证明是策略性滚动清理
   而非人为删证（等保检查要点）。
10. **失败可见**：距上次成功 >7 天、或 ``pending_errors`` 非空、或配置低于法定
    下限，/api/health 的 audit_retention 块 ok=false 且 status=degraded（沿用
    F-BE-CORE-05 备份链停摆先例：仍 200，不触发监督器重启）。任务体无论成败都
    写状态文件（``last_attempt_at``），否则「次次失败」会被误读成「从未运行」
    而永久宽限。

时区口径
----
**全部显式 UTC**。注意 PG 的 ``date_trunc``/``to_char`` 对 ``timestamptz``
按**会话时区**折算（本机实测 ``SHOW TimeZone`` = ``Asia/Shanghai``，与 UTC
口径分桶相差约 8 小时的行数），所以月键一律写成
``to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM')``，不依赖会话默认值；
导出口径与删除窗口也用 aware UTC 常量，三者严格同口径。

事务边界：``run_retention_once(db)`` 在调用方会话上工作、每批删除后 commit
（分批的意义就是小事务）；ARQ 入口 ``audit_retention_task`` 提供专用连接与
advisory lock，并用 bind 到该连接的会话执行（commit 不会关闭外部连接）。
"""
from __future__ import annotations

import asyncio
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
from fastapi_app.core.database import require_async_engine

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
# test_export_select_matches_column_tuple 锁定。
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


def archive_dir_path(raw: str | None = None) -> Path:
    """归档目录：相对路径锚定项目根（与 STATE_PATH 同理，见上）。"""
    path = Path(raw if raw is not None else settings.AUDIT_ARCHIVE_DIR)
    return path if path.is_absolute() else _PROJECT_ROOT / path


async def window_count(db: AsyncSession, month_start: datetime, month_end: datetime) -> int:
    """某时间窗内的现存行数。"""
    return int((await db.execute(text(
        'SELECT count(*) FROM audit_log WHERE created_at >= :ms AND created_at < :me'
    ), {'ms': month_start, 'me': month_end})).scalar() or 0)


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
    """校验并读回既有归档：{path, rows, ids, sha256}。

    读到底即触发 gzip 的 CRC 校验——截断/损坏的归档在这里就抛 OSError，而不是
    被「文件存在」当成完整产物继续往下删源数据。**同步函数**：调用方用
    ``asyncio.to_thread`` 跑，避免 25 万行解压把 worker 的事件循环卡住。
    """
    ids: list[int] = []
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as gz:
            for line in gz:
                if not line.strip():
                    continue
                row_id = json.loads(line).get('id')
                if isinstance(row_id, int):
                    ids.append(row_id)
    except (zlib.error, EOFError) as exc:
        # 完整性失败与「文件读不了」是同一类数据条件，统一成 OSError：
        # zlib.error / EOFError 都不继承 OSError，不归一就会穿透整轮任务
        # （所有月份一起失败），而不是只跳过坏掉的这个月。
        raise OSError(f'归档损坏或截断: {path}（{exc}）') from exc
    return {'path': str(path), 'rows': len(ids), 'ids': ids, 'sha256': _sha256_of(path)}


async def _export_month_jsonl(
    db: AsyncSession, month_key: str, month_start: datetime, month_end: datetime,
    archive_dir: Path,
) -> dict:
    """导出一个整月到 jsonl.gz（分批读 + 原子写 + fsync）。

    返回 {path, rows, ids, sha256, existed}；existed=True 表示复用既有归档
    （rows/ids 从文件读回，不是计划值）。
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    final_path = archive_dir / f'audit_log_{month_key.replace("-", "")}.jsonl.gz'
    if final_path.exists():
        stats = await asyncio.to_thread(archive_stats, final_path)
        return {**stats, 'existed': True}

    tmp_path = final_path.parent / (final_path.name + '.tmp')
    ids: list[int] = []
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
                    ids.append(int(row[0]))
                cursor = rows[-1][0]
        # 尾部已写全，再落盘：先 fsync 后 rename，避免掉电后留下
        # 「正式文件存在但内容截断」的证据黑洞。
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(tmp_path, final_path)
    sha = await asyncio.to_thread(_sha256_of, final_path)
    return {'path': str(final_path), 'rows': len(ids), 'ids': ids,
            'sha256': sha, 'existed': False}


def _jsonable(value):
    """datetime → ISO 字符串；其余非基本类型 → str。

    ``detail`` 列是 **Text** 不是 JSONB（``shared_models/audit_log.py``），驱动
    交上来的本来就是 str，外层 ``json.dumps`` 会把它当成一个 JSON 字符串值写出
    ——不需要也不应该在里层再 dumps 一次（那会变成双重编码的字符串）。
    """
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


async def _delete_ids_batched(
    db: AsyncSession, ids: list[int], batch: int = DELETE_BATCH_ROWS,
    progress: dict | None = None,
) -> int:
    """按归档的 id 集合分批删除，每批 commit（小事务）。返回总删除行数。

    删除对象**就是**归档过的 id：不做时间窗匹配、不设上界推导，所以
    「删的行 ⊆ 归档过的行」由构造保证。已删过的 id 再删一次命中 0 行，
    崩溃后重跑天然幂等。

    ``progress`` 是可选的可变计数器：每批提交后写入累计值。中途抛错时调用方
    还能拿到「已经真实提交了多少行」——否则已提交的批次会从账本里凭空消失
    （等保账本与库不一致，且会让 ANALYZE 被跳过）。
    """
    total = 0
    for start in range(0, len(ids), batch):
        chunk = ids[start:start + batch]
        result = await db.execute(
            # batch-loop: 有意逐批删除（每批 5000 条一次往返），批数与总行数成正比
            # 而与「每行一次查询」无关；这是分批小事务本身，不是 N+1。
            text('DELETE FROM audit_log WHERE id = ANY(:ids)'), {'ids': chunk})
        await db.commit()  # 每批小事务：分批的全部意义
        total += result.rowcount or 0
        if progress is not None:
            progress['deleted'] = total
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


def _merge_state(fields: dict, state_path: Path | None = None) -> None:
    """把若干字段并入状态文件（保留既有账本），写失败只记日志。

    ``write_skip_state`` 恰恰是在另一实例持锁运行期间被调用的，所以合并必须以
    **落盘前那一刻的磁盘状态**为底、调用方字段覆盖其上；先读一份快照再合并会让
    旧快照里的值赢过最新值（持锁方刚清掉的错误被"复活"，或刚记下的错误被清掉）。
    """
    state_path = state_path or STATE_PATH
    # 落盘前**只读一次**、且以这一次为底：调用方没打算写的字段（pending_errors /
    # last_error / 账本）一律取此刻的最新值。若先读一份快照再合并，旧快照里的
    # 值会覆盖最新值——持锁方刚清掉的错误会被"复活"，健康端点在下一轮成功之前
    # 一直假 degraded（反向则是把刚记下的错误静默清掉）。
    disk = read_retention_state(state_path) or {}
    merged = {**disk, **fields}
    # 时间戳单调：调用方若带着更旧的值（字段可能在很久以前算好），只准变新。
    for key in ('last_success_at', 'last_attempt_at', 'last_skipped_at'):
        mine, theirs = _parse_ts(merged.get(key)), _parse_ts(disk.get(key))
        if theirs is not None and (mine is None or theirs > mine):
            merged[key] = disk[key]
    # 账本同理：只增不减（归档条目按月份合并，删除计数取大）
    merged['archive_files'] = {
        **(disk.get('archive_files') or {}), **(merged.get('archive_files') or {})}
    disk_total = disk.get('deleted_rows_total')
    if disk_total is not None and type(disk_total) is not int:
        # 非法账本值绝不能在这里被「取大」成 0：跳过/失败路径通常先于成功路径
        # 落盘，清零之后成功路径就再也看不到损坏，三重留痕一个都不会发生。
        # 原样保留，交给成功路径去另存现场 + 报 ledger_corrupt。
        merged['deleted_rows_total'] = disk_total
    else:
        merged['deleted_rows_total'] = max(
            _as_int(disk_total), _as_int(merged.get('deleted_rows_total')))
    try:
        _write_state(merged, state_path)
    except OSError:
        logger.exception('audit_log 保留治理: 状态写入失败（%s）', state_path)


def _parse_ts(value) -> datetime | None:
    """ISO 时间戳 → aware datetime；不可解析返回 None（比较时视为「无」）。"""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _as_int(value) -> int:
    """容错取整：手改/旧格式写坏的账本值不能把「干净退出」变成任务失败。

    ``_merge_state`` 会走 ``write_failure_state``（在 finally 里）——那里抛异常
    会顶掉原始异常，运维看到的就变成「账本解析错误」而不是真正的失败原因。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def write_failure_state(
    exc: BaseException | None, state_path: Path | None = None,
) -> None:
    """任务整体失败时也留痕：写 last_attempt_at + last_error，保留既有账本。

    没有这一步，「每天在 compute_retention_plan 上抛错」会让状态文件永不生成，
    健康端点永远停在 not_yet_run 宽限而恒绿——与 F-BE-CORE-05 同型。
    """
    _merge_state({
        'last_attempt_at': datetime.now(UTC).isoformat(),
        'last_error': f'{type(exc).__name__}: {exc}' if exc is not None else 'aborted',
    }, state_path)


def write_skip_state(reason: str, state_path: Path | None = None) -> None:
    """本轮因故跳过（如另一实例持锁）：写 last_skipped_at，别让跳过无声无息。

    跳过不写状态的话，健康侧只能等 staleness 满 7 天才红，且看不出是「被锁挡住」。
    """
    _merge_state({
        'last_skipped_at': datetime.now(UTC).isoformat(),
        'skip_reason': reason,
    }, state_path)


async def _process_month(db: AsyncSession, plan: dict, archive_dir: Path) -> dict:
    """处理单个整月：归档 → 按归档 id 删除 → 复核窗口已清空。

    返回 {entry, error, deleted}：entry 进 report['months']，error 非 None 表示
    该月有问题（同时进 report['errors']）。
    """
    archive, error = await _archive_for_month(db, plan, archive_dir)
    if error is not None:
        return _skip(plan['month'], plan, error)
    return await _delete_for_month(db, plan, archive)


async def _archive_for_month(
    db: AsyncSession, plan: dict, archive_dir: Path,
) -> tuple[dict | None, dict | None]:
    """归档该月；返回 (archive, error)，error 非 None 表示本月应直接跳过。"""
    month_key = plan['month']
    month_start, month_end = _month_bounds(month_key)
    try:
        archive = await _export_month_jsonl(db, month_key, month_start, month_end, archive_dir)
    except (OSError, SQLAlchemyError) as exc:
        # 只兜「已知可恢复」的两类：文件系统（OSError：mkdir / gzip 写 / fsync /
        # os.replace / 归档 CRC 校验失败）与数据库（SQLAlchemyError：查询、
        # 锁等待超时）。其它异常（编程错误）照旧上抛——那类 bug 必须响，
        # 不能被按月吞成一条 pending_error。
        logger.error('audit_log 保留治理: %s 归档失败，跳过该月: %s', month_key, exc)
        # 会话可能停在 aborted 事务：不回滚，后续每个月的归档都会以 25P02 失败，
        # 真实根因只在首月出现一次，其余月份的错误信息全是假的。
        with suppress(SQLAlchemyError):
            await db.rollback()
        return None, {
            'month': month_key, 'error': 'archive_failed',
            'detail': f'{type(exc).__name__}: {exc}',
            'remediation': 'OSError 查磁盘空间与归档目录权限（backups/audit_archive）；'
                           'SQLAlchemyError 查 pg_stat_activity 的锁等待与连接数；'
                           '坏归档改名为 .corrupt-<时间戳> 后下一轮重导'}

    if not archive['existed'] and archive['rows'] != plan['rows']:
        # 本次导出的行数与计划不符：导出期间有并发写入（补录/回放）时会命中。
        # 保守起见本轮不删；下一轮复用这份归档即可正常推进（幂等）。
        logger.error(
            'audit_log 保留治理: %s 归档行数 %d != 计划 %d，本轮跳过删除',
            month_key, archive['rows'], plan['rows'])
        return None, {
            'month': month_key, 'error': 'archive_row_mismatch',
            'planned_rows': plan['rows'], 'archived_rows': archive['rows'],
            'remediation': '下一轮会自动复用该归档并继续；若持续出现，检查是否有'
                           '带显式 id 的补录/恢复任务在该月窗口内写入'}
    return archive, None


async def _delete_for_month(db: AsyncSession, plan: dict, archive: dict) -> dict:
    """按归档的 id 集合删除并复核；返回 {entry, error, deleted}。"""
    month_key = plan['month']
    month_start, month_end = _month_bounds(month_key)
    entry = {'month': month_key, 'rows': plan['rows'], 'archive_rows': archive['rows'],
             'archived': True, 'archive_path': archive['path'],
             'sha256': archive['sha256'], 'deleted': 0}
    progress = {'deleted': 0}
    try:
        # 删除**前**的窗口行数：与 deleted 一起构成等式，用来发现「删到了窗口外」。
        before = await window_count(db, month_start, month_end)
        deleted = await _delete_ids_batched(db, archive['ids'], progress=progress)
        leftover = await window_count(db, month_start, month_end)
    except (OSError, SQLAlchemyError) as exc:
        # 归档已落盘（证据在），只是没删成：entry 仍带 archive_path/sha256 进账本，
        # 否则等保取证会缺一条 sha256 记录，而磁盘上明明有这份证据。
        # 已提交的批次是真删了，必须计入账本（report/state 都按 deleted_total 走）。
        partial = int(progress['deleted'])
        entry['deleted'] = partial
        # 让会话从 aborted 事务里出来：否则后续 ANALYZE 会抛 25P02
        # (InFailedSqlTransaction)，把整轮报告连同根因一起吞掉。
        with suppress(SQLAlchemyError):
            await db.rollback()
        logger.error('audit_log 保留治理: %s 删除失败（已提交 %d 行），归档已保留: %s',
                     month_key, partial, exc)
        return {'entry': entry, 'deleted': partial, 'error': {
            'month': month_key, 'error': 'delete_failed',
            'detail': f'{type(exc).__name__}: {exc}',
            'deleted_rows': partial,
            'archive_path': archive['path'], 'archived_rows': archive['rows'],
            'remediation': '归档已完成，下一轮会复用该归档续删；若持续失败，'
                           '查 pg_stat_activity 的锁等待、长事务与连接数'}}

    entry['deleted'] = deleted
    logger.info(
        'audit_log 保留治理: %s 归档 %d 行%s，删除 %d 行，窗口剩余 %d 行',
        month_key, archive['rows'], '（复用）' if archive['existed'] else '',
        deleted, leftover)
    if deleted > before:
        # 删掉的行比该月窗口里原本存在的还多 ⇒ 归档里的 id 不属于这个月（归档被
        # 改名复用/从别的环境恢复/带显式 id 的补录）。删除已发生，无法撤回，但
        # 绝不能让它在「窗口剩余 0 行」的假象里静默过去。
        return {
            'entry': entry,
            'deleted': deleted,
            'error': {
                'month': month_key, 'error': 'delete_exceeded_window',
                'deleted_rows': deleted, 'window_rows_before': before,
                'archived_rows': archive['rows'],
                'remediation': f'本次删除了窗口外的行：核对 {archive["path"]} 是否属于 '
                               f'{month_key}（该文件名可能被改名复用或来自其他环境），'
                               f'并用 pg_dump/备份比对 id 段；确认后把该归档改名 '
                               f'.superseded-<时间戳> 并人工复核被删除的 id',
            },
        }
    if leftover:
        # 归档过的 id 都删完了，窗口里还有行 —— 它们从未进过归档（补录/回放/
        # 旧备份恢复）。绝不能删，但要让它在健康信号里可见。
        return {
            'entry': entry,
            'deleted': deleted,
            'error': {
                'month': month_key, 'error': 'archive_incomplete',
                'remaining_rows': leftover, 'archived_rows': archive['rows'],
                'remediation': f'这些行未进归档，故未删除。确认它们应当被保留后，把 '
                               f'{archive["path"]} 改名为 .superseded-<时间戳>，'
                               f'下一轮会重导整月归档并重新删除',
            },
        }
    return {'entry': entry, 'error': None, 'deleted': deleted}


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
    archived, sha256, deleted}], deleted_total, analyzed, errors: [{month, error,
    ...}]}。months 为空（无需处理或禁用）也写状态文件——「任务活着」的证据本身。
    errors 非空表示有月份有问题，会写进状态文件的 pending_errors 并让健康信号
    ok=False。
    """
    now = now or datetime.now(UTC)
    archive_dir = archive_dir or archive_dir_path()
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
        await _maybe_analyze(db, report)

    _persist_report_state(report, state_path, now)
    return report


async def _maybe_analyze(db: AsyncSession, report: dict) -> None:
    """有删除时 ANALYZE；失败只记一条错误，绝不吞掉整轮报告。

    ANALYZE 只是统计修复。某月删除失败后会话可能停在 aborted 事务里，这里再抛
    25P02 就会把根因盖掉：整轮 report（含已提交的删除账目与其它月份的成功结果）
    一起丢失，健康端点从「degraded + delete_failed」退化成「stale/never_succeeded」。
    """
    try:
        await db.execute(text('ANALYZE audit_log'))
        await db.commit()
        report['analyzed'] = True
    except SQLAlchemyError as exc:
        with suppress(SQLAlchemyError):
            await db.rollback()
        logger.warning('audit_log 保留治理: ANALYZE 失败（不影响删除结果）: %s', exc)
        report['errors'].append({
            'month': None, 'error': 'analyze_failed',
            'detail': f'{type(exc).__name__}: {exc}',
            'remediation': '统计信息未刷新，查询计划可能偏保守；下一轮成功删除后会'
                           '自动重试，也可手工执行 ANALYZE audit_log'})


def _persist_report_state(report: dict, state_path: Path, now: datetime) -> None:
    """把本轮结果并入状态文件（账本只增不减，损坏留现场）。"""
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
        report['errors'].append({'month': None, 'error': 'state_corrupt_recovered',
                                 'remediation': f'原文件已另存为 {corrupt.name}，'
                                                f'人工核对后再决定是否回填账本'})
        prev = None
    prev = prev or {}
    prev_deleted_raw = prev.get('deleted_rows_total')
    corrupt_ledger = None
    if prev_deleted_raw is not None and type(prev_deleted_raw) is not int:
        # 账本里的累计删除数不是整数：不能静默归零（等于账本凭空消失且无痕迹）。
        # 只报一轮是不够的——本轮就会把值覆盖成 0，下一轮 pending_errors 一清，
        # 痕迹全无。所以三重留痕：错误进健康信号、原文件另存 .corrupt-*、
        # 并在状态里长期保留 original 值（等保要的是「账本被动过」这件事本身）。
        logger.error('audit_log 保留治理: 账本 deleted_rows_total 非法（%r），按 0 起算',
                     prev_deleted_raw)
        corrupt_ledger = {
            'value': str(prev_deleted_raw)[:40],
            'detected_at': now.isoformat(),
        }
        try:
            backup = state_path.parent / f'{state_path.name}.corrupt-{now:%Y%m%d%H%M%S}'
            os.replace(state_path, backup)
            corrupt_ledger['backup'] = backup.name
        except OSError:
            logger.exception('audit_log 保留治理: 账本损坏但无法另存现场')
        report['errors'].append({
            'month': None, 'error': 'ledger_corrupt',
            'value': corrupt_ledger['value'],
            'backup': corrupt_ledger.get('backup'),
            'remediation': '核对 .corrupt-* 备份里的 deleted_rows_total，按备份/归档行数'
                           '人工回填；原值同时保留在 deleted_rows_total_corrupt 字段'})
    else:
        # 没有新损坏就保留既有痕迹（人工回填前一直可见）
        corrupt_ledger = prev.get('deleted_rows_total_corrupt')
    archives = dict(prev.get('archive_files') or {})
    for m in report['months']:
        if m.get('archive_path'):
            archives[m['month']] = {
                'path': str(Path(m['archive_path']).resolve()),
                'rows': m['archive_rows'], 'sha256': m['sha256'],
            }
    state = {
        'last_success_at': now.isoformat(),
        'last_attempt_at': now.isoformat(),
        'retention_months': settings.AUDIT_RETENTION_MONTHS,
        # 账本被手改坏（"1,234" 之类）不能在**已删完数据之后**抛 ValueError
        # ——那一抛会让本轮的 last_success_at/archive_files 都不落盘
        # （错误已记成 ledger_corrupt，不是静默归零）。
        'deleted_rows_total': _as_int(prev_deleted_raw) + report['deleted_total'],
        'archive_files': archives,
        # 「账本曾被动过」这件事本身要长期可见（值已按 0 起算，痕迹不能跟着消失）
        'deleted_rows_total_corrupt': corrupt_ledger,
        # 上一轮错误不累加：本轮成功即清空（错误是「当前是否卡着」的信号，
        # 不是历史账本；历史归档证据在 archive_files 里）
        'pending_errors': report['errors'],
    }
    _write_state(state, state_path)


async def audit_retention_task(ctx) -> dict:
    """ARQ cron 入口（03:00，日级补跑机制覆盖）：专用连接持锁后执行一轮。

    为什么不用会话锁：``pg_try_advisory_lock`` 的生命周期跟 **DBAPI 连接**走，
    而 ``Session.commit()`` 在根事务结束时把连接归还池，下一次 execute 可能拿到
    另一条——锁会留在池里某条连接上，解锁还打在别的连接上（返回 false 被忽略）。
    本任务每批都 commit，所以必须自己握住连接：``engine.connect()`` 拿到的连接
    由调用方所有，``AsyncSession(bind=conn)`` 的 commit 不会关闭它。

    为什么还要 ``join_transaction_mode='control_fully'``：绑定到**已经开了事务**
    的连接时，SQLAlchemy 默认（``conditional_savepoint``）会退到 ``rollback_only``，
    ``commit()`` 只 flush 不发 COMMIT。取锁那条 SELECT 恰好就 autobegin 了，
    不显式接管事务，每批删除的 commit 全是空转，最后被 finally 的 rollback 丢掉
    ——任务报成功、库里一行没删、健康端点全程绿。
    """
    engine = require_async_engine()
    report: dict | None = None
    async with engine.connect() as conn:
        locked = bool((await conn.execute(
            text('SELECT pg_try_advisory_lock(:k)'), {'k': RETENTION_LOCK_KEY})).scalar())
        if not locked:
            # 另一实例在跑（cron 与日级补跑重叠）：留痕后干净退出
            logger.warning('audit_log 保留治理: 已有实例持锁，跳过本轮')
            write_skip_state('lock_busy')
            return {'skipped': 'lock_busy'}
        try:
            # 上面那条 SELECT 让连接进入事务（autobegin）。**必须先结束它**：
            # 绑定到「已有事务的连接」的会话会退化，默认 join_transaction_mode
            # （conditional_savepoint）在这种情况下落到 rollback_only ——
            # `Session.commit()` 只 flush、不发 COMMIT，本任务每批删除的 commit
            # 因此全部堆在外部事务里，最后由 finally 的 rollback 一起丢掉：
            # 任务报「删了 N 行」、库里一行没少、窗口复核也看不见（同一事务内
            # 自证清白），健康端点全程绿 —— 静默失效的教科书形态。
            # 两道保险：先 rollback 结束 autobegin（advisory lock 是会话级、
            # 不随事务回滚释放），再显式 control_fully 让会话自己掌管提交。
            with suppress(SQLAlchemyError):
                await conn.rollback()
            async with AsyncSession(bind=conn, join_transaction_mode='control_fully') as db:
                report = await run_retention_once(db)
        finally:
            # 会话若停在 abort 事务里，先回滚才能执行下一条语句
            with suppress(SQLAlchemyError):
                await conn.rollback()
            try:
                released = (await conn.execute(
                    text('SELECT pg_advisory_unlock(:k)'),
                    {'k': RETENTION_LOCK_KEY})).scalar()
                if not released:
                    # 「锁没释放」的两条信号之一：返回 false
                    logger.error('audit_log 保留治理: advisory lock 未能释放（键 %#x）',
                                 RETENTION_LOCK_KEY)
            except SQLAlchemyError:
                # 另一条信号：解锁语句本身失败。这里若也 suppress，最需要告警的
                # 路径就彻底沉默了（锁会跟着回池的连接，后续每轮都 lock_busy）。
                logger.exception('audit_log 保留治理: advisory lock 释放失败（键 %#x）',
                                 RETENTION_LOCK_KEY)
                # 连接连同会话级锁一起丢弃：回池复用会让本任务下次「重入成功」，
                # 而别的实例/手工补跑永远拿不到锁。
                with suppress(SQLAlchemyError):
                    await conn.invalidate()
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

    ok=False 的情形（任一即降级）：
    - **配置低于法定下限**（0 < months < 6）：误配必须可见，否则一次运行就能
      把留存压到法定线以下；
    - **停摆**：距上次成功 > STALE_DAYS（沿用备份链停摆先例）；
    - **有待处理错误**：``pending_errors`` 非空（某月归档失败会被逐轮跳过，
      若只看 staleness，``last_success_at`` 照常刷新会让积压永远不可见）。
    ok=True 的情形：任务被禁用（months ≤ 0，明确的人工选择）；状态文件不存在
    （从未部署过该任务——注意任务体失败时会写 ``last_attempt_at``，所以
    「文件持续不存在」不等于「天天失败」）。

    状态文件存在但读不出来 / 缺 last_success_at / 时间戳不可解析 → ok=False。
    其中「跑过但从未成功」与「文件损坏」用不同 note 区分（前者查任务，后者查文件）。
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
        if not STATE_PATH.exists():
            return {'ok': True, 'last_success_at': None, 'note': 'not_yet_run'}
        attempted = bool((state or {}).get('last_attempt_at'))
        return {
            'ok': False,
            'last_success_at': None,
            # 「跑过但从未成功」≠「文件坏了」：前者查任务，后者查文件
            'note': 'never_succeeded' if attempted else 'state_unreadable',
            'last_attempt_at': (state or {}).get('last_attempt_at'),
            'last_error': (state or {}).get('last_error'),
            'last_skipped_at': (state or {}).get('last_skipped_at'),
            'skip_reason': (state or {}).get('skip_reason'),
            'state_path': str(STATE_PATH),
        }
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
        # 「账本曾被动过」在 pending_errors 清空后仍要可见（否则只有主动翻
        # 状态文件/备份目录才看得出来）。不参与 ok 判据：损坏本身已在发现轮
        # 让 ok=False，之后属于待人工回填的已知状态。
        'ledger_corrupt': state.get('deleted_rows_total_corrupt') or None,
        # 只暴露前几条，避免健康响应被长列表撑爆
        'pending_errors': pending[:5],
        'pending_error_count': len(pending),
    }
