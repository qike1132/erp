"""`/api/health` 的探测预算与可观测性（审计批次4：P1-14）。

## 拦哪种出错

`/api/health` 内部三段探测都没有上界，而两端的预算早就定死了：
- 探针侧 `prod_runner._probe_health` 单次 `timeout=5.0s`（同 tick 重试 1 次）；
- 库侧 `pool_timeout=30s` —— 那是「排队等连接」的上界，不是 SQL 超时。

于是连接池饱和 / 库无响应 / broker 黑洞时，端点远超 5s ⇒ 监督器把 `ready` 降为
`degraded` ⇒ `write_status` 写 `ready:false` ⇒ **业务完全正常但健康红**，GUI/巡检
被引向重启一个健康的后端。而这条链路当时还被排除在 prometheus 指标与「慢请求
>3s」日志之外：生产 20 条慢请求里没有一条 `/api/health`，只留下 373 次
`TimeoutError: timed out` 无从归因。

## 本文件各锁一件事

1. `test_probe_budget_below_runner_probe_timeout`：三段预算之和必须小于探针预算；
2. `test_db_probe_timeout_is_unhealthy` / `test_redis_probe_timeout_is_false` /
   `test_backup_signal_timeout_reports_probe_timeout`：逐段超时都在预算内返回，
   且 DB 超时判不健康、备份链超时只降级；
3. `test_slow_health_logs_warning`：慢健康检查自己会打日志（原先完全静默）；
4. `test_metrics_count_health_endpoint`：`/api/health` 真实进入 prometheus 指标；
5. `test_arq_probe_result_is_cached` / `test_arq_probe_pool_creation_is_bounded`：
   ARQ 隔离探针结果有短 TTL 缓存、建池也在同一 deadline 内；
6. `test_force_restart_*`：强制重启前监督器独立复检库；库连不上就不杀进程树。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi_app.core import health


# --------------------------------------------------------------- ① 预算对齐
def test_probe_budget_below_runner_probe_timeout():
    """三段之和必须 < prod_runner 单次探针预算（5.0s），否则「业务正常但健康红」。"""
    assert health._probe_budget_s() < 5.0, (
        f'端点预算 {health._probe_budget_s()}s 已越过探针 5.0s 预算（P1-14）'
    )
    assert health._HEALTH_DB_TIMEOUT_S > 0
    assert health._HEALTH_REDIS_TIMEOUT_S > 0
    assert health._HEALTH_BACKUP_SIGNAL_TIMEOUT_S > 0


async def test_db_probe_timeout_is_unhealthy(monkeypatch):
    """DB 探测超过预算 → 判不健康，且必须在预算内返回（不能等 pool_timeout=30s）。"""
    monkeypatch.setattr(health, '_HEALTH_DB_TIMEOUT_S', 0.05)

    async def _hang():
        await asyncio.sleep(5)
        return True

    monkeypatch.setattr(health, 'verify_db_connectivity', _hang)

    started = time.monotonic()
    ok = await health._db_healthy()
    elapsed = time.monotonic() - started

    assert ok is False, '探测超时不能报健康（fail-closed）'
    assert elapsed < 1.0, f'DB 探测耗时 {elapsed:.2f}s，说明上界没生效'
    assert health._last_probe_ms['db'] >= 0


async def test_redis_probe_timeout_is_false(monkeypatch):
    """Redis ping 挂着不回 → 判 False，同样在预算内返回。"""
    from fastapi_app.core import redis_client

    monkeypatch.setattr(health, '_HEALTH_REDIS_TIMEOUT_S', 0.05)

    class _HangClient:
        async def ping(self):
            await asyncio.sleep(5)
            return True

    async def _client():
        return _HangClient()

    monkeypatch.setattr(redis_client, 'get_async_redis_client', _client)

    started = time.monotonic()
    assert await health._redis_healthy() is False
    assert time.monotonic() - started < 1.0


async def test_backup_signal_timeout_reports_probe_timeout(monkeypatch):
    """备份/ARQ 信号超时 → 上报 probe_timeout，状态只降级、不摘流量。"""
    monkeypatch.setattr(health, '_HEALTH_BACKUP_SIGNAL_TIMEOUT_S', 0.05)

    async def _hang():
        await asyncio.sleep(5)
        return {'ok': True, 'age_hours': 0.1, 'arq_ok': True}

    monkeypatch.setattr(health, '_backup_signal', _hang)

    sig = await health._backup_signal_bounded()

    assert sig['ok'] is False
    assert sig['note'] == 'probe_timeout'
    # ARQ/broker 挂了不等于数据库不可用：只降级（degraded），不 503 摘流量
    assert health._resolve_status(
        overall_healthy=True, backup_ok=sig['ok'],
        audit_retention_ok=True, numbering_audit_retention_ok=True,
    ) == 'degraded'


# --------------------------------------------------------------- 自观测
def test_slow_health_logs_warning(caplog):
    """慢健康检查必须自己打一条日志（原先 /api/health 完全不在慢请求日志里）。"""
    with caplog.at_level('WARNING'):
        health._log_if_slow_health(time.monotonic() - health._HEALTH_SLOW_LOG_S - 1.0)

    assert any('慢健康检查' in rec.getMessage() for rec in caplog.records), (
        f'慢健康检查没有任何日志：{[r.getMessage() for r in caplog.records]}'
    )


def test_fast_health_does_not_log(caplog):
    with caplog.at_level('WARNING'):
        health._log_if_slow_health(time.monotonic())
    assert not any('慢健康检查' in rec.getMessage() for rec in caplog.records)


def test_metrics_count_health_endpoint():
    """`/api/health` 必须真实进入 prometheus 指标（不再整体跳过）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from prometheus_client import generate_latest

    from fastapi_app.core import metrics, middleware

    if not metrics.METRICS_AVAILABLE:
        pytest.skip('prometheus_client 未安装（指标链路整体不可用）')

    app = FastAPI()

    @app.get('/api/health')
    def _h():
        return {'status': 'ok'}

    middleware._setup_prometheus(app)
    with TestClient(app) as client:
        assert client.get('/api/health').status_code == 200

    body = generate_latest().decode('utf-8')
    assert 'endpoint="/api/health"' in body, (
        '健康端点仍被排除在指标之外 —— 端点慢了无法归因（P1-14②）'
    )


