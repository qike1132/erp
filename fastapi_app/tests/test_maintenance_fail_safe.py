"""维护模式 Redis fail-safe 回归（2026-10-17 审计 F-BE-CORE-09）。

原实现：Redis 不可用/异常一律 return False（fail-open）——还原期间 broker 抖动
会把写闸门静默打穿，写请求落在正被替换的库上。修复：enter 时写本地哨兵文件，
Redis 读不到时以哨兵为准（fail-safe）；哨兵带 mtime 过期防崩溃遗留。
"""
import time

import pytest

import fastapi_app.core.maintenance as m


@pytest.fixture(autouse=True)
def _tmp_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(m, '_MAINTENANCE_SENTINEL', tmp_path / 'm.sentinel')


@pytest.mark.asyncio
async def test_redis_down_but_sentinel_active_returns_true(monkeypatch):
    async def _no_client():
        return None
    monkeypatch.setattr(m, '_get_client', _no_client)
    m._write_sentinel(True)
    assert await m.is_maintenance_mode() is True


@pytest.mark.asyncio
async def test_redis_down_no_sentinel_returns_false(monkeypatch):
    async def _no_client():
        return None
    monkeypatch.setattr(m, '_get_client', _no_client)
    assert await m.is_maintenance_mode() is False


@pytest.mark.asyncio
async def test_redis_exception_with_sentinel_returns_true(monkeypatch):
    async def _boom():
        raise ConnectionError('broker down')
    monkeypatch.setattr(m, '_get_client', _boom)
    m._write_sentinel(True)
    assert await m.is_maintenance_mode() is True


@pytest.mark.asyncio
async def test_stale_sentinel_ignored(monkeypatch, tmp_path):
    async def _no_client():
        return None
    monkeypatch.setattr(m, '_get_client', _no_client)
    m._write_sentinel(True)
    # 把 mtime 拨回超过 2×TTL
    import os
    old = time.time() - (m._SENTINEL_MAX_AGE + 60)
    os.utime(m._MAINTENANCE_SENTINEL, (old, old))
    assert await m.is_maintenance_mode() is False


@pytest.mark.asyncio
async def test_redis_ok_overrides_sentinel(monkeypatch):
    """Redis 正常时以 Redis 值为准（哨兵存在但 Redis 说没有 → False）。"""
    class _FakeClient:
        async def get(self, key):
            return None
    async def _client():
        return _FakeClient()
    monkeypatch.setattr(m, '_get_client', _client)
    m._write_sentinel(True)
    assert await m.is_maintenance_mode() is False
