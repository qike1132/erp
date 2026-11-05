"""numbering_audit 保留治理：安全不变式与入口契约。"""
from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.core.config import settings
from fastapi_app.tasks import numbering_audit_retention_task as nrt


class _Result:
    def __init__(self, rows: list[Any] | None = None, rowcount: int = 0, scalar: Any = None):
        self._rows = rows or []
        self.rowcount = rowcount
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


def _row(row_id: int, checked_at: datetime) -> tuple:
    return row_id, f'PO-{row_id}', row_id % 2, f'detail-{row_id}', checked_at


def _row_json(row: tuple) -> dict:
    return {
        'id': row[0], 'scope': row[1], 'counter_behind': row[2],
        'detail': row[3], 'checked_at': row[4].isoformat(),
    }


def _write_archive(path, rows: list[tuple], corrupt: bool = False) -> None:
    if corrupt:
        path.write_bytes(b'not-a-gzip-archive')
        return
    with gzip.open(path, 'wt', encoding='utf-8') as gz:
        for row in rows:
            gz.write(json.dumps(_row_json(row), ensure_ascii=False) + '\n')


class FakeDB:
    def __init__(
        self,
        rows: list[tuple] | None = None,
        export_error: Exception | None = None,
        delete_error: Exception | None = None,
        delete_error_after: int | None = None,
        analyze_error: Exception | None = None,
        hidden_ids: set[int] | None = None,
    ):
        self.rows = list(rows or [])
        self.export_error = export_error
        self.delete_error = delete_error
        self.delete_error_after = delete_error_after
        self.analyze_error = analyze_error
        self.hidden_ids = hidden_ids or set()
        self.calls: list[str] = []
        self.deleted_ids: list[int] = []
        self.delete_batches: list[list[int]] = []
        self.commits = 0
        self.rollbacks = 0

    def _expired(self, cutoff: datetime) -> list[tuple]:
        return [row for row in self.rows if row[4] < cutoff]

    async def execute(self, statement, params: dict | None = None):
        sql = str(statement)
        params = params or {}
        if sql.startswith('SELECT count(*) FROM numbering_audit'):
            self.calls.append('count')
            count = len(self._expired(params['cutoff']))
            return _Result(scalar=count)
        if sql.startswith('SELECT id, scope, counter_behind, detail, checked_at'):
            self.calls.append('export')
            if self.export_error:
                raise self.export_error
            rows = sorted(
                (row for row in self._expired(params['cutoff'])
                 if row[0] > params['cursor'] and row[0] not in self.hidden_ids),
                key=lambda row: row[0],
            )
            return _Result(rows[: params['batch']])
        if sql.startswith('DELETE FROM numbering_audit'):
            self.calls.append('delete')
            if (self.delete_error is not None
                    and (self.delete_error_after is None
                         or len(self.delete_batches) >= self.delete_error_after)):
                raise self.delete_error
            ids = set(params['ids'])
            # 真实按 SQL 的两个谓词筛选；漏掉 cutoff 时会误删新记录，测试能抓住。
            if 'checked_at < :cutoff' not in sql:
                raise AssertionError('DELETE 必须同时带归档 ID 与过期时间双约束')
            matched = [row[0] for row in self.rows
                       if row[0] in ids and row[4] < params['cutoff']]
            self.delete_batches.append(list(params['ids']))
            self.deleted_ids.extend(matched)
            self.rows = [row for row in self.rows if row[0] not in matched]
            return _Result(rowcount=len(matched))
        if sql.startswith('ANALYZE numbering_audit'):
            self.calls.append('analyze')
            if self.analyze_error:
                raise self.analyze_error
            return _Result()
        raise AssertionError(f'未预期 SQL: {sql[:120]}')

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'NUMBERING_AUDIT_RETENTION_DAYS', 30, raising=False)
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'default_state.json')
    monkeypatch.setattr(nrt, 'DELETE_BATCH_ROWS', 5000)


def test_cutoff_uses_utc_day_boundary():
    now = datetime(2026, 11, 15, 12, 34, tzinfo=UTC)
    assert nrt.retention_cutoff(now) == datetime(2026, 10, 16, 0, 0, tzinfo=UTC)


