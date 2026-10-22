"""L15：Redis 大 value 的 JSON 序列化必须下沉线程池，小 value 保持同步。"""
import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_large_value_serialization_offloaded(monkeypatch):
    from utils import redis_cache

    ticks = []
    start = time.monotonic()

    def _slow_dumps(*args, **kwargs):
        time.sleep(0.2)
        return "{}"

    monkeypatch.setattr(redis_cache.json, "dumps", _slow_dumps)

    async def _ticker():
        for _ in range(5):
            ticks.append(time.monotonic() - start)
            await asyncio.sleep(0.02)

    await asyncio.gather(
        redis_cache._serialize_async(["x"] * 2000),
        _ticker(),
    )

    assert len(ticks) == 5
    assert ticks[0] < 0.1, f"事件循环被大 value 序列化阻塞了 {ticks[0]:.3f}s"


def test_small_value_stays_synchronous():
    from utils import redis_cache

    assert redis_cache._needs_offload({"a": 1}) is False
    assert redis_cache._needs_offload(["x"] * 2000) is True
