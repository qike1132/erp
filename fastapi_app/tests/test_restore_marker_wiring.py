"""B2 回归锁（接线层）：恢复流程必须在 DROP 前落标记、只在成功后清除。

`fastapi_app/tests/test_restore_guard_fail_closed.py` 锁的是标记模块自身语义；
本文件锁的是 `restore_database_via_psql()` **是否真的按那个语义调用**：

* 标记写不进去 → 直接返回错误，**不调** `_rebuild_database_with_admin`（不 DROP）；
* 导入成功（status=ok）→ `mark_restore_finished(success=True)`；
* 导入失败 / partial / 重建失败 → `mark_restore_finished(success=False, failure_stage=...)`。

历史实现用「外层 finally 无条件 mark_restore_finished()」，三个分支都会把标记清掉，
下次启动再也看不到「数据库可能是空壳」。
"""
from __future__ import annotations

import pytest

from fastapi_app.services.backup import dump
from fastapi_app.services.backup import restore_guard as guard


class _FakeStream:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def read(self, _n: int) -> bytes:  # pragma: no cover - 由 fake worker 取代
        return b''


@pytest.fixture
def restore_env(monkeypatch):
    """把恢复流程的所有外部依赖打桩，只保留被断言的编排逻辑。"""
    stream = _FakeStream()
    calls: dict[str, list] = {'rebuild': [], 'finished': []}

    monkeypatch.setattr(dump, '_open_dump_stream', lambda _zf: (stream, object(), b'', 0))
    monkeypatch.setattr(dump, '_resolve_db_env', lambda: {
        'db_host': 'h', 'db_port': '5432', 'db_user': 'u', 'db_name': 'erp_system',
        'admin_user': 'postgres', 'admin_env': {}, 'env': {},
    })

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(dump, '_release_app_connections', _noop)
    monkeypatch.setattr(dump, '_drain_and_terminate_connections', _noop)
    monkeypatch.setattr(dump, '_await_psql_progress', _noop)

    def _fake_finished(*, success, failure_stage=None):
        calls['finished'].append((success, failure_stage))
        return True

    monkeypatch.setattr(guard, 'mark_restore_finished', _fake_finished)
    monkeypatch.setattr(dump, '_FakeStream', _FakeStream, raising=False)

    def _rebuild(result):
        async def _fn(**_kwargs):
            calls['rebuild'].append(1)
            return result
        return _fn

    return SimpleEnv(stream, calls, _rebuild, monkeypatch)


class SimpleEnv:
    def __init__(self, stream, calls, rebuild_factory, monkeypatch):
        self.stream = stream
        self.calls = calls
        self._rebuild_factory = rebuild_factory
        self._mp = monkeypatch

    def rebuild_returns(self, result):
        self._mp.setattr(dump, '_rebuild_database_with_admin', self._rebuild_factory(result))

    def psql_returns(self, result: dict):
        def _worker(_args, _env, _stream, _first, state, out):
            state['stream_done'] = True
            out.update(result)

        self._mp.setattr(dump, '_psql_import_worker', _worker)


@pytest.mark.asyncio
async def test_aborts_before_drop_when_marker_cannot_be_written(restore_env, monkeypatch):
    def _boom(*_a, **_k):
        raise guard.RestoreMarkerError('disk full')

    monkeypatch.setattr(guard, 'mark_restore_started', _boom)
    restore_env.rebuild_returns(None)

    result = await dump.restore_database_via_psql(object(), db=None, task_id=None)

    assert result['status'] == 'error'
    assert '拒绝' in result['error']
    assert restore_env.calls['rebuild'] == [], '标记写不进去时绝不能 DROP 数据库'
    assert restore_env.stream.closed, '中止时必须关闭 gzip 流（句柄泄漏）'
    assert restore_env.calls['finished'] == [], '尚未开始就中止，不得再"结束"一次标记'


@pytest.mark.asyncio
async def test_success_clears_marker(restore_env, monkeypatch):
    monkeypatch.setattr(guard, 'mark_restore_started', lambda *_a, **_k: None)
    restore_env.rebuild_returns(None)
    restore_env.psql_returns({'rc': 0})

    result = await dump.restore_database_via_psql(object(), db=None, task_id=None)

    assert result['status'] == 'ok'
    assert restore_env.calls['finished'] == [(True, 'done')]


@pytest.mark.asyncio
async def test_psql_failure_keeps_marker(restore_env, monkeypatch):
    monkeypatch.setattr(guard, 'mark_restore_started', lambda *_a, **_k: None)
    restore_env.rebuild_returns(None)
    restore_env.psql_returns({'rc': 1, 'stderr': b'ERROR: boom'})

    result = await dump.restore_database_via_psql(object(), db=None, task_id=None)

    assert result['status'] == 'error'
    assert restore_env.calls['finished'] == [(False, 'import')]


@pytest.mark.asyncio
async def test_partial_import_keeps_marker(restore_env, monkeypatch):
    """partial = 有语句失败，库内容不可信，不得当作成功清除标记。"""
    monkeypatch.setattr(guard, 'mark_restore_started', lambda *_a, **_k: None)
    restore_env.rebuild_returns(None)
    restore_env.psql_returns({'rc': 0, 'stderr': b'ERROR: one statement failed'})

    result = await dump.restore_database_via_psql(object(), db=None, task_id=None)

    assert result['status'] == 'partial'
    assert restore_env.calls['finished'] == [(False, 'import')]


@pytest.mark.asyncio
async def test_rebuild_failure_keeps_marker(restore_env, monkeypatch):
    monkeypatch.setattr(guard, 'mark_restore_started', lambda *_a, **_k: None)
    restore_env.rebuild_returns({'status': 'error', 'error': 'CREATE DATABASE 失败'})

    result = await dump.restore_database_via_psql(object(), db=None, task_id=None)

    assert result['status'] == 'error'
    assert restore_env.calls['finished'] == [(False, 'rebuild_db')]
