"""P1-06 回归：备份任务的 ARQ 重试契约。

ARQ 0.28 只在任务抛 ``Retry`` 时重放；普通异常会立即失败。备份任务原实现
``if job_try < 3: raise e`` 抛普通异常，等于「重试 3 次」从未发生。
本文件锁住：前两跳抛 Retry、最后一跳返回 error 且 _tracked_job 记为 failed。
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from arq import Retry

from fastapi_app.core.arq_app import _tracked_job
from fastapi_app.tasks import backup_tasks


@pytest.fixture(autouse=True)
def _patch_task_infra(monkeypatch):
    monkeypatch.setattr(backup_tasks, 'create_progress', AsyncMock())
    monkeypatch.setattr(backup_tasks, 'update_progress', AsyncMock())
    monkeypatch.setattr(backup_tasks, 'fail_progress', AsyncMock())
    monkeypatch.setattr(backup_tasks, '_send_backup_alert', AsyncMock())

    async def _boom():
        raise RuntimeError('disk full')

    monkeypatch.setattr('fastapi_app.services.backup.ensure_backup_dir', _boom)


async def test_failure_on_first_attempt_raises_retry():
    with pytest.raises(Retry):
        await backup_tasks.manual_full_backup_task({'job_try': 1}, task_id='retry-1')


async def test_failure_on_last_attempt_returns_error():
    result = await backup_tasks.manual_full_backup_task({'job_try': backup_tasks._MAX_TRIES}, task_id='retry-2')
    assert result['status'] == 'error'
    assert result['error']


async def test_tracked_job_marks_error_result_as_failed():
    async def _task(ctx):
        return {'status': 'error', 'error': 'boom'}

    ctx = {}
    await _tracked_job(_task, max_tries=3)(ctx)
    assert ctx['_job_outcome'] == 'failed'


def test_all_retry_blocks_raise_arq_retry():
    """9 个任务族的 job_try 分支必须全部抛 Retry，不能有 copy-paste 回退。"""
    source = Path(backup_tasks.__file__).read_text(encoding='utf-8')
    tree = ast.parse(source)
    blocks = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        dumped = ast.dump(node.test)
        if 'job_try' not in dumped or '_MAX_TRIES' not in dumped:
            continue
        blocks += 1
        raises_retry = any(
            isinstance(stmt, ast.Raise)
            and isinstance(stmt.exc, ast.Call)
            and getattr(stmt.exc.func, 'id', None) == 'Retry'
            for stmt in node.body
        )
        assert raises_retry, f'第 {node.lineno} 行的 job_try 分支未抛 Retry'
    assert blocks == 9
