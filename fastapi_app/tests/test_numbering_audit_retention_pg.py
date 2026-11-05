"""numbering_audit 保留治理：隔离 PostgreSQL 真库验证。"""
from __future__ import annotations

import gzip
import json
import socket
from contextlib import suppress
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from fastapi_app.core.config import settings
from fastapi_app.tasks import numbering_audit_retention_task as nrt

pytestmark = [pytest.mark.integration, pytest.mark.db]

_ID_LO, _ID_HI = 900_000, 900_999
_OLD = datetime(1000, 1, 1, 3, 0, tzinfo=UTC)
_FUTURE = datetime(2099, 1, 1, 3, 0, tzinfo=UTC)
_NOW = datetime(1000, 2, 15, 12, 0, tzinfo=UTC)
#: 真实入口用真实 now 会算出「今天−30天」，把共享测试库里所有 30 天前的行一起删掉。
#: 入口用例必须把 cutoff 钉在这个哨兵日：只覆盖 _OLD、不碰 _FUTURE 与其它数据。
_SENTINEL_CUTOFF = datetime(1000, 2, 1, tzinfo=UTC)


def _test_db_url() -> str:
    import os

    url = os.getenv('TEST_DATABASE_URL') or settings.ASYNC_DATABASE_URL
    from fastapi_app.tests._test_db_guard import assert_is_test_database

    assert_is_test_database(url)
    return url


def _redact(url: str) -> str:
    return url.rsplit('@', 1)[-1]


def _tcp_reachable(url: str, timeout: float = 2.0) -> bool:
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    try:
        with socket.create_connection(
            (parsed.host or '127.0.0.1', parsed.port or 5432), timeout=timeout,
        ):
            return True
    except OSError:
        return False


async def _purge(conn) -> None:
    await conn.execute(text(
        'DELETE FROM numbering_audit WHERE id BETWEEN :lo AND :hi'),
        {'lo': _ID_LO, 'hi': _ID_HI})


async def _require_no_foreign_expired_rows(conn) -> None:
    count = (await conn.execute(text(
        'SELECT count(*) FROM numbering_audit WHERE checked_at < :cutoff AND NOT id BETWEEN :lo AND :hi'),
        {'cutoff': _NOW, 'lo': _ID_LO, 'hi': _ID_HI},
    )).scalar()
    if count:
        pytest.skip(f'测试库在本用例历史窗口已有 {count} 行，跳过以免误删')


@pytest_asyncio.fixture
async def pg_engine():
    url = _test_db_url()
    if not _tcp_reachable(url):
        pytest.skip(f'测试库端口不可达（{_redact(url)}）')
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            present = (await conn.execute(
                text("SELECT to_regclass('public.numbering_audit')"))).scalar()
            await _require_no_foreign_expired_rows(conn)
            await conn.rollback()
    except Exception as exc:
        with suppress(Exception):
            await engine.dispose()
        pytest.skip(f'测试库不可用（{type(exc).__name__}）')
    if present is None:
        with suppress(Exception):
            await engine.dispose()
        pytest.skip('测试库缺 numbering_audit 表')
    async with engine.begin() as conn:
        await _purge(conn)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await _purge(conn)
        await engine.dispose()


async def _insert(conn, ids: list[int], checked_at: datetime) -> None:
    for row_id in ids:
        await conn.execute(text(
            'INSERT INTO numbering_audit (id, scope, counter_behind, detail, checked_at) '
            'VALUES (:id, :scope, :behind, :detail, :checked_at)'
        ), {
            'id': row_id, 'scope': f'PG-{row_id}', 'behind': 0,
            'detail': f'pg-it-{row_id}', 'checked_at': checked_at,
        })


async def test_archive_and_delete_only_expired_sentinel_rows(pg_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'NUMBERING_AUDIT_RETENTION_DAYS', 30, raising=False)
    old_ids = [900_001, 900_002, 900_003]
    future_ids = [900_101, 900_102]
    async with pg_engine.begin() as conn:
        await _insert(conn, old_ids, _OLD)
        await _insert(conn, future_ids, _FUTURE)

    async with AsyncSession(bind=pg_engine, expire_on_commit=False) as db:
        report = await nrt.run_retention_once(
            db, now=_NOW, archive_dir=tmp_path, state_path=tmp_path / 'state.json')

    assert report['errors'] == []
    assert report['deleted_total'] == len(old_ids)
    archives = list(tmp_path.glob('numbering_audit_before_*.jsonl.gz'))
    assert len(archives) == 1
    async with pg_engine.connect() as conn:
        db_name = (await conn.execute(text('SELECT current_database()'))).scalar()
    assert archives[0].name == f'numbering_audit_before_{db_name}_10000116.jsonl.gz', (
        '归档文件名必须带真实库名，否则生产库与恢复演练库会互相复用 ID 集'
    )
    with gzip.open(archives[0], 'rt', encoding='utf-8') as gz:
        archived = [json.loads(line)['id'] for line in gz.read().splitlines()]
    assert sorted(archived) == old_ids

    async with pg_engine.connect() as conn:
        left_old = (await conn.execute(text(
            'SELECT count(*) FROM numbering_audit WHERE id = ANY(:ids)'), {'ids': old_ids},
        )).scalar()
        left_future = (await conn.execute(text(
            'SELECT count(*) FROM numbering_audit WHERE id = ANY(:ids)'), {'ids': future_ids},
        )).scalar()
    assert left_old == 0
    assert left_future == len(future_ids)

    from fastapi_app.api.v1.endpoints.numbering_audit import latest_audit
    async with AsyncSession(bind=pg_engine, expire_on_commit=False) as db:
        latest = await latest_audit(limit=300, db=db)
    scopes = {item['scope'] for item in latest['items']}
    assert {f'PG-{row_id}' for row_id in future_ids} <= scopes
    assert not {f'PG-{row_id}' for row_id in old_ids} & scopes


async def test_real_entry_point_commits_batches(pg_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'NUMBERING_AUDIT_RETENTION_DAYS', 30, raising=False)
    ids = [900_201, 900_202, 900_203]
    async with pg_engine.begin() as conn:
        await _insert(conn, ids, _OLD)
    monkeypatch.setattr(nrt, 'require_async_engine', lambda: pg_engine)
    monkeypatch.setattr(nrt, 'archive_dir_path', lambda _raw=None: tmp_path)
    monkeypatch.setattr(nrt, 'STATE_PATH', tmp_path / 'state.json')
    # 钉住 cutoff：否则真实入口按「今天−30天」清掉共享测试库里所有历史行。
    monkeypatch.setattr(nrt, 'retention_cutoff', lambda _now=None: _SENTINEL_CUTOFF)

    report = await nrt.numbering_audit_retention_task({})
    assert report['archive_key'].endswith('1000-02-01'), '窗口未按哨兵 cutoff 计算'
    assert report['deleted_total'] == len(ids)
    async with pg_engine.connect() as conn:
        left = (await conn.execute(text(
            'SELECT count(*) FROM numbering_audit WHERE id = ANY(:ids)'), {'ids': ids},
        )).scalar()
    assert left == 0, '真实入口返回后行仍存在，说明分批 commit 未真正落盘'