def test_archive_dir_is_anchored_to_project_root(tmp_path):
    assert nrt.archive_dir_path('backups/numbering_audit_archive') == (
        nrt._PROJECT_ROOT / 'backups/numbering_audit_archive')
    assert nrt.archive_dir_path(str(tmp_path)) == tmp_path


async def test_disabled_retention_does_not_query_or_delete(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'NUMBERING_AUDIT_RETENTION_DAYS', 0, raising=False)
    db = FakeDB([_row(1, datetime(2000, 1, 1, tzinfo=UTC))])
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert report['disabled'] is True
    assert report['deleted_total'] == 0
    assert db.calls == []


async def test_empty_expired_set_succeeds_without_archive(tmp_path):
    db = FakeDB([_row(1, datetime(2026, 11, 15, tzinfo=UTC))])
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert report['deleted_total'] == 0 and report['errors'] == []
    assert 'delete' not in db.calls and 'export' not in db.calls
    assert list(tmp_path.glob('*.jsonl.gz')) == []


async def test_cutoff_equal_timestamp_is_retained(tmp_path):
    now = datetime(2026, 11, 15, tzinfo=UTC)
    db = FakeDB([_row(1, nrt.retention_cutoff(now))])
    report = await nrt.run_retention_once(
        db, now=now, archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert report['deleted_total'] == 0
    assert db.deleted_ids == []


async def test_archive_precedes_delete_and_contains_exact_rows(tmp_path):
    old = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)
    db = FakeDB([_row(2, old), _row(1, old), _row(3, datetime(2026, 11, 1, tzinfo=UTC))])
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert db.calls.index('export') < db.calls.index('delete')
    assert sorted(db.deleted_ids) == [1, 2]
    assert report['deleted_total'] == 2 and report['errors'] == []
    archives = list(tmp_path.glob('numbering_audit_before_*.jsonl.gz'))
    assert len(archives) == 1
    with gzip.open(archives[0], 'rt', encoding='utf-8') as gz:
        archived = [json.loads(line) for line in gz.read().splitlines()]
    assert [row['id'] for row in archived] == [1, 2]
    assert report['archive']['rows'] == 2
    assert len(report['archive']['sha256']) == 64


async def test_export_failure_means_no_delete(tmp_path):
    db = FakeDB(
        [_row(1, datetime(2026, 9, 1, tzinfo=UTC))],
        export_error=SQLAlchemyError('read failed'),
    )
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert report['deleted_total'] == 0
    assert report['errors'][0]['error'] == 'archive_failed'
    assert 'delete' not in db.calls


async def test_corrupt_existing_archive_is_not_reused(tmp_path):
    old = datetime(2026, 9, 1, tzinfo=UTC)
    path = tmp_path / 'numbering_audit_before_20261016.jsonl.gz'
    _write_archive(path, [_row(1, old)], corrupt=True)
    db = FakeDB([_row(1, old)])
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert report['deleted_total'] == 0
    assert report['errors'][0]['error'] == 'archive_failed'
    assert 'delete' not in db.calls


async def test_export_count_mismatch_means_no_delete(tmp_path):
    old = datetime(2026, 9, 1, tzinfo=UTC)
    db = FakeDB([_row(1, old), _row(2, old), _row(3, old)], hidden_ids={3})
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert report['deleted_total'] == 0
    assert report['errors'][0]['error'] == 'archive_row_mismatch'
    assert 'delete' not in db.calls


async def test_unarchived_late_row_is_not_deleted(tmp_path):
    old = datetime(2026, 9, 1, tzinfo=UTC)
    path = tmp_path / 'numbering_audit_before_20261016.jsonl.gz'
    _write_archive(path, [_row(1, old), _row(2, old)])
    db = FakeDB([_row(1, old), _row(2, old), _row(3, old)])
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert sorted(db.deleted_ids) == [1, 2]
    assert 3 not in db.deleted_ids
    assert report['errors'][0]['error'] == 'archive_incomplete'
    assert report['errors'][0]['remaining_rows'] == 1


