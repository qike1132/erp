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
