"""领域事件「广播失败 → 落死信」链路的回归（2026-11-16 补）。

此前这条链路**零覆盖**：
- ``tests/test_domain_event_handler_deadletter.py`` 只覆盖 handler 失败（``stage=handler``）；
- ``fastapi_app/tests/test_domain_event_broadcast_timeout.py`` 只覆盖 ``_broadcast``
  的超时/退避/短路。

中间的 ``publish_with_retry`` —— 重试耗尽后落死信、且记录**不带 stage** ——
没有任何断言。后果是它静默污染生产证据：测试环境广播恒定失败（未初始化 Redis
客户端），2026-10-09→11-16 往仓库 ``logs/domain_events_deadletter.jsonl`` 写了
2437 条测试死信，而生产巡检（``deadletter_patrol_task`` / ``scripts/inspect_deadletter.py``）
读的正是同一个文件 —— 噪音把「应为 0」的基线冲掉。

本文件锁定四件事：
1. 广播失败 → 落死信，记录**保持无 stage 字段**（消费者靠这个区分广播/handler）；
2. 广播成功 → 不落死信（防"什么都往里写"的噪音）；
3. 死信目录受 ``ERP_DEADLETTER_DIR`` 控制（测试隔离的开关本身不能是硬编码）；
4. 巡检函数与写入口解析出**同一个**路径（防第二真相源）。
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fastapi_app.core import domain_events as de
from fastapi_app.tasks import deadletter_patrol_task as patrol


def _event() -> de.DomainEvent:
    return de.DomainEvent(
        event_type=de.DomainEventType.ORDER_DELETED,
        domain='order',
        payload={'order_id': 7},
    )


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    text = path.read_text(encoding='utf-8')
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture
def deadletter_file(tmp_path, monkeypatch):
    """把死信目录指到 tmp_path，顺带验证覆盖开关生效。"""
    monkeypatch.setenv('ERP_DEADLETTER_DIR', str(tmp_path))
    return tmp_path / 'domain_events_deadletter.jsonl'


@pytest.fixture(autouse=True)
def _isolate_subscribers(monkeypatch):
    """订阅表是模块级全局状态：清空它，避免用例真的跑业务 handler。"""
    monkeypatch.setattr(de, '_subscribers', {})
    monkeypatch.setattr(de, '_broadcast_unhealthy_until', 0.0)


@pytest.fixture
def no_redis(monkeypatch):
    """模拟测试环境常态：Redis 客户端未初始化（``_broadcast`` 返回 False）。"""
    monkeypatch.setattr('fastapi_app.core.redis_wrapper.get_client', lambda: None)


@pytest.mark.asyncio
async def test_broadcast_failure_lands_in_deadletter(deadletter_file, no_redis):
    """广播重试耗尽 → 必须落死信，且记录不带 stage（消费者契约）。"""
    await de.publish_with_retry(_event(), max_retries=0, delay=0)

    recs = _records(deadletter_file)
    assert len(recs) == 1, f'广播失败应落 1 条死信，实际 {len(recs)}'
    rec = recs[0]
    assert rec['event_type'] == de.DomainEventType.ORDER_DELETED.value
    assert rec['payload'] == {'order_id': 7}
    assert 'Redis 广播未发出' in rec['error']
    assert rec['ts'], '死信必须带时间戳，否则巡检无法按窗口统计'
    assert 'stage' not in rec, (
        '广播死信不得带 stage：patrol/inspect 靠「无 stage = 广播」分类，'
        '加了会被当成 handler 死信触发 critical 告警'
    )


@pytest.mark.asyncio
async def test_broadcast_success_writes_no_deadletter(deadletter_file, monkeypatch):
    """广播成功 → 死信文件不应产生（连目录都不该有文件）。"""

    class _OkClient:
        async def publish(self, *_args, **_kwargs):
            return 1

    monkeypatch.setattr('fastapi_app.core.redis_wrapper.get_client', lambda: _OkClient())
    await de.publish_with_retry(_event(), max_retries=0, delay=0)

    assert _records(deadletter_file) == []


@pytest.mark.asyncio
async def test_handler_deadletter_also_honours_override(deadletter_file, monkeypatch):
    """handler 死信与发布死信共用同一目录解析（否则只隔离了一半）。"""

    async def boom(_event):
        raise RuntimeError('handler 炸了')

    monkeypatch.setattr(de, '_subscribers', {de.DomainEventType.ORDER_DELETED: [boom]})
    await de._dispatch_in_process(_event())

    recs = _records(deadletter_file)
    assert len(recs) == 1
    assert recs[0]['stage'] == 'handler'


@pytest.mark.asyncio
async def test_handler_deadletter_runs_off_event_loop(deadletter_file, monkeypatch):
    """审计 M-30：handler 死信写盘必须离开事件循环（同步 open 会串行拖慢 worker）。"""
    import threading

    main_thread = threading.get_ident()
    seen: dict = {}

    def fake_append(*_args, **_kwargs):
        seen['thread'] = threading.get_ident()

    async def boom(_event):
        raise RuntimeError('handler 炸了')

    monkeypatch.setattr(de, '_append_deadletter_handler', fake_append)
    monkeypatch.setattr(de, '_subscribers', {de.DomainEventType.ORDER_DELETED: [boom]})

    await de._dispatch_in_process(_event())

    assert seen['thread'] != main_thread


@pytest.mark.asyncio
async def test_patrol_reads_the_same_path_as_writer(deadletter_file, no_redis):
    """巡检读的必须就是写入口写的那个文件，否则「0 条」是假的。"""
    await de.publish_with_retry(_event(), max_retries=0, delay=0)

    assert patrol.default_deadletter_path() == deadletter_file
    summary = patrol.summarize_deadletter(
        patrol.default_deadletter_path(),
        since=datetime.now(UTC) - timedelta(hours=1),
    )
    assert summary['broadcast_count'] == 1
    assert summary['handler_count'] == 0
