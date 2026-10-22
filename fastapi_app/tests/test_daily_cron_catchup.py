"""M7：日级 ARQ cron 停机漏跑后必须自动补跑一次，且不重复入队。"""
from datetime import datetime

import pytest

from fastapi_app.core import arq_app


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key, fallback=None, context=""):
        return self.store.get(key, fallback)

    async def set(self, key, value, ex=None):
        self.store[key] = value


class _FakePool:
    def __init__(self):
        self.enqueued = []
        self.seen = set()

    async def enqueue_job(self, name, _job_id=None):
        if _job_id in self.seen:
            return None
        self.seen.add(_job_id)
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
        "fastapi_app.core.redis_wrapper.safe_get", fake_redis.get
    )

    now = datetime(2026, 10, 22, 9, 0)  # 两个日级 cron 的应跑时刻都已过
    await arq_app.catch_up_daily_crons({}, now=now)
    first = list(fake_pool.enqueued)
    await arq_app.catch_up_daily_crons({}, now=now)

    assert first, "漏跑的日级 cron 必须被入队"
    assert fake_pool.enqueued == first, "重复采样不得重复入队"
    assert len({job_id for _, job_id in first}) == len(first)
    # 入队 ≠ 成功：scanner 不得预写 cron_last_ok（否则失败重试后当天不再补跑）
    assert not any(k.startswith("cron_last_ok:") for k in fake_redis.store)


@pytest.mark.asyncio
async def test_success_callback_marks_day(monkeypatch):
    """成功回调才写当日标记；键名与 scanner 读取的一致。"""
    stored = {}

    async def _safe_set(key, value, timeout=300, context=""):
        stored[key] = value
        return True

    monkeypatch.setattr("fastapi_app.core.redis_wrapper.safe_set", _safe_set)

    from fastapi_app.core.arq_callbacks import _mark_daily_cron_success
    from fastapi_app.tasks.plan_tasks import sync_shipment_records_task

    await _mark_daily_cron_success({"_job_function": sync_shipment_records_task})

    assert any(k.startswith("cron_last_ok:") for k in stored), stored
