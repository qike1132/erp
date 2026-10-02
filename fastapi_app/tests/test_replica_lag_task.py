"""只读副本延迟巡检任务（replica_lag_task）—— 「不抛错退出」契约回归。

模块 docstring 承诺：ARQ 任务本身不抛错退出，否则 max_tries 耗尽后 cron 会被丢弃、
监控静默失效（比 lag 超阈更糟）。此前只有 asyncpg.connect 被 try 包住，连接成功之后的
查询失败会逃逸（副本卡住触发 8s statement_timeout → QueryCanceledError；链路中断 →
InterfaceError。asyncpg 异常不继承内置 OSError/ConnectionError）。
"""
from datetime import timedelta

import pytest

from fastapi_app.tasks import replica_lag_task as mod


class _FakeConn:
    """按序返回 fetchval 结果的假连接；元素为 Exception 时抛出。"""

    def __init__(self, fetchval_results=None, *, close_raises=False):
        self._results = list(fetchval_results or [])
        self.closed = False
        self._close_raises = close_raises

    async def execute(self, *_a, **_kw):
        return None

    async def fetchval(self, *_a, **_kw):
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True
        if self._close_raises:
            raise RuntimeError('close failed')


def _wire(monkeypatch, conn):
    import asyncpg

    monkeypatch.setattr(
        mod.settings, 'ASYNC_DATABASE_REPLICA_URL',
        'postgresql+asyncpg://u:p@127.0.0.1:5433/erp_system',
    )

    async def _connect(**_kw):
        return conn

    monkeypatch.setattr(asyncpg, 'connect', _connect)


@pytest.mark.asyncio
async def test_query_failure_returns_instead_of_raising(monkeypatch):
    """回归 L-2：连接成功后查询失败不得逃逸成任务失败。"""
    conn = _FakeConn([RuntimeError('QueryCanceledError: statement timeout')])
    _wire(monkeypatch, conn)

    result = await mod.replica_lag_task({})

    assert result == {'ok': False, 'error': 'query-failed'}
    assert conn.closed is True, '查询失败也必须关闭连接'


@pytest.mark.asyncio
async def test_close_failure_does_not_raise(monkeypatch):
    """关连接失败同样不应让任务失败（连接随进程回收）。"""
    conn = _FakeConn([True, timedelta(seconds=3)], close_raises=True)
    _wire(monkeypatch, conn)

    result = await mod.replica_lag_task({})

    assert result == {'ok': True, 'lag_seconds': 3.0}


@pytest.mark.asyncio
async def test_happy_path_reports_lag(monkeypatch):
    conn = _FakeConn([True, timedelta(seconds=12.5)])
    _wire(monkeypatch, conn)

    result = await mod.replica_lag_task({})

    assert result == {'ok': True, 'lag_seconds': 12.5}
    assert conn.closed is True


@pytest.mark.asyncio
async def test_not_in_recovery_is_reported_without_raising(monkeypatch):
    conn = _FakeConn([False])
    _wire(monkeypatch, conn)

    result = await mod.replica_lag_task({})

    assert result == {'ok': False, 'error': 'not-in-recovery'}
    assert conn.closed is True


@pytest.mark.asyncio
async def test_no_replica_url_skips(monkeypatch):
    monkeypatch.setattr(mod.settings, 'ASYNC_DATABASE_REPLICA_URL', '')

    assert await mod.replica_lag_task({}) == {'skipped': 'no-replica-url'}
