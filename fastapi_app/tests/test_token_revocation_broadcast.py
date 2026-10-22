"""M9：登出撤销必须广播到其他 worker，消除多 worker 放行窗口。"""
import time

import pytest

from fastapi_app.core.auth import blacklist


@pytest.mark.asyncio
async def test_revoke_publishes(monkeypatch):
    published = []

    class _FakeRedis:
        async def set(self, *a, **k):
            return True

        async def publish(self, channel, msg):
            published.append((channel, msg))

    monkeypatch.setattr(
        "fastapi_app.core.redis_wrapper.get_client", lambda: _FakeRedis()
    )

    await blacklist.revoke_token("jti-x", int(time.time()) + 60)

    assert any("token_revoked" in c for c, _ in published), published
    assert any(m == "jti-x" for _, m in published), published


class _FakePubSub:
    def __init__(self):
        self.closed = False
        self.subscribed = None

    async def subscribe(self, channel):
        self.subscribed = channel

    async def listen(self):
        raise RuntimeError("connection lost")
        yield  # pragma: no cover

    async def aclose(self):
        self.closed = True


class _FakeRedisWithPubSub:
    def __init__(self, ps):
        self._ps = ps

    def pubsub(self):
        return self._ps


@pytest.mark.asyncio
async def test_consumer_closes_pubsub_on_error():
    """监听断开时必须关闭 pubsub，否则专用连接不归还池（多 worker 会耗尽）。"""
    ps = _FakePubSub()
    with pytest.raises(RuntimeError):
        await blacklist._consume_revocation_messages(_FakeRedisWithPubSub(ps))
    assert ps.closed
