"""ARQ 失败告警脱敏（M4，2026-10-25 上线前检查）回归测试。

锁定：``on_job_end`` 失败链的外发告警（alert_service）只含异常**类型名**与
job 关联 ID，绝不含异常原文（`{exc}` 可能携带 SQL 片段/参数/密钥样式内容，
300 字符截断不提供机密性）。原文只允许出现在受保护的内部日志与死信队列条目。
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from fastapi_app.core import arq_callbacks


def _failed_ctx(exc: Exception) -> dict:
    return {
        'job_id': 'job-abc-123',
        'job_try': 3,
        '_job_function': 'sync_stock_task',
        '_max_tries': 3,
        '_job_args': (),
        '_job_kwargs': {},
        '_job_outcome': 'failed',
        '_job_exception': exc,
    }


async def test_failure_alert_does_not_leak_exception_text():
    """外发 error 不得含异常原文/密钥样式串；须含类型名与 job_id。"""
    # EXAMPLE_ 前缀 = hook 第 2 层占位符排除列表放行（无 allowlist 可依）
    secret = 'SECRET_TOKEN=EXAMPLE_NOT_REAL_9f8e7d6c5b4a'
    exc = RuntimeError(f'psycopg 连接失败 password={secret} order_id=SO-20261025-0001')

    with patch('fastapi_app.services.backup.metrics.alert_service.alert_service.send_alert',
               new=AsyncMock()) as spy, \
         patch('fastapi_app.core.redis_wrapper.safe_lpush', new=AsyncMock()):
        await arq_callbacks.on_job_end(_failed_ctx(exc))

    assert spy.await_count == 1, '失败链必须外发 critical 告警（M-C）'
    sent = spy.await_args.kwargs
    assert sent['severity'] == 'critical'
    error_text = sent['error']
    assert 'RuntimeError' in error_text, '类型名保留（定位用）'
    assert 'job-abc-123' in error_text, '关联 ID 保留（定位用）'
    assert secret not in error_text, '密钥样式原文不得外发（M4）'
    assert 'EXAMPLE_NOT_REAL' not in error_text
    assert 'SO-20261025-0001' not in error_text, '业务标识不得外发（M4）'
    assert 'password=' not in error_text


async def test_dead_letter_entry_keeps_exception_for_internal_triage():
    """死信队列条目保留异常原文——内部受保护存储供排查，脱敏只针对外发渠道。"""
    exc = RuntimeError('cannot import name compute_order_statuses_batch')

    with patch('fastapi_app.services.backup.metrics.alert_service.alert_service.send_alert',
               new=AsyncMock()), \
         patch('fastapi_app.core.redis_wrapper.safe_lpush', new=AsyncMock()) as lpush:
        await arq_callbacks.on_job_end(_failed_ctx(exc))

    assert lpush.await_count == 1, '死信条目必须照常写入'
    entry = json.loads(lpush.await_args.args[1])
    assert 'cannot import name' in entry['exception'], '死信（内部）保留原文'
    assert entry['exception_type'] == 'RuntimeError'
    assert entry['task_id'] == 'job-abc-123'
