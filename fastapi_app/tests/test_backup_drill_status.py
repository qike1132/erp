"""灾备演练失败必须在调度表里如实记 failed（2026-11-04 修复回归）。

缺陷
----
``disaster_recovery_test_task`` 在 ``overall_success=false`` 时只发告警然后
``return result``。而 ``_tracked_job`` 判定失败的依据只有两种：抛异常，或返回
dict 且 ``status=='error'``。演练服务返回的是 ``{'overall_success': False, ...}``
—— 不带 ``status``，于是 ``on_job_end`` 走成功分支，把
``backup_schedule.last_status`` 写成 ``success``。

生产实测（2026-11-01，`backup_schedule` id=36）：``last_status=success``，
而 ``backups/server/recovery_tests/recovery_test_20261101_041001_fbf72c.json``
里 ``overall_success=false``。也就是说"灾备到底能不能用"这个最关键的信号，
在调度表里被彻底掩盖了 —— 与 `backup_freshness` 恒红、watchdog 冷却误记账
属于同一类"监控说谎"缺陷。

修复契约（本文件逐条锁定）
--------------------------
1. 演练 ``overall_success=false`` 时，任务返回值必须带 ``status='error'``；
2. 原始字段（``overall_success`` / ``test_id`` / 失败原因）不得丢；
3. ``overall_success=true`` 时不得被误标成 error；
4. ``_tracked_job`` 对该返回值必须判 ``_job_outcome='failed'``（否则修复无效）。
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture()
def backup_tasks(monkeypatch):
    from fastapi_app.tasks import backup_tasks as module

    async def _noop_alert(*args, **kwargs):
        return None

    monkeypatch.setattr(module, '_send_backup_alert', _noop_alert)
    return module


def _run_failed_drill(backup_tasks, payload: dict) -> dict:
    import importlib

    # 注意：`orchestration/__init__.py` 把 `recovery_test_service` 这个属性重绑成了
    # 单例实例，`from ... import recovery_test_service` 拿到的是实例而非模块；
    # 这里必须按模块名导入才能 patch 到单例方法。
    svc_module = importlib.import_module(
        'fastapi_app.services.backup.orchestration.recovery_test_service'
    )

    async def _fake_perform(*args, **kwargs):
        return payload

    service = svc_module.recovery_test_service
    original = service.perform_recovery_test
    service.perform_recovery_test = _fake_perform  # type: ignore[method-assign]
    try:
        return asyncio.run(backup_tasks.disaster_recovery_test_task({'job_try': 1}))
    finally:
        service.perform_recovery_test = original  # type: ignore[method-assign]


def test_failed_drill_returns_error_status(backup_tasks) -> None:
    result = _run_failed_drill(
        backup_tasks,
        {
            'test_id': 'drill-20261101',
            'overall_success': False,
            'error': 'constraint_validation: UndefinedColumnError',
        },
    )

    assert result['status'] == 'error', '演练失败必须以 status=error 返回，否则调度终态会被写成 success'
    assert result['overall_success'] is False
    assert result['test_id'] == 'drill-20261101'
    assert 'constraint_validation' in result['error']


def test_successful_drill_not_marked_error(backup_tasks) -> None:
    result = _run_failed_drill(
        backup_tasks,
        {'test_id': 'drill-ok', 'overall_success': True, 'summary': {'tables': 71}},
    )

    assert result.get('status') != 'error'
    assert result['overall_success'] is True


def test_tracked_job_turns_drill_failure_into_failed_outcome(backup_tasks) -> None:
    """修复必须真的作用到 ARQ 回调判定上，而不只是多了一个字段。"""
    from fastapi_app.core.arq_app import _tracked_job

    failed = _run_failed_drill(
        backup_tasks,
        {'test_id': 'drill-x', 'overall_success': False, 'error': 'boom'},
    )

    async def _fake_task(ctx):
        return failed

    ctx: dict = {'job_try': 1}
    asyncio.run(_tracked_job(_fake_task)(ctx))

    assert ctx.get('_job_outcome') == 'failed', '_tracked_job 必须把 status=error 的返回值判为失败'
