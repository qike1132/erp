"""ARQ 0.28 钩子契约与任务成败分流回归。

背景（审计 P1-13）
------------------
ARQ 0.28 的 Worker 只接受 ``on_job_start`` / ``on_job_end``，没有 ``on_job_failed``。
旧配置把 ``on_job_started`` / ``on_job_failed`` 挂到 WorkerSettings 上，构造 Worker 时
被静默丢弃：开始时间永不记录、失败永不进 DLQ、失败调度任务被 ``on_job_end`` 误标成功。

修法：注册任务时包一层 ``_tracked_job``，把成败写进 ``ctx['_job_outcome']``；
``on_job_end`` 按 success / failed / retrying 分流。
"""
from __future__ import annotations

import asyncio

import pytest
from arq import Retry
from arq.worker import create_worker

from fastapi_app.core import arq_callbacks
from fastapi_app.core.arq_app import MAX_TRIES, WorkerSettings, _tracked_job
from fastapi_app.core.schedule_status import STATUS_FAILED, STATUS_SUCCESS

# ---------------------------------------------------------------------------
# 钩子接线：必须是 ARQ 认识的真名
# ---------------------------------------------------------------------------

def test_worker_settings_uses_real_arq_hooks() -> None:
    assert WorkerSettings.on_job_start is arq_callbacks.on_job_start
    assert WorkerSettings.on_job_end is arq_callbacks.on_job_end
    assert not hasattr(WorkerSettings, 'on_job_started')
    assert not hasattr(WorkerSettings, 'on_job_failed')


def test_arq_worker_accepts_the_hooks() -> None:
    worker = create_worker(WorkerSettings)

    assert worker.on_job_start is arq_callbacks.on_job_start
    assert worker.on_job_end is arq_callbacks.on_job_end


def test_registered_job_names_are_preserved() -> None:
    names = [f.__name__ for f in WorkerSettings.functions]

    for expected in ('batch_import_orders_task', 'scheduler_poller', 'inventory_reconcile_task'):
        assert expected in names
    assert len(names) == len(set(names))


def test_cron_job_names_are_preserved() -> None:
    names = [cj.name for cj in WorkerSettings.cron_jobs]

    # ARQ 的 CronJob.name 形如 cron:<函数名>，不是 cron_schedules 里的展示名。
    assert 'cron:scheduler_poller' in names
    assert 'cron:ensure_readonly_grants_task' in names


# ---------------------------------------------------------------------------
# 任务边界：成败标记
# ---------------------------------------------------------------------------

async def test_success_marks_success() -> None:
    async def demo(ctx):
        ctx['ran'] = True
        return 42

    ctx: dict = {'job_id': 'j1', 'job_try': 1}
    result = await _tracked_job(demo, MAX_TRIES)(ctx)

    assert result == 42
    assert ctx['ran'] is True
    assert ctx['_job_outcome'] == 'success'
    assert ctx['_job_function'] == 'demo'
    assert ctx['_max_tries'] == MAX_TRIES


async def test_normal_exception_marks_failed() -> None:
    async def demo(ctx):
        raise ValueError('boom')

    ctx: dict = {'job_id': 'j2', 'job_try': 1}
    with pytest.raises(ValueError):
        await _tracked_job(demo, MAX_TRIES)(ctx)

    assert ctx['_job_outcome'] == 'failed'
    assert isinstance(ctx['_job_exception'], ValueError)


async def test_retry_before_last_try_is_not_terminal() -> None:
    async def demo(ctx):
        raise Retry()

    ctx: dict = {'job_id': 'j3', 'job_try': 1}
    with pytest.raises(Retry):
        await _tracked_job(demo, 3)(ctx)

    assert ctx['_job_outcome'] == 'retrying'
    assert '_job_exception' not in ctx


async def test_retry_on_last_try_marks_failed() -> None:
    async def demo(ctx):
        raise Retry()

    ctx: dict = {'job_id': 'j4', 'job_try': 3}
    with pytest.raises(Retry):
        await _tracked_job(demo, 3)(ctx)

    assert ctx['_job_outcome'] == 'failed'
    assert isinstance(ctx['_job_exception'], Retry)


