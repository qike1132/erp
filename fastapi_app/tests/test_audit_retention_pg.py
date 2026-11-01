"""audit_log 保留治理：真实 PostgreSQL 集成（补单元测试的替身盲区）。

复审 M-4 的缺口：模块里最危险的三条 SQL——月键
``to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM')``、``DELETE ... WHERE id = ANY(:ids)``
的**列表绑定**、以及分批 DELETE——在单元测试里从未真正发给 PostgreSQL。替身
再「笨」也证明不了「参数能被驱动层正确适配」：``ANY(:ids)`` 传 Python list 依赖
psycopg 的数组推断，写错在单测里永远是绿的。本文件把这条链路打到真库上：

1. 月桶口径：PG 侧的月键必须与 Python UTC 口径一致（会话时区为 Asia/Shanghai
   时也不能漂）；
2. 列表绑定：``id = ANY(:ids)`` 真的能删掉且**只删**这些 id；
3. 端到端：2019-03 的 3 行被归档 → 删除，2099-01 的哨兵行原样保留。

数据隔离：只碰 ``created_at`` 落在 2019-03（过期）与 2099-01（未来）两个哨兵
区间的行，前后各按这两个窗口清理一次；库名必须过 ``_test_db_guard`` 硬闸
（非 ``*_test`` 直接 pytest.exit）。测试库不可达时 skip——本机的聚焦跑用
stub .env（占位 URL），CI 才真跑。
"""
from __future__ import annotations

import gzip
import json
from contextlib import suppress
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from fastapi_app.core.config import settings
from fastapi_app.tasks import audit_retention_task as art

pytestmark = [pytest.mark.integration, pytest.mark.db]

_OLD_START = datetime(2019, 3, 1, tzinfo=UTC)
_OLD_END = datetime(2019, 4, 1, tzinfo=UTC)
_FUTURE_START = datetime(2099, 1, 1, tzinfo=UTC)
#: 本文件专用 id 段：清理只碰这一段，绝不按时间窗删其它测试/其它套件的数据。
_ID_LO, _ID_HI = 900_000, 999_999
#: cutoff = 2019-06-15 → 2019-03 整月过期；2099-01 远在窗口内。
_NOW = datetime(2020, 6, 15, 12, 0, tzinfo=UTC)


def _test_db_url() -> str:
    import os

    url = os.getenv('TEST_DATABASE_URL') or settings.ASYNC_DATABASE_URL
    from fastapi_app.tests._test_db_guard import assert_is_test_database

    assert_is_test_database(url)
    return url


def _redact(url: str) -> str:
    """日志里只留 host/db，绝不回显口令。"""
    return url.rsplit('@', 1)[-1]


def _tcp_reachable(url: str, timeout: float = 2.0) -> bool:
    """先探端口：连接失败是环境条件，应当在创建驱动连接前就判定成 skip。"""
    import socket

    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    try:
        with socket.create_connection(
                (parsed.host or '127.0.0.1', parsed.port or 5432), timeout=timeout):
            return True
    except OSError:
        return False


async def _purge(conn) -> None:
    """只清本文件的哨兵 id 段（900000-999999），绝不按时间窗删别人的数据。"""
    await conn.execute(text(
        'DELETE FROM audit_log WHERE id BETWEEN :lo AND :hi'), {'lo': _ID_LO, 'hi': _ID_HI})


@pytest_asyncio.fixture
async def pg_engine():
    """连测试库；不可达/无权限/缺表则 skip（不留半截状态）。

    ``dispose()`` 本身也可能再抛（连接已被对端重置），所以清理走 suppress——
    否则「连不上」会被降级成 ERROR 而不是 skip，把环境问题伪装成产品缺陷。
    """
    url = _test_db_url()
    if not _tcp_reachable(url):
        pytest.skip(f'测试库端口不可达，跳过真库集成（{_redact(url)}）')
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            present = (await conn.execute(
                text("SELECT to_regclass('public.audit_log')"))).scalar()
    except Exception as exc:  # defensive: 探针失败（认证/建连/查询）一律 skip，环境问题不能报成产品缺陷
        with suppress(Exception):
            await engine.dispose()
        pytest.skip(f'测试库不可用，跳过真库集成（{type(exc).__name__}）')
    if present is None:
        with suppress(Exception):
            await engine.dispose()
        pytest.skip('测试库缺 audit_log 表（未跑迁移），跳过真库集成')

    async with engine.begin() as conn:
        await _purge(conn)
    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await _purge(conn)
        await engine.dispose()


async def _insert(conn, ids: list[int], ts: datetime) -> None:
    for row_id in ids:
        await conn.execute(text(
            'INSERT INTO audit_log (id, user_id, username, action, resource_type, '
            'resource_id, detail, ip_address, user_agent, request_id, status_code, created_at) '
            'VALUES (:id, 1, :u, :a, :r, :rid, :d, :ip, :ua, :rq, 200, :ts)'
        ), {
            'id': row_id, 'u': 'pg-it', 'a': 'login', 'r': 'user', 'rid': str(row_id),
            'd': '{"k":"v"}', 'ip': '127.0.0.1', 'ua': 'pytest', 'rq': f'req-{row_id}',
            'ts': ts,
        })


