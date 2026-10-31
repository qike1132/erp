"""领域事件广播的超时/退避回归（2026-10-30 审计 A-M1）。

`_broadcast` 原先裸调 `client.publish()`：Redis 出现 TCP 半死（连得上但不响应）时，
这一次调用会挂到套接字超时（5–10s）。发布发生在写请求的 post-commit 回调里，
此时数据库连接仍被持有，于是一个写请求就能把连接池和请求队列一起拖住。

修复后：单次发布包 `wait_for` 硬超时；失败置退避窗口，窗口内直接短路；
并把失败告知缓存层（note_command_failure）让两套退避同向。
"""
import asyncio
import time
from unittest.mock import patch

import pytest

from fastapi_app.core import domain_events
from fastapi_app.core.domain_events import DomainEvent, DomainEventType


def _event() -> DomainEvent:
    return DomainEvent(event_type=DomainEventType.ORDER_DELETED, domain='order', payload={'order_id': 1})


class _HangingClient:
    def __init__(self):
        self.publish_calls = 0

    async def publish(self, *_args, **_kwargs):
        self.publish_calls += 1
        await asyncio.sleep(30)  # 模拟 TCP 半死：永不返回


class _OkClient:
    def __init__(self):
        self.publish_calls = 0

    async def publish(self, *_args, **_kwargs):
        self.publish_calls += 1
        return 1


@pytest.fixture(autouse=True)
def _reset_backoff(monkeypatch):
    monkeypatch.setattr(domain_events, '_broadcast_unhealthy_until', 0.0, raising=True)
    yield
    domain_events._broadcast_unhealthy_until = 0.0


@pytest.mark.asyncio
async def test_publish_is_bounded_by_timeout(monkeypatch):
    """半死连接不得把发布拖过超时窗口。"""
    client = _HangingClient()
    monkeypatch.setattr(domain_events, '_BROADCAST_TIMEOUT_S', 0.1)
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=client), \
         patch('fastapi_app.core.redis_wrapper.note_command_failure') as m_note:
        started = time.monotonic()
        ok = await domain_events._broadcast(_event())
        elapsed = time.monotonic() - started

    assert ok is False
    assert elapsed < 1.0, f'发布未被超时截断，耗时 {elapsed:.2f}s'
    # 失败要告知缓存层，两套退避同向
    m_note.assert_called_once()


@pytest.mark.asyncio
async def test_second_broadcast_short_circuits_within_backoff(monkeypatch):
    """窗口内不再尝试发布：写请求不该每个都付一次超时代价。"""
    client = _HangingClient()
    monkeypatch.setattr(domain_events, '_BROADCAST_TIMEOUT_S', 0.1)
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=client), \
         patch('fastapi_app.core.redis_wrapper.note_command_failure'):
        assert await domain_events._broadcast(_event()) is False
        calls_after_first = client.publish_calls
        assert await domain_events._broadcast(_event()) is False

    assert client.publish_calls == calls_after_first, '退避窗口内仍发起了发布'


@pytest.mark.asyncio
async def test_force_bypasses_backoff_for_explicit_retry(monkeypatch):
    """显式要求投递（publish_with_retry）不受短路窗口限制。"""
    monkeypatch.setattr(domain_events, '_BROADCAST_TIMEOUT_S', 0.1)
    hanging = _HangingClient()
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=hanging), \
         patch('fastapi_app.core.redis_wrapper.note_command_failure'):
        assert await domain_events._broadcast(_event()) is False

    ok_client = _OkClient()
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=ok_client):
        assert await domain_events._broadcast(_event(), force=True) is True
    assert ok_client.publish_calls == 1


@pytest.mark.asyncio
async def test_success_resets_backoff(monkeypatch):
    """一次成功后窗口立即清除，后续不必等到期。"""
    monkeypatch.setattr(domain_events, '_broadcast_unhealthy_until', time.monotonic() + 60)
    ok_client = _OkClient()
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=ok_client):
        assert await domain_events._broadcast(_event(), force=True) is True

    assert domain_events._broadcast_unhealthy_until == 0.0
    # 非 force 也应立即恢复尝试
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=ok_client):
        assert await domain_events._broadcast(_event()) is True
    assert ok_client.publish_calls == 2


@pytest.mark.asyncio
async def test_missing_client_is_not_treated_as_redis_failure(monkeypatch):
    """拿不到客户端只表示「未发出」，不应 arm 退避窗口（否则 Redis 恢复后仍被压住）。"""
    with patch('fastapi_app.core.redis_wrapper.get_client', return_value=None):
        assert await domain_events._broadcast(_event()) is False
    assert domain_events._broadcast_unhealthy_until == 0.0