# --------------------------------------------------------------- ③ ARQ 探针
async def test_arq_probe_result_is_cached(monkeypatch):
    """TTL 内不重复握手 broker（原先每次冷计算都 create_pool + aclose）。"""
    from fastapi_app.core import arq_app

    calls: list[float] = []

    async def _once(timeout: float) -> bool:
        calls.append(timeout)
        return True

    monkeypatch.setattr(arq_app, '_probe_arq_once', _once)
    monkeypatch.setattr(arq_app, '_probe_cache', {'at': 0.0, 'ok': False})

    assert await arq_app.probe_worker_health_isolated(1.0) is True
    assert await arq_app.probe_worker_health_isolated(1.0) is True
    assert len(calls) == 1, 'TTL 内仍在重复建池握手'

    arq_app._probe_cache['at'] = time.monotonic() - arq_app._PROBE_CACHE_TTL_S - 1
    assert await arq_app.probe_worker_health_isolated(1.0) is True
    assert len(calls) == 2, 'TTL 过期后必须重新探测'


async def test_arq_probe_pool_creation_is_bounded(monkeypatch):
    """建池也在同一个 deadline 内（原先只有 pool.get() 受约束，可拖 ~10s）。"""
    from fastapi_app.core import arq_app

    async def _hang(*_a, **_kw):
        await asyncio.sleep(5)

    monkeypatch.setattr(arq_app, 'create_pool', _hang)

    started = time.monotonic()
    ok = await arq_app._probe_arq_once(0.05)
    elapsed = time.monotonic() - started

    assert ok is False
    assert elapsed < 1.0, f'建池耗时 {elapsed:.2f}s，说明 timeout 没覆盖 create_pool'


# --------------------------------------------------------------- ④ 监督器复检
def test_supervisor_db_recheck_detects_unreachable(monkeypatch):
    """独立复检必须真连库：连不上就是 False（不能只看探针）。"""
    from fastapi_app.core import prod_runner

    monkeypatch.setattr(prod_runner, '_DB_RECHECK_TIMEOUT_S', 1)

    # 127.0.0.1:1 没有监听 → 连接立刻被拒
    assert prod_runner._db_reachable_from_supervisor(
        url='postgresql+psycopg://u:p@127.0.0.1:1/erp_nope') is False


def _managed(monkeypatch, *, db_reachable, kills):
    """造一个只走 poll() 决策分支的受监督服务（不启进程、不打网络）。"""
    from fastapi_app.core import prod_runner

    svc = prod_runner._Managed(
        'api', ['noop'], Path('.'), health_url='http://127.0.0.1:1/api/health',
        workers=4,
    )
    svc.proc = SimpleNamespace(poll=lambda: None, returncode=None)  # 进程"存活"
    svc.status = 'ready'
    svc.consecutive_health_fail = 10
    svc.health_fail_start = (
        time.monotonic() - prod_runner._DEGRADED_RESTART_MIN_WINDOW_S - 10
    )
    monkeypatch.setattr(svc, '_probe_health', lambda: (False, 5.0))
    monkeypatch.setattr(prod_runner, '_db_reachable_from_supervisor',
                        lambda *a, **kw: db_reachable)
    monkeypatch.setattr(svc, 'kill_tree', lambda: (kills.append(1), True)[1])
    return svc


def test_force_restart_skipped_when_db_unreachable(monkeypatch):
    """库从监督器也连不上 → 根因不在 API 进程，不杀进程树（P1-14④）。"""
    kills: list = []
    svc = _managed(monkeypatch, db_reachable=False, kills=kills)

    svc.poll()

    assert kills == [], '库不可达时仍杀了进程树 —— 事故现场会少一个能报警的进程'
    assert svc.status != 'crashed'
    assert svc.consecutive_health_fail >= 10, '健康失败计数不该被清零'


def test_force_restart_proceeds_when_db_reachable(monkeypatch):
    """库可达 + 探针持续失败 10 分钟 → 照旧强制重启（原行为不变）。"""
    kills: list = []
    svc = _managed(monkeypatch, db_reachable=True, kills=kills)

    svc.poll()

    assert kills == [1], '库可达时应当按原逻辑强制重启'
    assert svc.status == 'crashed'
