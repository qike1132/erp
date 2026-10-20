"""调度任务的 `last_status` 必须落到终态，不能永远停在 'running'。

背景（/backup 审计，high；生产库实测）
-------------------------------------
`scheduler_poller` 入队时写 `last_status='running'`，**全仓库再无第二处写这个字段**。
生产库 `backup_schedule` 的两行（full / incremental）实测状态都是 'running'，
`last_run_at` 却停在当天 02:00 —— 任务早已结束，状态却显示"执行中"。

修法：入队时给 job 一个可解析的 id（`sched:{schedule_id}:{窗口}`），ARQ 0.28 的
on_job_end 回调按任务边界记录的成败分流并把终态写回；任务函数签名不动。
"""
from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi_app.core import schedule_status as ss

_CORE = Path(ss.__file__)
_CALLBACKS = _CORE.parent / 'arq_callbacks.py'
_TASKS = _CORE.parent.parent / 'tasks' / 'backup_tasks.py'


# ---------------------------------------------------------------------------
# job id 编解码
# ---------------------------------------------------------------------------

def test_job_id_round_trip() -> None:
    job_id = ss.schedule_job_id(18, datetime(2026, 9, 28, 2, 0))

    assert job_id.startswith(ss.SCHEDULE_JOB_ID_PREFIX)
    assert ss.parse_schedule_job_id(job_id) == 18


def test_job_id_carries_hour_window() -> None:
    """同一小时内重复入队 == 同一个 job id（ARQ 去重），跨小时不同。"""
    a = ss.schedule_job_id(7, datetime(2026, 9, 28, 2, 1))
    b = ss.schedule_job_id(7, datetime(2026, 9, 28, 2, 59))
    c = ss.schedule_job_id(7, datetime(2026, 9, 28, 3, 0))

    assert a == b
    assert a != c


@pytest.mark.parametrize('job_id', [None, '', 'other:1', 'sync_import', 'sched:', 'sched:abc:1'])
def test_non_schedule_job_ids_are_ignored(job_id) -> None:
    assert ss.parse_schedule_job_id(job_id) is None


# ---------------------------------------------------------------------------
# 终态回写
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeDb:
    def __init__(self, row) -> None:
        self.row = row
        self.committed = False

    async def execute(self, _stmt):
        return _FakeResult(self.row)

    async def commit(self) -> None:
        self.committed = True


class _FakeCtx:
    def __init__(self, db) -> None:
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc):
        return False


def _patch_db(monkeypatch: pytest.MonkeyPatch, row) -> _FakeDb:
    from fastapi_app.core import database

    db = _FakeDb(row)
    monkeypatch.setattr(database, 'get_async_db_context', lambda: _FakeCtx(db))
    return db


async def test_success_writes_terminal_status(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(last_status=ss.STATUS_RUNNING)
    db = _patch_db(monkeypatch, row)

    ok = await ss.mark_schedule_finished(ss.schedule_job_id(18, datetime(2026, 9, 28, 2, 0)), ss.STATUS_SUCCESS)

    assert ok is True
    assert row.last_status == ss.STATUS_SUCCESS
    assert db.committed is True


async def test_failure_writes_terminal_status(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(last_status=ss.STATUS_RUNNING)
    _patch_db(monkeypatch, row)

    await ss.mark_schedule_finished(ss.schedule_job_id(19, datetime(2026, 9, 28, 2, 0)), ss.STATUS_FAILED)

    assert row.last_status == ss.STATUS_FAILED


async def test_missing_row_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _patch_db(monkeypatch, None)

    ok = await ss.mark_schedule_finished(ss.schedule_job_id(404, datetime(2026, 9, 28, 2, 0)), ss.STATUS_SUCCESS)

    assert ok is False
    assert db.committed is False


async def test_non_schedule_job_touches_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom():  # pragma: no cover - 不得被调用
        raise AssertionError('非调度任务不该开数据库连接')

    from fastapi_app.core import database

    monkeypatch.setattr(database, 'get_async_db_context', _boom)

    assert await ss.mark_schedule_finished('manual_full_backup:xyz', ss.STATUS_SUCCESS) is False


async def test_db_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """回写失败绝不能冒泡到 ARQ 回调（那会掩盖原始失败/影响告警）。"""
    from fastapi_app.core import database

    class _Boom:
        async def __aenter__(self):
            raise RuntimeError('db down')

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(database, 'get_async_db_context', lambda: _Boom())

    assert await ss.mark_schedule_finished(ss.schedule_job_id(18, datetime(2026, 9, 28)), ss.STATUS_FAILED) is False


# ---------------------------------------------------------------------------
# 接线守卫：入队带前缀、回调写终态
# ---------------------------------------------------------------------------

def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding='utf-8'))


def _calls_in(path: Path, func_name: str) -> set[str]:
    """函数体内所有被调用的「函数名」（含属性调用）。"""
    for node in ast.walk(_tree(path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return {
                (n.func.id if isinstance(n.func, ast.Name) else n.func.attr)
                for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))
            }
    raise AssertionError(f'{func_name} 不存在于 {path.name}')


def test_poller_enqueues_with_schedule_job_id() -> None:
    src = _TASKS.read_text(encoding='utf-8')

    assert '_job_id=schedule_job_id(' in src, (
        'scheduler_poller 入队必须带 sched: 前缀的 job id，否则回调无法反解 schedule_id'
    )
    assert 'schedule_job_id' in _calls_in(_TASKS, 'scheduler_poller')


def test_callbacks_mark_terminal_status() -> None:
    calls = _calls_in(_CALLBACKS, 'on_job_end')
    assert '_mark_schedule_outcome' in calls
    assert '_handle_job_failure' in calls, 'on_job_end 必须按失败分支调用 DLQ/告警逻辑'


def test_failed_handler_marks_failed_status() -> None:
    src = _CALLBACKS.read_text(encoding='utf-8')
    tree = _tree(_CALLBACKS)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == '_handle_job_failure':
            body = ast.get_source_segment(src, node) or ''
            assert '_mark_schedule_outcome' in body
            assert 'STATUS_FAILED' in body, '失败处理必须写 failed，而不是复用了 success'
            return
    raise AssertionError('_handle_job_failure 不存在')