async def test_wrong_archive_cannot_delete_non_expired_row(tmp_path):
    old = datetime(2026, 9, 1, tzinfo=UTC)
    recent = datetime(2026, 11, 1, tzinfo=UTC)
    path = tmp_path / 'numbering_audit_before_20261016.jsonl.gz'
    _write_archive(path, [_row(1, old), _row(2, recent)])
    db = FakeDB([_row(1, old), _row(2, recent)])
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert db.deleted_ids == [1], '归档 ID 之外的新记录必须被 cutoff 防住'
    assert [row[0] for row in db.rows] == [2]
    assert report['errors'] == []


async def test_partial_delete_is_accounted_and_rerun_completes(tmp_path, monkeypatch):
    monkeypatch.setattr(nrt, 'DELETE_BATCH_ROWS', 2)
    old = datetime(2026, 9, 1, tzinfo=UTC)
    rows = [_row(i, old) for i in range(1, 6)]
    db = FakeDB(rows, delete_error=SQLAlchemyError('lock timeout'), delete_error_after=1)
    state_path = tmp_path / 'state.json'
    first = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path)
    assert first['deleted_total'] == 2
    assert first['errors'][0]['error'] == 'delete_failed'
    assert first['errors'][0]['deleted_rows'] == 2
    assert db.rollbacks >= 1
    assert json.loads(state_path.read_text(encoding='utf-8'))['deleted_rows_total'] == 2

    db.delete_error = None
    export_calls_before = db.calls.count('export')
    second = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path)
    assert second['deleted_total'] == 3 and second['errors'] == []
    assert db.calls.count('export') == export_calls_before, '重跑必须复用归档，不重导'
    assert sorted(db.deleted_ids) == [1, 2, 3, 4, 5]
    assert json.loads(state_path.read_text(encoding='utf-8'))['deleted_rows_total'] == 5


async def test_analyze_failure_does_not_erase_delete_result(tmp_path):
    db = FakeDB(
        [_row(1, datetime(2026, 9, 1, tzinfo=UTC))],
        analyze_error=SQLAlchemyError('analyze failed'),
    )
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=tmp_path / 'state.json')
    assert report['deleted_total'] == 1
    assert report['errors'][-1]['error'] == 'analyze_failed'


async def test_corrupt_state_is_set_aside(tmp_path):
    state_path = tmp_path / 'state.json'
    state_path.write_text('{broken', encoding='utf-8')
    db = FakeDB()
    report = await nrt.run_retention_once(
        db, now=datetime(2026, 11, 15, tzinfo=UTC),
        archive_dir=tmp_path, state_path=state_path)
    assert report['errors'][0]['error'] == 'state_corrupt_recovered'
    assert len(list(tmp_path.glob('state.json.corrupt-*'))) == 1


class _FakeConn:
    def __init__(self, lock_ok: bool = True, unlock_error: Exception | None = None):
        self.lock_ok = lock_ok
        self.unlock_error = unlock_error
        self.invalidated = False
        self.calls: list[str] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append(sql)
        if 'pg_try_advisory_lock' in sql:
            return _Result(scalar=self.lock_ok)
        if 'pg_advisory_unlock' in sql:
            if self.unlock_error:
                raise self.unlock_error
            return _Result(scalar=True)
        return _Result(scalar=True)

    async def rollback(self):
        self.calls.append('rollback')

    async def invalidate(self):
        self.invalidated = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, lock_ok: bool = True, unlock_error: Exception | None = None):
        self.conns: list[_FakeConn] = []
        self._lock_ok = lock_ok
        self._unlock_error = unlock_error

    def connect(self):
        conn = _FakeConn(self._lock_ok, self._unlock_error)
        self.conns.append(conn)
        return conn


class _FakeSession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def _patch_session(monkeypatch):
    seen = {}

    def _factory(**kwargs):
        seen['session'] = _FakeSession(**kwargs)
        return seen['session']

    monkeypatch.setattr(nrt, 'AsyncSession', _factory)
    return seen


