"""M7：日级 ARQ cron 停机漏跑后必须自动补跑一次，且不重复入队。"""
from datetime import datetime

import pytest

from fastapi_app.core import arq_app


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class _FakePool:
    def __init__(self):
        self.enqueued = []

    async def enqueue_job(self, name, _job_id=None):
        self.enqueued.append((name, _job_id))
        return object()


@pytest.mark.asyncio
async def test_missed_daily_cron_enqueued_once(monkeypatch):
    fake_redis = _FakeRedis()
    fake_pool = _FakePool()

    async def _get_pool():
        return fake_pool

    monkeypatch.setattr(arq_app, "get_arq_pool", _get_pool)
    monkeypatch.setattr(
        "fastapi_app.core.redis_wrapper.get_client", lambda: fake_redis
    )

    now = datetime(2026, 10, 22, 9, 0)  # 两个日级 cron 的应跑时刻都已过
    await arq_app.catch_up_daily_crons({}, now=now)
    first = list(fake_pool.enqueued)
    await arq_app.catch_up_daily_crons({}, now=now)

    assert first, "漏跑的日级 cron 必须被入队"
    assert fake_pool.enqueued == first, "重复采样不得重复入队"
    assert len({job_id for _, job_id in first}) == len(first)
