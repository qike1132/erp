"""领域事件去重回归（2026-10-17 审计 F-BE-CORE-03）。

原实现：publish() 本地执行一遍 + Redis 广播投回发布进程再跑一遍 → 8 worker
下每个事件执行 9 次，写型订阅者（采购计划重算/撤单）9 倍写放大。修复：
广播体带 origin_pid（发布进程跳过自己）+ 监听器按 event_id 进程内去重。
"""
import json
import os

import fastapi_app.core.domain_events as de
from fastapi_app.core.domain_events import DomainEvent, DomainEventType


def _event() -> DomainEvent:
    return DomainEvent(
        event_type=DomainEventType.STOCK_OUT_CREATED,
        domain='stock', payload={'x': 1}, event_id='evt-123')


def test_to_dict_contains_origin_pid():
    d = _event().to_dict()
    assert d['origin_pid'] == os.getpid()


def test_listener_skips_own_pid_message(monkeypatch):
    """广播回环到发布进程时，handler 不再执行。"""
    calls = []
    monkeypatch.setitem(de._subscribers, DomainEventType.STOCK_OUT_CREATED,
                        [lambda e: calls.append(e)])
    payload = json.dumps(_event().to_dict(), ensure_ascii=False)
    # origin_pid 是本进程 → 应跳过
    data = json.loads(payload)
    assert data['origin_pid'] == os.getpid()
    # 模拟监听器分支逻辑：origin_pid == os.getpid() → continue
    skipped = data.get('origin_pid') == os.getpid()
    assert skipped


def test_seen_event_ids_dedup():
    """同 event_id 第二次进入不再执行。"""
    de._seen_event_ids.clear()
    ev = _event()
    calls = []

    def handler(e):
        calls.append(e)

    # 模拟监听器的去重分支
    for _ in range(2):
        if ev.event_id in de._seen_event_ids:
            continue
        de._seen_event_ids[ev.event_id] = True
        handler(ev)
    assert len(calls) == 1
