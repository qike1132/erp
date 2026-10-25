"""死信巡检任务（M-C，2026-10-25 审计）的回归测试。

行为锁定：
- handler 级死信（stage=handler/handler_cross_process，近24h）→ critical 告警，
  外发文本不含异常原文（M4：截断不等于脱敏）；
- ARQ DLQ 残留 → critical 告警（M3：原 warning 受 failure_threshold=3 约束，
  每日巡检头两次不外发；critical 首次即通知）；
- Redis DLQ 状态不可知 → critical 告警 + 任务按失败收尾（M1：unknown 洗成
  「空队列」是假健康）；
- 只有广播死信 → 不告警（Redis 重启窗口属常态，不打扰）；
- 时间窗外/坏行不计数；死信文件不存在 → 空结果不告警。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from fastapi_app.services.backup.metrics.alert_service import (
    alert_service as _alert_singleton,
)
from fastapi_app.tasks import deadletter_patrol_task as patrol


def _write(path, records: list[dict | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for rec in records:
            if isinstance(rec, str):  # 原始坏行：不是合法 JSON
                f.write(rec + '\n')
            else:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def _handler_rec(hours_ago: float = 1.0) -> dict:
    ts = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    # error 故意带密钥样式与业务标识：M4 断言「外发不含原文」需要真实敏感样例，
    # 否则脱敏断言无变异敏感性（评审 finding 10）。
    return {'ts': ts, 'stage': 'handler', 'handler': 'on_order_deleted',
            'event_type': 'order.deleted',
            'error': 'cannot import name x; password=sk-live-9f8e7d6c order=SO-20261025-0001'}


def _broadcast_rec(hours_ago: float = 1.0) -> dict:
    ts = (datetime.now(UTC) - timedelta(hours=hours_ago)).isoformat()
    return {'ts': ts, 'event_type': 'stock_out.created',
            'error': 'Redis 广播未发出（客户端不可用或发布失败）'}


@pytest.fixture
def alert_spy(monkeypatch):
    alerts: list[dict] = []

    async def fake_send_alert(**kwargs):
        alerts.append(kwargs)

    monkeypatch.setattr(_alert_singleton, 'send_alert', fake_send_alert)
    return alerts


@pytest.fixture
def dlq_empty(monkeypatch):
    async def fake_len():
        return 0
    monkeypatch.setattr(patrol, '_redis_dlq_length', fake_len)


# ---------------------------------------------------------------------------
# summarize_deadletter
# ---------------------------------------------------------------------------

def test_summarize_counts_by_stage(tmp_path):
    now = datetime.now(UTC)
    path = tmp_path / 'deadletter.jsonl'
    _write(path, [
        _handler_rec(1.0),
        _broadcast_rec(2.0),
        _broadcast_rec(72.0),   # 窗口外（>24h）→ 不计入
        'not-json {{{',         # 坏行 → 跳过
        {'ts': 'not-a-date', 'stage': 'handler'},  # 坏时间戳 → 跳过
    ])
    s = patrol.summarize_deadletter(path, since=now - timedelta(hours=24))
    assert s['handler_count'] == 1
    assert s['broadcast_count'] == 1
    assert len(s['handler_samples']) == 1
    assert s['handler_samples'][0]['handler'] == 'on_order_deleted'


def test_summarize_missing_file_is_empty(tmp_path):
    s = patrol.summarize_deadletter(tmp_path / 'nope.jsonl', since=datetime.now(UTC))
    assert s['total'] == 0 and s['handler_count'] == 0


def test_cross_process_stage_counts_as_handler(tmp_path):
    path = tmp_path / 'deadletter.jsonl'
    rec = _handler_rec(1.0)
    rec['stage'] = 'handler_cross_process'
    _write(path, [rec])
    s = patrol.summarize_deadletter(path, since=datetime.now(UTC) - timedelta(hours=2))
    assert s['handler_count'] == 1


# ---------------------------------------------------------------------------
# run_deadletter_patrol 分级告警
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handler_deadletter_alerts_critical(monkeypatch, alert_spy, dlq_empty, tmp_path):
    path = tmp_path / 'deadletter.jsonl'
    _write(path, [_handler_rec(1.0), _broadcast_rec(1.0)])
    monkeypatch.setattr(patrol, 'default_deadletter_path', lambda: path)

    result = await patrol.run_deadletter_patrol()

    assert result['handler_count'] == 1
    assert len(alert_spy) == 1
    assert alert_spy[0]['severity'] == 'critical'
    assert 'handler 级死信' in alert_spy[0]['error']


@pytest.mark.asyncio
async def test_handler_alert_error_is_sanitized_not_raw_exception(monkeypatch, alert_spy, dlq_empty, tmp_path):
    """M4 锁：外发告警只给结构化字段（handler 名），不得携带异常原文。

    变异：把实现改回在 error 里拼 _sample_desc（含 error 字段原文），本测试必红。
    """
    path = tmp_path / 'deadletter.jsonl'
    _write(path, [_handler_rec(1.0)])
    monkeypatch.setattr(patrol, 'default_deadletter_path', lambda: path)

    await patrol.run_deadletter_patrol()

    error_text = alert_spy[0]['error']
    assert 'on_order_deleted' in error_text, '外发必须含 handler 名（定位用）'
    assert 'cannot import name' not in error_text, '异常原文不得外发（M4）'
    assert 'sk-live-9f8e7d6c' not in error_text, '密钥样式原文不得外发（M4）'
    assert 'SO-20261025-0001' not in error_text, '业务标识不得外发（M4）'


@pytest.mark.asyncio
async def test_dlq_length_uses_three_state_llen(monkeypatch):
    """H-1 + M1 锁：DLQ 长度必须走三态 safe_llen_ex（List 用 LLEN）。

    safe_get（Redis GET）打在 List 上抛 WRONGTYPE、被底层缓存层吞成 None →
    恒报 0；safe_llen（二态折叠版）又把「查不出来」洗成 0——两者都是假健康。
    变异：把实现改回 safe_get / safe_llen，本测试必红。
    """
    calls: list[tuple[str, str]] = []

    async def fake_llen_ex(key, context=''):
        calls.append(('llen_ex', key))
        return 4

    async def fake_get(key, default=None, context=''):
        calls.append(('get', key))
        return default

    monkeypatch.setattr('fastapi_app.core.redis_wrapper.safe_llen_ex', fake_llen_ex)
    monkeypatch.setattr('fastapi_app.core.redis_wrapper.safe_get', fake_get)

    assert await patrol._redis_dlq_length() == 4
    assert calls == [('llen_ex', patrol.ARQ_DLQ_KEY)], 'DLQ 长度必须经三态 safe_llen_ex 读取'


@pytest.mark.asyncio
async def test_dlq_unknown_alerts_critical_and_task_fails(monkeypatch, alert_spy, tmp_path):
    """M1 锁：Redis 不可知 ≠ 空队列。必须 critical 外发 + 任务按失败收尾。

    变异：把 unknown 折叠成 0（走「无残留」分支），本测试必红（无告警/success=True）。
    """
    async def fake_len():
        return None
    monkeypatch.setattr(patrol, '_redis_dlq_length', fake_len)
    monkeypatch.setattr(patrol, 'default_deadletter_path', lambda: tmp_path / 'none.jsonl')

    task_result = await patrol.inspect_deadletter_task({})

    assert task_result['dlq_status'] == 'unknown'
    assert task_result['arq_dlq_len'] is None
    assert len(alert_spy) == 1
    assert alert_spy[0]['severity'] == 'critical'
    assert '无法读取 Redis DLQ' in alert_spy[0]['error']
    assert task_result['success'] is False, 'unknown 时巡检任务必须记失败'
    assert task_result['status'] == 'error', "status='error' 让 _tracked_job 记 failed（失败链 critical）"


@pytest.mark.asyncio
async def test_dlq_residue_alerts_critical_on_first_occurrence(monkeypatch, alert_spy, tmp_path):
    """M3 锁：DLQ 残留必须 critical（首次即外发），不得走 warning 阈值。"""
    async def fake_len():
        return 2
    monkeypatch.setattr(patrol, '_redis_dlq_length', fake_len)
    monkeypatch.setattr(patrol, 'default_deadletter_path', lambda: tmp_path / 'none.jsonl')

    result = await patrol.run_deadletter_patrol()

    assert result['arq_dlq_len'] == 2
    assert len(alert_spy) == 1
    assert alert_spy[0]['severity'] == 'critical', 'warning 受 failure_threshold 约束会静默两轮（M3）'


@pytest.mark.asyncio
async def test_critical_alert_bypasses_failure_threshold(monkeypatch):
    """M3 配套锁：alert_service 的 critical 级别必须绕过 failure_threshold=3。

    模拟真实链路：只替换邮件/webhook 两个出口（记录调用），failure_counts 从零
    开始、阈值 3——第一次 critical 就必须触发通知。变异（critical 也走阈值）
    本测试必红。
    """
    from fastapi_app.services.backup.metrics.alert_service import alert_service as real_svc

    sent = []
    monkeypatch.setattr(real_svc, 'failure_counts', {}, raising=False)
    monkeypatch.setattr(real_svc, 'last_alert_times', {}, raising=False)
    monkeypatch.setitem(real_svc.alert_config, 'failure_threshold', 3)
    monkeypatch.setitem(real_svc.alert_config, 'email_enabled', True)
    monkeypatch.setitem(real_svc.alert_config, 'webhook_enabled', False)

    async def fake_email(_data):
        sent.append('email')
        return True

    monkeypatch.setattr(real_svc, '_send_email_alert', fake_email)
    ok = await real_svc.send_alert(
        task_name='deadletter-patrol', error='ARQ 死信队列残留 2 条',
        task_type='deadletter_patrol', severity='critical',
    )
    assert ok is True and sent == ['email'], f'critical 首次必须外发，实际 sent={sent}'


@pytest.mark.asyncio
async def test_clean_state_alerts_nothing(monkeypatch, alert_spy, dlq_empty, tmp_path):
    path = tmp_path / 'deadletter.jsonl'
    _write(path, [_broadcast_rec(1.0)])  # 只有广播死信：常态不打扰
    monkeypatch.setattr(patrol, 'default_deadletter_path', lambda: path)

    result = await patrol.run_deadletter_patrol()

    assert result['handler_count'] == 0
    assert alert_spy == []


@pytest.mark.asyncio
async def test_old_handler_deadletter_outside_window_does_not_alert(
    monkeypatch, alert_spy, dlq_empty, tmp_path,
):
    """25h 前的 handler 死信不在当日窗口内（存量由 CLI 工具人工处置）。"""
    path = tmp_path / 'deadletter.jsonl'
    _write(path, [_handler_rec(25.0)])
    monkeypatch.setattr(patrol, 'default_deadletter_path', lambda: path)

    result = await patrol.run_deadletter_patrol()

    assert result['handler_count'] == 0
    assert alert_spy == []
