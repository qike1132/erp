"""死信巡检任务（M-C，2026-10-25 审计）的回归测试。

行为锁定：
- handler 级死信（stage=handler/handler_cross_process，近24h）→ critical 告警；
- ARQ DLQ 残留 → warning 告警；
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
    return {'ts': ts, 'stage': 'handler', 'handler': 'on_order_deleted',
            'event_type': 'order.deleted', 'error': 'cannot import name x'}


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
async def test_dlq_residue_alerts_warning(monkeypatch, alert_spy, tmp_path):
    async def fake_len():
        return 2
    monkeypatch.setattr(patrol, '_redis_dlq_length', fake_len)
    monkeypatch.setattr(patrol, 'default_deadletter_path', lambda: tmp_path / 'none.jsonl')

    result = await patrol.run_deadletter_patrol()

    assert result['arq_dlq_len'] == 2
    assert len(alert_spy) == 1
    assert alert_spy[0]['severity'] == 'warning'


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
