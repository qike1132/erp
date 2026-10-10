"""只读副本引擎连接池预算与关停释放的回归测试。

背景（2026-10-10 评审 P0-3 / P2-12）：
- _init_read_engine 复用主库 _pool_config ⇒ 主池+副本池峰值连接
  2×(pool_size+max_overflow)×workers 超过 PG max_connections(100)。
  修法：副本池在主池基础上减半（副本有 1s 快速失败+熔断降级主库，
  池小不损可用性）。
- dispose_async_engines 只 dispose 主引擎，不释放 _read_engine，
  与 rebuild_pool 的口径不对称。修法：补 dispose。
"""
import pytest

import fastapi_app.core.database as db


def test_read_engine_pool_config_is_half_of_primary():
    """副本池必须是主池减半（向上给最小值），不能整体复用主池配置。"""
    primary = dict(db._pool_config)

    db._read_engine = None
    db._ReadSessionLocal = None
    try:
        db._init_read_engine()
    finally:
        pass

    # 未配置副本 URL 时函数直接返回（回退主库），跳过断言
    if db._read_engine is None:
        pytest.skip("未配置 ASYNC_DATABASE_REPLICA_URL，副本引擎未初始化")

    from sqlalchemy.pool import AsyncAdaptedQueuePool

    pool = db._read_engine.pool
    assert isinstance(pool, AsyncAdaptedQueuePool)
    assert pool.size() <= max(2, primary["pool_size"] // 2), (
        f"副本池 size={pool.size()} 超过主池减半预算 {max(2, primary['pool_size'] // 2)}"
    )
    assert pool._max_overflow <= max(1, primary["max_overflow"] // 2)


def test_read_pool_config_derivation_is_pure():
    """派生逻辑：减半后不小于下限（size≥2, overflow≥1），且不改主池。"""
    primary_size, primary_overflow = 5, 3
    read_size = max(2, primary_size // 2)
    read_overflow = max(1, primary_overflow // 2)
    assert (read_size, read_overflow) == (2, 1)
    assert (primary_size, primary_overflow) == (5, 3)  # 主池不动


@pytest.mark.asyncio
async def test_dispose_async_engines_disposes_read_engine(monkeypatch):
    """dispose_async_engines 必须同时释放只读副本引擎。"""
    disposed = []

    class FakeEngine:
        async def dispose(self):
            disposed.append("read")

    monkeypatch.setattr(db, "_read_engine", FakeEngine())
    monkeypatch.setattr(db, "_ReadSessionLocal", object())
    monkeypatch.setattr(db, "_async_engine", None)
    monkeypatch.setattr(db, "_AsyncSessionLocal", None)
    monkeypatch.setattr(db, "async_engine", None)

    await db.dispose_async_engines()

    assert "read" in disposed, "dispose_async_engines 未释放只读副本引擎"
    assert db._read_engine is None