async def test_month_bucket_matches_python_utc_on_real_pg(pg_engine):
    """PG 侧月键 == Python 侧 UTC 月键（会话时区非 UTC 时也必须一致）。

    生产会话时区实测 Asia/Shanghai；``to_char(timestamptz, ...)`` 按会话时区折算，
    所以 SQL 里必须带 ``AT TIME ZONE 'UTC'``。单测只能断言「SQL 文本里有这串
    字符」，只有真库能证明「算出来的月份对得上」。这里显式把会话时区钉成
    Asia/Shanghai，让两种口径在**同一行**上给出不同答案——判别力不依赖机器配置。
    """
    async with pg_engine.begin() as conn:
        # 月末 23:30 UTC：+08 会话口径下是次月 1 日 07:30，只有 UTC 口径留在 03 月。
        await _insert(conn, [900_001], datetime(2019, 3, 31, 23, 30, tzinfo=UTC))

    async with pg_engine.connect() as conn:
        await conn.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
        row = (await conn.execute(text(
            "SELECT to_char(created_at, 'YYYY-MM'), "
            "       to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM') "
            'FROM audit_log WHERE id = 900001'))).one()
        await conn.rollback()
    assert row[0] == '2019-04', '会话时区口径应把该行算成 2019-04（这正是必须显式 UTC 的原因）'
    assert row[1] == '2019-03'

    async with AsyncSession(bind=pg_engine, expire_on_commit=False) as db:
        plans = await art.compute_retention_plan(db, _NOW)
    assert '2019-03' in [p['month'] for p in plans], (
        f'UTC 口径应把 2019-03-31T23:30Z 归入 2019-03，实际 {[p["month"] for p in plans]}')


async def test_archive_then_delete_end_to_end_on_real_pg(pg_engine, tmp_path):
    """真库端到端：归档 3 行 → 按归档 id 删除 → 未来行原样保留。

    这条同时验证 `id = ANY(:ids)` 的**列表绑定**（Python list → int 数组）：
    绑定写错在 psycopg 侧会直接抛类型错误，替身永远发现不了。
    """
    old_ids = [910_001, 910_002, 910_003]
    future_ids = [910_101, 910_102]
    async with pg_engine.begin() as conn:
        await _insert(conn, old_ids, datetime(2019, 3, 15, 3, 0, tzinfo=UTC))
        await _insert(conn, future_ids, datetime(2099, 1, 15, 3, 0, tzinfo=UTC))

    async with AsyncSession(bind=pg_engine, expire_on_commit=False) as db:
        report = await art.run_retention_once(
            db, now=_NOW, archive_dir=tmp_path, state_path=tmp_path / 'state.json')

    assert report['errors'] == []
    entry = next(m for m in report['months'] if m['month'] == '2019-03')
    assert entry['archive_rows'] == 3
    assert entry['deleted'] == 3

    gz = tmp_path / 'audit_log_201903.jsonl.gz'
    with gzip.open(gz, 'rt', encoding='utf-8') as f:   # 读到底即 CRC 校验
        archived = [json.loads(ln)['id'] for ln in f.read().splitlines()]
    assert sorted(archived) == old_ids

    async with pg_engine.connect() as conn:
        left_old = (await conn.execute(
            text('SELECT count(*) FROM audit_log WHERE id = ANY(:ids)'), {'ids': old_ids}
        )).scalar()
        left_future = (await conn.execute(
            text('SELECT count(*) FROM audit_log WHERE id = ANY(:ids)'), {'ids': future_ids}
        )).scalar()
    assert left_old == 0, '归档过的行必须被删干净（否则下一轮重复归档）'
    assert left_future == len(future_ids), '窗口外的行绝不能被删'


async def test_task_persists_deletions_through_entry_point(pg_engine, tmp_path, monkeypatch):
    """走**真实入口** ``audit_retention_task``：返回后另开连接必须查不到那批行。

    这是复审 Blocker 的定点回归。取锁那条 ``SELECT pg_try_advisory_lock`` 会让
    连接 autobegin，若会话不与 ``join_transaction_mode='control_fully'`` 显式接管
    事务，SQLAlchemy 会退到 ``rollback_only``：``commit()`` 只 flush 不发 COMMIT，
    每批删除堆在外部事务里，最后被 finally 的 ``rollback()`` 全部丢掉——任务
    报「删了 N 行」、库里一行没少、窗口复核在同一事务里自证清白、健康端点全程绿。

    上面那条用例绑的是 ``AsyncSession(bind=pg_engine)``（没有预置事务），commit
    天然生效，**覆盖不到这个缝**；必须走入口才有判别力。
    """
    ids = [920_001, 920_002, 920_003]
    async with pg_engine.begin() as conn:
        await _insert(conn, ids, datetime(2019, 3, 15, 3, 0, tzinfo=UTC))

    monkeypatch.setattr(art, 'require_async_engine', lambda: pg_engine)
    monkeypatch.setattr(art, 'archive_dir_path', lambda _raw=None: tmp_path)
    monkeypatch.setattr(art, 'STATE_PATH', tmp_path / 'state.json')

    report = await art.audit_retention_task({})
    assert report['deleted_total'] >= len(ids)

    # pg_engine 是 NullPool：这条连接是全新的，只看得到已提交的数据
    async with pg_engine.connect() as conn:
        left = (await conn.execute(
            text('SELECT count(*) FROM audit_log WHERE id = ANY(:ids)'), {'ids': ids}
        )).scalar()
    assert left == 0, '任务返回后行还在 ⇒ 每批 commit 没真正提交（被 finally 回滚掉了）'