async def test_task_uses_one_dedicated_connection_and_control_fully(monkeypatch, tmp_path):
    engine = _FakeEngine()
    monkeypatch.setattr(nrt, 'require_async_engine', lambda: engine)
    seen = _patch_session(monkeypatch)

    async def _run(db):
        return {'deleted_total': 0, 'analyzed': False, 'errors': []}

    monkeypatch.setattr(nrt, 'run_retention_once', _run)
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'state.json')
    await nrt.numbering_audit_retention_task({})
    assert len(engine.conns) == 1
    assert seen['session'].kwargs['bind'] is engine.conns[0]
    assert seen['session'].kwargs['join_transaction_mode'] == 'control_fully'
    calls = engine.conns[0].calls
    assert any('pg_try_advisory_lock' in call for call in calls)
    assert any('pg_advisory_unlock' in call for call in calls)


async def test_task_lock_busy_writes_skip_not_success(monkeypatch, tmp_path):
    engine = _FakeEngine(lock_ok=False)
    monkeypatch.setattr(nrt, 'require_async_engine', lambda: engine)
    _patch_session(monkeypatch)
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'state.json')
    result = await nrt.numbering_audit_retention_task({})
    assert result == {'skipped': 'lock_busy'}
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['skip_reason'] == 'lock_busy'
    assert 'last_success_at' not in state


async def test_task_failure_records_attempt_and_releases_lock(monkeypatch, tmp_path):
    engine = _FakeEngine()
    monkeypatch.setattr(nrt, 'require_async_engine', lambda: engine)
    _patch_session(monkeypatch)

    async def _boom(db):
        raise RuntimeError('plan failed')

    monkeypatch.setattr(nrt, 'run_retention_once', _boom)
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'state.json')
    with pytest.raises(RuntimeError, match='plan failed'):
        await nrt.numbering_audit_retention_task({})
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state['last_error'] == 'RuntimeError: plan failed'
    assert any('pg_advisory_unlock' in call for call in engine.conns[0].calls)


async def test_unlock_failure_invalidates_connection(monkeypatch, tmp_path):
    engine = _FakeEngine(unlock_error=SQLAlchemyError('connection lost'))
    monkeypatch.setattr(nrt, 'require_async_engine', lambda: engine)
    _patch_session(monkeypatch)

    async def _run(db):
        return {'deleted_total': 0, 'analyzed': False, 'errors': []}

    monkeypatch.setattr(nrt, 'run_retention_once', _run)
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'state.json')
    await nrt.numbering_audit_retention_task({})
    assert engine.conns[0].invalidated is True


def _write_signal(path, **fields):
    path.write_text(json.dumps(fields), encoding='utf-8')
    return path


def test_signal_missing_and_disabled_are_neutral(monkeypatch, tmp_path):
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'absent.json')
    assert nrt.numbering_audit_retention_signal()['note'] == 'not_yet_run'
    monkeypatch.setattr(settings, 'NUMBERING_AUDIT_RETENTION_DAYS', 0, raising=False)
    assert nrt.numbering_audit_retention_signal()['disabled'] is True


def test_signal_stale_pending_and_corrupt_are_not_ok(monkeypatch, tmp_path):
    path = _write_signal(
        tmp_path / 'state.json',
        last_success_at=(datetime.now(UTC) - timedelta(days=nrt.STALE_DAYS + 1)).isoformat(),
        pending_errors=[],
    )
    monkeypatch.setattr(nrt, 'STATE_PATH', path)
    assert nrt.numbering_audit_retention_signal()['ok'] is False
    path = _write_signal(
        path, last_success_at=datetime.now(UTC).isoformat(),
        pending_errors=[{'error': 'archive_failed'}],
    )
    signal = nrt.numbering_audit_retention_signal()
    assert signal['ok'] is False and signal['pending_error_count'] == 1
    path.write_text('{broken', encoding='utf-8')
    assert nrt.numbering_audit_retention_signal()['note'] == 'state_unreadable'


def test_signal_shape_is_fixed_across_states(monkeypatch, tmp_path):
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'absent.json')
    shapes = [set(nrt.numbering_audit_retention_signal())]
    monkeypatch.setattr(settings, 'NUMBERING_AUDIT_RETENTION_DAYS', 0, raising=False)
    shapes.append(set(nrt.numbering_audit_retention_signal()))
    assert shapes[0] == shapes[1]
