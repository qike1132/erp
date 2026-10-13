"""库存缓存「保热循环」的回归测试（2026-10-13）。

`_warm_inventory_cache` 原为「启动时跑一次」：缓存 TTL(120s) 一过就没人再热它，
下一个请求只能自己去跑 CTE。现改为启动预热 + 每 60s 重算默认键，让该键常驻
L1/L2 —— 命中缓存只读 Redis、不碰 PG，把 /stock 热路径从「主机/DB 争用时可能
卡数秒」里摘出来（评审依据见该函数 docstring）。

本测试锁死两点：①它是**循环**，不是一次；②每次都用与前端一致的 `per_page`。
"""
import asyncio

from fastapi_app import main as main_module


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _fake_session_factory():
    return _FakeSession()


async def test_warm_inventory_cache_keeps_refreshing(monkeypatch):
    """启动后必须**反复**重算默认键（一次就停 = 保热失效）。"""
    calls: list[tuple[int, int]] = []

    async def _fake_get_inventory_paginated(db, page=1, per_page=50):
        calls.append((page, per_page))

    monkeypatch.setattr(main_module, '_INVENTORY_WARMUP_STARTUP_DELAY_SECONDS', 0)
    monkeypatch.setattr(main_module, '_INVENTORY_WARMUP_INTERVAL_SECONDS', 0.01)
    # 两个依赖都在 _warm_inventory_cache 内部按需 import，patch 其源模块即可命中
    monkeypatch.setattr('fastapi_app.core.database.get_async_db_context', _fake_session_factory)
    monkeypatch.setattr(
        'fastapi_app.services.stock_service.get_inventory_paginated',
        _fake_get_inventory_paginated,
    )

    task = asyncio.create_task(main_module._warm_inventory_cache())
    try:
        for _ in range(500):
            if len(calls) >= 3:
                break
            await asyncio.sleep(0.01)
    finally:
        task.cancel()
        # 循环里必须让 CancelledError 透传（关停靠 background_tasks 的 cancel+gather 回收）
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('保热任务未响应取消 —— 关停会挂住')

    assert len(calls) >= 3, f'应周期性重算，实际只跑了 {len(calls)} 次'
    assert all(page == 1 and per_page == 20 for page, per_page in calls), calls
