"""ARQ Worker 健康检测回归护栏（`core/arq_app.check_worker_health`）。

背景
----
`check_worker_health()` 曾误用 arq 0.28 **不存在**的 `ArqRedis.health()`，
异常被宽泛 except 吞成 `(False, '...AttributeError')`，
使 `/api/v1/backup/full` 与 `/incremental` 一律返回 503 WORKER_OFFLINE——
**即使 worker 健康在线**，手动备份被完全阻断。

为什么既有测试抓不到：
`test_backup_m1.py` 的 `TestTriggerEndpoints` 用 autouse fixture 把
`actions._check_worker_online` 整体 mock 掉（合理：端点测试不该依赖运行环境），
`fake_pool = AsyncMock()` 又会自动合成任意属性 → `pool.health()` 也能"成功"。
于是**没有任何测试真正执行过健康探测逻辑**，回归畅通无阻。

本文件直接针对健康检测函数本身，用**普通对象**（非 AsyncMock）做替身，
使"多调一个不存在的方法"这类缺陷必然暴露。
"""
from __future__ import annotations

import asyncio

import pytest
from arq.connections import ArqRedis
from arq.constants import default_queue_name, health_check_key_suffix

from fastapi_app.core import arq_app
from fastapi_app.core.arq_app import WorkerSettings, check_worker_health

# 期望的哨兵键（实测 Redis 6380 上存在的键即为该值）
EXPECTED_KEY = default_queue_name + health_check_key_suffix


class _FakePool:
    """最小 ARQ 连接池替身：只实现哨兵键读取，故意**不**提供 health()。

    刻意不用 AsyncMock —— AsyncMock 会自动合成 `health` 等任意属性，
    正是它让历史上的 AttributeError 回归无法被测试发现。
    """

    def __init__(self, sentinel=None, raise_exc: Exception | None = None, hang: float = 0.0):
        self._sentinel = sentinel
        self._raise = raise_exc
        self._hang = hang
        self.get_calls: list[str] = []
        self.default_queue_name = default_queue_name

    async def get(self, key):
        self.get_calls.append(key)
        if self._hang:
            await asyncio.sleep(self._hang)
        if self._raise is not None:
            raise self._raise
        return self._sentinel


@pytest.fixture
def patch_pool(monkeypatch):
    def _apply(pool):
        async def _fake_get_pool():
            return pool

        monkeypatch.setattr(arq_app, 'get_arq_pool', _fake_get_pool)
        return pool

    return _apply


# ---------------------------------------------------------------------------
# 0. 契约锚点：把"arq 0.28 没有 health()"钉死在测试里
# ---------------------------------------------------------------------------
def test_arq_redis_has_no_health_method():
    """锁定根因：arq 0.28 的 ArqRedis 不存在 health() 方法。

    若未来升级 arq 引入了该方法，本测试会失败——提醒复查探测实现，
    而不是让代码悄悄依赖一个不存在（或语义不同）的接口。
    """
    assert not hasattr(ArqRedis, 'health'), (
        'arq 已提供 ArqRedis.health()，请复核 check_worker_health 的实现与语义'
    )


def test_sentinel_key_matches_arq_official_constant():
    """哨兵键必须等于 arq 官方定义（Worker.health_check_key 同源）。"""
    assert EXPECTED_KEY == 'arq:queue:health-check'
    assert arq_app._health_check_key(_FakePool()) == EXPECTED_KEY


# ---------------------------------------------------------------------------
# 1. 在线：哨兵键存在 → True（修复前此处必然失败）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_online_when_sentinel_present(patch_pool):
    """哨兵键存在 → (True, ...)，且只读哨兵键、不触碰不存在的 health()。

    修复前行为：`pool.health()` → AttributeError → 返回 (False, '...AttributeError')
    → 端点 503，手动备份被误拦截。
    """
    pool = patch_pool(
        _FakePool(sentinel=b'Sep-17 11:20:21 j_complete=0 j_failed=0 j_retried=0 j_ongoing=0 queued=0')
    )

    is_healthy, message = await check_worker_health()

    assert is_healthy is True, f'worker 有哨兵键却被判离线: {message}'
    assert 'ARQ Worker 在线' in message
    assert pool.get_calls == [EXPECTED_KEY]


@pytest.mark.asyncio
async def test_online_accepts_str_sentinel(patch_pool):
    """decode_responses=True 的连接池返回 str，也须判为在线。"""
    patch_pool(_FakePool(sentinel='Sep-17 11:20:21 j_complete=3'))

    is_healthy, message = await check_worker_health()

    assert is_healthy is True
    assert 'j_complete=3' in message


# ---------------------------------------------------------------------------
# 2. 离线：哨兵键缺失 → False，且给出可操作的提示
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_offline_when_sentinel_absent(patch_pool):
    patch_pool(_FakePool(sentinel=None))

    is_healthy, message = await check_worker_health()

    assert is_healthy is False
    assert 'ARQ Worker 未运行' in message
    assert 'erp-arq' in message


# ---------------------------------------------------------------------------
# 3. 探测自身异常：必须降级返回而不是抛出，且不误报为"未运行"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_probe_exception_degrades_without_raising(patch_pool):
    patch_pool(_FakePool(raise_exc=ConnectionError('redis 挂了')))

    is_healthy, message = await check_worker_health()

    assert is_healthy is False
    # 必须点出真实异常类型，便于与"worker 真没起"区分
    assert 'ConnectionError' in message


@pytest.mark.asyncio
async def test_probe_timeout_is_bounded(patch_pool):
    """broker 假死（TCP 可连不回包）时，探测必须在 _HEALTH_PROBE_TIMEOUT 内返回。

    修复前实现依赖 client 级超时（conn_timeout=1 × conn_retries=5），
    最坏可把入队请求拖住数十秒。
    """
    patch_pool(_FakePool(hang=30))

    t0 = asyncio.get_running_loop().time()
    is_healthy, message = await check_worker_health()
    elapsed = asyncio.get_running_loop().time() - t0

    assert is_healthy is False
    assert '超时' in message
    assert elapsed < arq_app._HEALTH_PROBE_TIMEOUT + 1.0, f'探测耗时 {elapsed:.1f}s，未受上限约束'


# ---------------------------------------------------------------------------
# 4. Worker 侧配置：哨兵键刷新周期必须足够短
# ---------------------------------------------------------------------------
def test_worker_health_check_interval_is_short():
    """默认 3600s → worker 硬崩溃后最长 1 小时仍误报在线，必须显式缩短。"""
    assert WorkerSettings.health_check_interval == 60
