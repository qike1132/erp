"""领域事件订阅 handler 失败必须落死信（2026-10-22 事故的可观测性缺口）。

事故：`ORDER_DELETED` handler 因延迟导入缺符号连续 `ImportError` 8 次，但只落 ERROR
日志——调用方（删订单）的请求照常 200、页面无提示，用户看到的是「采购中心挂着我
没有的订单」。等用户投诉才发现，中间无任何可巡检信号。

修法：handler 失败与发布失败共用 `logs/domain_events_deadletter.jsonl`，用 `stage`
字段区分（`handler` vs 发布失败的缺省形态），附 handler 名与 error_type 便于定位重放。

本测试锁定这条：**任何 handler 抛异常都必须写进死信文件**。
"""
import json
from pathlib import Path

import pytest

from fastapi_app.core import domain_events as de


@pytest.fixture
def deadletter_path(tmp_path, monkeypatch):
    """把死信文件指到临时目录，避免污染生产 logs/。"""
    target = tmp_path / 'domain_events_deadletter.jsonl'
    real_write = de._append_deadletter_handler

    def _patched(event, handler, error):
        record = {
            'ts': '2026-10-23T00:00:00+00:00',
            'stage': 'handler',
            'handler': getattr(handler, '__name__', repr(handler)),
            'event_type': event.event_type.value,
            'payload': event.payload,
            'error': str(error),
            'error_type': type(error).__name__,
        }
        target.write_text(
            target.read_text(encoding='utf-8') + json.dumps(record, ensure_ascii=False) + '\n'
            if target.exists() else json.dumps(record, ensure_ascii=False) + '\n',
            encoding='utf-8',
        )

    monkeypatch.setattr(de, '_append_deadletter_handler', _patched)
    yield target
    monkeypatch.setattr(de, '_append_deadletter_handler', real_write)


def _records(path: Path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


async def test_handler_failure_writes_deadletter(deadletter_path):
    """handler 抛异常 → 死信文件出现该事件的记录（附 handler 名与错误类型）。"""

    async def boom(event):
        raise ImportError("cannot import name 'x' from 'y'")

    # 直接测私有分发函数：订阅注册是模块级全局状态，用 monkeypatch 隔离
    de._subscribers.setdefault(de.DomainEventType.ORDER_DELETED, [])
    original = list(de._subscribers[de.DomainEventType.ORDER_DELETED])
    de._subscribers[de.DomainEventType.ORDER_DELETED].append(boom)
    try:
        await de._dispatch_in_process(de.DomainEvent(
            event_type=de.DomainEventType.ORDER_DELETED,
            domain='order',
            payload={'order_id': 68941},
        ))
    finally:
        de._subscribers[de.DomainEventType.ORDER_DELETED] = original

    recs = _records(deadletter_path)
    assert len(recs) == 1, f'应有 1 条 handler 死信，实际 {len(recs)}'
    r = recs[0]
    assert r['stage'] == 'handler'
    assert r['handler'] == 'boom'
    assert r['error_type'] == 'ImportError'
    assert r['payload'] == {'order_id': 68941}


async def test_handler_success_writes_no_deadletter(deadletter_path):
    """handler 正常返回 → 不写死信（防"什么都往里写"的噪音）。"""

    async def ok(event):
        return None

    de._subscribers.setdefault(de.DomainEventType.ORDER_DELETED, [])
    original = list(de._subscribers[de.DomainEventType.ORDER_DELETED])
    de._subscribers[de.DomainEventType.ORDER_DELETED].append(ok)
    try:
        await de._dispatch_in_process(de.DomainEvent(
            event_type=de.DomainEventType.ORDER_DELETED,
            domain='order',
            payload={'order_id': 1},
        ))
    finally:
        de._subscribers[de.DomainEventType.ORDER_DELETED] = original

    assert _records(deadletter_path) == [], 'handler 成功时死信应为空'


async def test_one_failing_handler_does_not_block_others(deadletter_path):
    """单个 handler 失败不影响其它 handler（既有契约，防回归）。"""
    calls = []

    async def bad(event):
        raise RuntimeError('boom')

    async def good(event):
        calls.append(event.payload.get('order_id'))

    de._subscribers.setdefault(de.DomainEventType.ORDER_DELETED, [])
    original = list(de._subscribers[de.DomainEventType.ORDER_DELETED])
    de._subscribers[de.DomainEventType.ORDER_DELETED].extend([bad, good])
    try:
        await de._dispatch_in_process(de.DomainEvent(
            event_type=de.DomainEventType.ORDER_DELETED,
            domain='order',
            payload={'order_id': 42},
        ))
    finally:
        de._subscribers[de.DomainEventType.ORDER_DELETED] = original

    assert calls == [42], '前一个 handler 抛异常后，后续 handler 仍应执行'