async def test_cancelled_job_is_retryable_not_terminal() -> None:
    async def demo(ctx):
        raise asyncio.CancelledError()

    ctx: dict = {'job_id': 'j5', 'job_try': 1}
    with pytest.raises(asyncio.CancelledError):
        await _tracked_job(demo, MAX_TRIES)(ctx)

    assert ctx['_job_outcome'] == 'retrying'


# ---------------------------------------------------------------------------
# on_job_end 分流
# ---------------------------------------------------------------------------

async def _capture_schedule(monkeypatch):
    calls: list[str] = []

    async def fake(ctx, status):
        calls.append(status)

    monkeypatch.setattr(arq_callbacks, '_mark_schedule_outcome', fake)
    return calls


async def test_on_job_end_success_writes_success(monkeypatch) -> None:
    calls = await _capture_schedule(monkeypatch)

    await arq_callbacks.on_job_end({'job_id': 'sched:1:0', '_job_outcome': 'success'})

    assert calls == [STATUS_SUCCESS]


async def test_on_job_end_retrying_writes_nothing(monkeypatch) -> None:
    calls = await _capture_schedule(monkeypatch)

    await arq_callbacks.on_job_end({'job_id': 'sched:1:0', '_job_outcome': 'retrying'})

    assert calls == []


async def test_on_job_end_failed_writes_failed_and_dlq(monkeypatch) -> None:
    calls = await _capture_schedule(monkeypatch)
    entries: list[dict] = []

    async def fake_push(entry):
        entries.append(entry)

    from fastapi_app.services.backup.metrics.alert_service import (
        alert_service as _alert_singleton,
    )

    alerts: list[dict] = []

    async def fake_send_alert(**kwargs):
        alerts.append(kwargs)

    monkeypatch.setattr(arq_callbacks, '_push_to_dead_letter', fake_push)
    monkeypatch.setattr(arq_callbacks, '_emit_failure_metric', lambda _name: None)
    monkeypatch.setattr(_alert_singleton, 'send_alert', fake_send_alert)

    ctx = {
        'job_id': 'sched:9:0',
        'job_try': 3,
        '_max_tries': 3,
        '_job_function': 'demo_task',
        '_job_args': (1, 'x'),
        '_job_kwargs': {'k': 'v'},
        '_job_outcome': 'failed',
        '_job_exception': ValueError('boom'),
    }
    await arq_callbacks.on_job_end(ctx)

    assert calls == [STATUS_FAILED]
    assert len(entries) == 1
    entry = entries[0]
    assert entry['task_id'] == 'sched:9:0'
    assert entry['task_name'] == 'demo_task'
    assert entry['exception'] == 'boom'
    assert entry['exception_type'] == 'ValueError'
    assert entry['job_try'] == 3
    assert entry['max_tries'] == 3
    assert '(1, ' in entry['args']
    assert "'k': 'v'" in entry['kwargs']
    # M-C：任务终态失败必须接 alert_service（critical 恒通知），不再只落日志
    assert len(alerts) == 1
    assert alerts[0]['task_name'] == 'arq:demo_task'
    assert alerts[0]['severity'] == 'critical'
    # M4（2026-10-25）：外发告警只给类型名 + 关联 ID，异常原文（'boom'）不得外发——
    # 截断不等于脱敏；原文保留在上方日志与死信条目（entry['exception'] == 'boom'）。
    assert 'ValueError' in alerts[0]['error']
    assert 'boom' not in alerts[0]['error']


async def test_on_job_end_without_outcome_keeps_legacy_success(monkeypatch) -> None:
    """未包 _tracked_job 的外部调用保持旧语义；注册任务全部已包。"""
    calls = await _capture_schedule(monkeypatch)

    await arq_callbacks.on_job_end({'job_id': 'legacy'})

    assert calls == [STATUS_SUCCESS]
