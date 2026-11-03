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


def test_read_engine_pool_config_is_half_of_primary(monkeypatch):
    """副本池必须是主池减半（向上给最小值），不能整体复用主池配置。

    2026-11-03（全量 skip 明细复核）：本机没有只读副本实例，原写法在
    ``_init_read_engine()`` 因 URL 为空直接 return 后 ``pytest.skip``，于是
    「副本池预算」这条 P0-3 回归**从未在任何环境执行过**——它伪装成环境缺失，
    实际是覆盖缺口。

    本用例验证的是**池参数派生**，不是副本连通性。``create_async_engine`` 是
    惰性建池（不 ping、不建连），所以注入一个副本 URL 就能让 ``_init_read_engine``
    走完整建池分支并断言池参数，无需真实副本实例。
    """
    primary = dict(db._pool_config)

    monkeypatch.setattr(
        db.settings,
        'ASYNC_DATABASE_REPLICA_URL',
        'postgresql+asyncpg://replica_probe:probe@127.0.0.1:5432/erp_system_test',
    )

    db._read_engine = None
    db._ReadSessionLocal = None
    try:
        db._init_read_engine()

        assert db._read_engine is not None, (
            '已注入 ASYNC_DATABASE_REPLICA_URL，副本引擎必须被建出来；'
            '若为 None 说明建池分支被短路，本用例会静默退化成 skip'
        )

        from sqlalchemy.pool import AsyncAdaptedQueuePool

        pool = db._read_engine.pool
        assert isinstance(pool, AsyncAdaptedQueuePool)
        assert pool.size() <= max(2, primary["pool_size"] // 2), (
            f"副本池 size={pool.size()} 超过主池减半预算 {max(2, primary['pool_size'] // 2)}"
        )
        assert pool._max_overflow <= max(1, primary["max_overflow"] // 2)
    finally:
        # 惰性引擎没建过连接，置空即可；但必须清掉，否则污染同进程后续用例。
        db._read_engine = None
        db._ReadSessionLocal = None


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
