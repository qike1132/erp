"""numbering_audit 保留治理：UTC 日界、归档先行、分批删除、失败可见。

默认保留 30 个完整 UTC 日（实际 30–31 天）。每日任务只删除严格早于 cutoff
且已写入 JSONL.GZ 归档的 ID；归档损坏或导出失败时不删除任何源行。
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

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import require_async_engine

logger = logging.getLogger(__name__)

DELETE_BATCH_ROWS = 5000
EXPORT_BATCH_ROWS = 5000
STALE_DAYS = 7
#: 与旧 audit_log 任务（0x4152455400000001）区分；必须落在 PostgreSQL bigint
#: 有符号范围内，否则 pg_try_advisory_lock 会直接报溢出而不是返回 false。
RETENTION_LOCK_KEY = 0x4E41524554000001
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = _PROJECT_ROOT / 'logs' / 'numbering_audit_retention_state.json'
_COLUMNS = ('id', 'scope', 'counter_behind', 'detail', 'checked_at')
_EXPORT_SELECT = (
    'SELECT id, scope, counter_behind, detail, checked_at FROM numbering_audit '
    'WHERE checked_at < :cutoff AND id > :cursor ORDER BY id LIMIT :batch'
)


def _as_utc(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def retention_cutoff(now: datetime | None = None) -> datetime:
    """当前 UTC 日减保留天数；完整日粒度避免同日重跑移动窗口。"""
    now = _as_utc(now)
    day = now.date() - timedelta(days=settings.NUMBERING_AUDIT_RETENTION_DAYS)
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def archive_dir_path(raw: str | None = None) -> Path:
    path = Path(raw if raw is not None else settings.NUMBERING_AUDIT_ARCHIVE_DIR)
    return path if path.is_absolute() else _PROJECT_ROOT / path


def _archive_path(archive_dir: Path, cutoff: datetime) -> Path:
    return archive_dir / f'numbering_audit_before_{cutoff:%Y%m%d}.jsonl.gz'


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as raw:
        for block in iter(lambda: raw.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _read_archive(path: Path) -> dict:
    """读到底完成 CRC 校验，并核对列契约，拒绝把错误归档当成删除依据。"""
    ids: list[int] = []
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as gz:
            for line in gz:
                if not line.strip():
                    continue
                row = json.loads(line)
                if tuple(row) != _COLUMNS or type(row.get('id')) is not int:
                    raise OSError(f'归档列契约不符: {path}')
                ids.append(row['id'])
    except (zlib.error, EOFError, UnicodeError, json.JSONDecodeError) as exc:
        raise OSError(f'归档损坏或截断: {path}（{exc}）') from exc
    if len(ids) != len(set(ids)):
        raise OSError(f'归档包含重复 ID: {path}')
    return {'path': str(path), 'rows': len(ids), 'ids': ids, 'sha256': _sha256_of(path)}


async def _expired_count(db: AsyncSession, cutoff: datetime) -> int:
    return int((await db.execute(text(
        'SELECT count(*) FROM numbering_audit WHERE checked_at < :cutoff'
    ), {'cutoff': cutoff})).scalar() or 0)


async def _export_expired_jsonl(db: AsyncSession, cutoff: datetime, archive_dir: Path) -> dict:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = _archive_path(archive_dir, cutoff)
    if path.exists():
        return {**_read_archive(path), 'existed': True}

    planned = await _expired_count(db, cutoff)
    ids: list[int] = []
    cursor = -1
    tmp = path.parent / (path.name + '.tmp')
    with open(tmp, 'wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb') as gz:
            while True:
                rows = (await db.execute(text(_EXPORT_SELECT), {
                    'cutoff': cutoff, 'cursor': cursor, 'batch': EXPORT_BATCH_ROWS,
                })).all()
                if not rows:
                    break
                for row in rows:
                    payload = dict(zip(_COLUMNS, row, strict=True))
                    payload['checked_at'] = payload['checked_at'].isoformat()
                    gz.write(json.dumps(payload, ensure_ascii=False).encode('utf-8') + b'\n')
                    ids.append(int(row[0]))
                cursor = rows[-1][0]
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(tmp, path)
    return {
        'path': str(path), 'rows': len(ids), 'ids': ids,
        'sha256': _sha256_of(path), 'existed': False, 'planned_rows': planned,
    }


async def _delete_ids_batched(
    db: AsyncSession, ids: list[int], cutoff: datetime, progress: dict,
) -> int:
    total = 0
    for start in range(0, len(ids), DELETE_BATCH_ROWS):
        chunk = ids[start:start + DELETE_BATCH_ROWS]
        result = await db.execute(
            # batch-loop: 每批一次集合删除与 commit；不是逐行 N+1。
            text('DELETE FROM numbering_audit WHERE id = ANY(:ids) AND checked_at < :cutoff'),
            {'ids': chunk, 'cutoff': cutoff},
        )
        await db.commit()
        total += result.rowcount or 0
        progress['deleted'] = total
    return total


def read_retention_state(state_path: Path | None = None) -> dict | None:
    try:
        data = json.loads((state_path or STATE_PATH).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_state(state: dict, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.parent / (state_path.name + '.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, state_path)


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _merge_state(fields: dict, state_path: Path | None = None) -> None:
    state_path = state_path or STATE_PATH
    disk = read_retention_state(state_path) or {}
    merged = {**disk, **fields}
    for key in ('last_success_at', 'last_attempt_at', 'last_skipped_at'):
        mine, theirs = _parse_ts(merged.get(key)), _parse_ts(disk.get(key))
        if theirs is not None and (mine is None or theirs > mine):
            merged[key] = disk[key]
    merged['archive_files'] = {
        **(disk.get('archive_files') or {}), **(merged.get('archive_files') or {})}
    disk_total = disk.get('deleted_rows_total')
    if disk_total is not None and type(disk_total) is not int:
        merged['deleted_rows_total'] = disk_total
    else:
        merged['deleted_rows_total'] = max(
            _as_int(disk_total), _as_int(merged.get('deleted_rows_total')))
    try:
        _write_state(merged, state_path)
    except OSError:
        logger.exception('numbering_audit 保留治理: 状态写入失败（%s）', state_path)


def write_failure_state(exc: BaseException | None, state_path: Path | None = None) -> None:
    _merge_state({
        'last_attempt_at': datetime.now(UTC).isoformat(),
        'last_error': f'{type(exc).__name__}: {exc}' if exc is not None else 'aborted',
    }, state_path)


def write_skip_state(reason: str, state_path: Path | None = None) -> None:
    _merge_state({
        'last_skipped_at': datetime.now(UTC).isoformat(),
        'skip_reason': reason,
    }, state_path)


def _persist_report_state(report: dict, state_path: Path, now: datetime) -> None:
    previous = read_retention_state(state_path)
    if previous is None and state_path.exists():
        corrupt = state_path.parent / f'{state_path.name}.corrupt-{now:%Y%m%d%H%M%S}'
        try:
            os.replace(state_path, corrupt)
            report['errors'].append({
                'error': 'state_corrupt_recovered',
                'remediation': f'原状态已另存为 {corrupt.name}，请人工核对账本',
            })
        except OSError as exc:
            report['errors'].append({'error': 'state_corrupt_unreadable', 'detail': str(exc)})
        previous = None
    previous = previous or {}
    previous_total = previous.get('deleted_rows_total')
    corrupt_ledger = previous.get('deleted_rows_total_corrupt')
    if previous_total is not None and type(previous_total) is not int:
        corrupt_ledger = {'value': str(previous_total)[:40], 'detected_at': now.isoformat()}
        report['errors'].append({
            'error': 'ledger_corrupt', 'value': corrupt_ledger['value'],
            'remediation': '按归档与备份人工回填 deleted_rows_total',
        })
    archives = dict(previous.get('archive_files') or {})
    if report.get('archive') and report.get('archive_key'):
        archive = report['archive']
        archives[report['archive_key']] = {
            'path': str(Path(archive['path']).resolve()),
            'rows': archive['rows'], 'sha256': archive['sha256'],
        }
    state = {
        'last_success_at': now.isoformat(),
        'last_attempt_at': now.isoformat(),
        'last_skipped_at': previous.get('last_skipped_at'),
        'skip_reason': previous.get('skip_reason'),
        'retention_days': report['retention_days'],
        'deleted_rows_total': _as_int(previous_total) + report['deleted_total'],
        'deleted_rows_total_corrupt': corrupt_ledger,
        'archive_files': archives,
        'pending_errors': report['errors'],
    }
    _write_state(state, state_path)


async def _maybe_analyze(db: AsyncSession, report: dict) -> None:
    if not report['deleted_total']:
        return
    try:
        await db.execute(text('ANALYZE numbering_audit'))
        await db.commit()
        report['analyzed'] = True
    except SQLAlchemyError as exc:
        with suppress(SQLAlchemyError):
            await db.rollback()
        report['errors'].append({
            'error': 'analyze_failed', 'detail': f'{type(exc).__name__}: {exc}',
            'remediation': '删除结果已保留；下一轮会重试，也可在维护窗口 ANALYZE numbering_audit',
        })


async def run_retention_once(
    db: AsyncSession, now: datetime | None = None,
    archive_dir: Path | None = None, state_path: Path | None = None,
) -> dict:
    now = _as_utc(now)
    archive_dir = archive_dir or archive_dir_path()
    state_path = state_path or STATE_PATH
    days = settings.NUMBERING_AUDIT_RETENTION_DAYS
    report = {
        'ran_at': now.isoformat(), 'retention_days': days, 'disabled': days <= 0,
        'archive_key': None, 'archive': None, 'deleted_total': 0,
        'analyzed': False, 'errors': [],
    }
    if days > 0:
        cutoff = retention_cutoff(now)
        report['archive_key'] = cutoff.date().isoformat()
        planned = await _expired_count(db, cutoff)
        if planned:
            archive = None
            try:
                archive = await _export_expired_jsonl(db, cutoff, archive_dir)
                report['archive'] = {k: v for k, v in archive.items() if k != 'ids'}
            except (OSError, SQLAlchemyError) as exc:
                with suppress(SQLAlchemyError):
                    await db.rollback()
                report['errors'].append({
                    'error': 'archive_failed', 'detail': f'{type(exc).__name__}: {exc}',
                    'remediation': '检查归档目录权限、磁盘空间和数据库锁；坏归档改名后重导',
                })
            if archive is not None:
                if not archive['existed'] and archive['rows'] != planned:
                    report['errors'].append({
                        'error': 'archive_row_mismatch',
                        'planned_rows': planned, 'archived_rows': archive['rows'],
                        'remediation': '本轮不删除；检查是否有并发历史补录，下一轮复用归档复核',
                    })
                else:
                    progress = {'deleted': 0}
                    try:
                        before = await _expired_count(db, cutoff)
                        deleted = await _delete_ids_batched(db, archive['ids'], cutoff, progress)
                        leftover = await _expired_count(db, cutoff)
                        report['deleted_total'] = deleted
                        if deleted > before:
                            report['errors'].append({
                                'error': 'delete_exceeded_window',
                                'deleted_rows': deleted, 'window_rows_before': before,
                                'remediation': '核对归档来源与环境，并按备份复核被删除 ID',
                            })
                        elif leftover:
                            report['errors'].append({
                                'error': 'archive_incomplete', 'remaining_rows': leftover,
                                'remediation': '未归档行未删除；确认后改名归档为 .superseded-* 以重导',
                            })
                    except (OSError, SQLAlchemyError) as exc:
                        report['deleted_total'] = progress['deleted']
                        with suppress(SQLAlchemyError):
                            await db.rollback()
                        report['errors'].append({
                            'error': 'delete_failed', 'detail': f'{type(exc).__name__}: {exc}',
                            'deleted_rows': progress['deleted'],
                            'remediation': '归档已保留；修复锁/连接问题后下一轮续删',
                        })
        await _maybe_analyze(db, report)
    _persist_report_state(report, state_path, now)
    return report


async def numbering_audit_retention_task(ctx) -> dict:
    """ARQ 入口：锁与提交共用专用连接，防止 cron/补跑/手工触发重入。"""
    engine = require_async_engine()
    report: dict | None = None
    async with engine.connect() as conn:
        locked = bool((await conn.execute(
            text('SELECT pg_try_advisory_lock(:k)'), {'k': RETENTION_LOCK_KEY})).scalar())
        if not locked:
            write_skip_state('lock_busy')
            return {'skipped': 'lock_busy'}
        try:
            # 结束取锁 SELECT 的 autobegin；会话级锁不会随 rollback 释放。
            with suppress(SQLAlchemyError):
                await conn.rollback()
            async with AsyncSession(bind=conn, join_transaction_mode='control_fully') as db:
                report = await run_retention_once(db)
        finally:
            with suppress(SQLAlchemyError):
                await conn.rollback()
            try:
                released = (await conn.execute(
                    text('SELECT pg_advisory_unlock(:k)'), {'k': RETENTION_LOCK_KEY})).scalar()
                if not released:
                    logger.error('numbering_audit 保留治理: advisory lock 未能释放')
            except SQLAlchemyError:
                logger.exception('numbering_audit 保留治理: advisory lock 释放失败')
                with suppress(SQLAlchemyError):
                    await conn.invalidate()
            if report is None:
                write_failure_state(sys.exc_info()[1])
    logger.info(
        'numbering_audit 保留治理完成: deleted=%d errors=%d',
        report['deleted_total'], len(report['errors']),
    )
    return report


def _signal(**overrides) -> dict:
    base = {
        'ok': True, 'disabled': False, 'note': None,
        'last_success_at': None, 'last_attempt_at': None, 'last_skipped_at': None,
        'skip_reason': None, 'last_error': None, 'age_days': None,
        'stale_threshold_days': STALE_DAYS, 'retention_days': None,
        'deleted_rows_total': None, 'ledger_corrupt': None,
        'pending_errors': [], 'pending_error_count': 0, 'state_path': None,
    }
    base.update(overrides)
    return base


def numbering_audit_retention_signal() -> dict:
    """固定键集；pending error、最近整体失败或超过 7 天未成功均降级。"""
    days = settings.NUMBERING_AUDIT_RETENTION_DAYS
    if days <= 0:
        return _signal(disabled=True, retention_days=days)
    state = read_retention_state()
    if state is None or not state.get('last_success_at'):
        if not STATE_PATH.exists():
            return _signal(note='not_yet_run', retention_days=days)
        attempted = bool((state or {}).get('last_attempt_at'))
        return _signal(
            ok=False, note='never_succeeded' if attempted else 'state_unreadable',
            retention_days=days,
            last_attempt_at=(state or {}).get('last_attempt_at'),
            last_error=(state or {}).get('last_error'),
            last_skipped_at=(state or {}).get('last_skipped_at'),
            skip_reason=(state or {}).get('skip_reason'), state_path=str(STATE_PATH),
        )
    last = _parse_ts(state.get('last_success_at'))
    if last is None:
        return _signal(ok=False, note='state_unreadable', retention_days=days,
                       state_path=str(STATE_PATH))
    age_days = (datetime.now(UTC) - last) / timedelta(days=1)
    pending = state.get('pending_errors') or []
    attempt = _parse_ts(state.get('last_attempt_at'))
    recent_failure = bool(
        state.get('last_error') and attempt is not None and attempt > last,
    )
    return _signal(
        ok=age_days <= STALE_DAYS and not pending and not recent_failure,
        note='recent_failure' if recent_failure else None,
        last_success_at=state['last_success_at'],
        last_attempt_at=state.get('last_attempt_at'),
        last_skipped_at=state.get('last_skipped_at'),
        skip_reason=state.get('skip_reason'),
        last_error=state.get('last_error'),
        age_days=round(age_days, 1), retention_days=state.get('retention_days', days),
        deleted_rows_total=state.get('deleted_rows_total'),
        ledger_corrupt=state.get('deleted_rows_total_corrupt') or None,
        pending_errors=pending[:5], pending_error_count=len(pending),
    )
