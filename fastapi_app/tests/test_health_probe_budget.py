"""`/api/health` 的探测预算与可观测性（审计批次4：P1-14）。

## 拦哪种出错

`/api/health` 内部各段探测原先都没有上界，而两端的预算早就定死了：
- 探针侧 `prod_runner._probe_health` 单次 `timeout=5.0s`（同 tick 重试 1 次）；
- 库侧 `pool_timeout=30s` —— 那是「排队等连接」的上界，不是 SQL 超时。

于是连接池饱和 / 库无响应 / broker 黑洞时，端点远超 5s ⇒ 监督器把 `ready` 降为
`degraded` ⇒ `write_status` 写 `ready:false` ⇒ **业务完全正常但健康红**，GUI/巡检
被引向重启一个健康的后端。而这条链路当时还被排除在 prometheus 指标与「慢请求
>3s」日志之外：生产 20 条慢请求里没有一条 `/api/health`，只留下 373 次
`TimeoutError: timed out` 无从归因。

## 本文件各锁一件事

1. `test_probe_budget_below_runner_probe_timeout`：四段预算之和必须小于探针预算；
2. 逐段超时都在预算内返回，且 DB 超时判不健康、备份链超时只降级；
3. `test_degraded_reasons_timeout_is_empty_and_fast`：降级原因也受预算约束
   （它走另一个 socket 超时 5s 的 Redis 客户端，不兜住就会把端点拖过 5s）；
4. 慢健康检查自己会打日志（原先完全静默）；`/api/health` 真实进入 prometheus 指标；
5. ARQ 隔离探针结果有短 TTL 缓存、建池也在同一 deadline 内；
6. 强制重启前监督器独立复检库：库连不上则**有限次**否决重启（并把状态如实降级），
   否决次数用尽后仍回到原逻辑 —— 否决不能是永久的（推送前评审 High）。
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
    """四段之和必须 < prod_runner 单次探针预算（5.0s），否则「业务正常但健康红」。"""
    assert health._probe_budget_s() < 5.0, (
        f'端点预算 {health._probe_budget_s()}s 已越过探针 5.0s 预算（P1-14）'
    )
    assert health._HEALTH_DB_TIMEOUT_S > 0
    assert health._HEALTH_REDIS_TIMEOUT_S > 0
    assert health._HEALTH_BACKUP_SIGNAL_TIMEOUT_S > 0
    assert health._HEALTH_DEGRADED_REASONS_TIMEOUT_S > 0


async def test_db_probe_timeout_is_unhealthy(monkeypatch):
    """DB 探测超过预算 → 判不健康，且必须在预算内返回（不能等 pool_timeout=30s）。"""
    monkeypatch.setattr(health, '_HEALTH_DB_TIMEOUT_S', 0.05)

    async def _hang():
        await asyncio.sleep(5)
        return True

    monkeypatch.setattr(health, 'verify_db_connectivity', _hang)

    started = time.monotonic()
    ok, elapsed_ms = await health._db_healthy()
    elapsed = time.monotonic() - started

    assert ok is False, '探测超时不能报健康（fail-closed）'
    assert elapsed < 1.0, f'DB 探测耗时 {elapsed:.2f}s，说明上界没生效'
    assert elapsed_ms >= 0


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
    ok, _ms = await health._redis_healthy()
    assert ok is False
    assert time.monotonic() - started < 1.0


async def test_backup_signal_timeout_reports_probe_timeout(monkeypatch):
    """备份/ARQ 信号超时 → 上报 probe_timeout，状态只降级、不摘流量。"""
    monkeypatch.setattr(health, '_HEALTH_BACKUP_SIGNAL_TIMEOUT_S', 0.05)

    async def _hang():
        await asyncio.sleep(5)
        return {'ok': True, 'age_hours': 0.1, 'arq_ok': True}

    monkeypatch.setattr(health, '_backup_signal', _hang)

    sig, _ms = await health._backup_signal_bounded()

    assert sig['ok'] is False
    assert sig['note'] == 'probe_timeout'
    # ARQ/broker 挂了不等于数据库不可用：只降级（degraded），不 503 摘流量
    assert health._resolve_status(
        overall_healthy=True, backup_ok=sig['ok'],
        audit_retention_ok=True, numbering_audit_retention_ok=True,
    ) == 'degraded'


async def test_degraded_reasons_timeout_is_empty_and_fast(monkeypatch):
    """降级原因读取超预算 → 按空处理且快速返回（它是展示标签，不能拖垮端点）。

    这一段走 `utils.redis_cache`（socket 超时 5s，与 core.redis_client 不是同一个
    客户端）：不纳入预算时 Redis 黑洞会让端点整体 ≈9.5s（推送前评审 Medium）。
    """
    monkeypatch.setattr(health, '_HEALTH_DEGRADED_REASONS_TIMEOUT_S', 0.05)

    async def _hang():
        await asyncio.sleep(5)
        return ['cache_degraded']

    monkeypatch.setattr(health, 'degraded_reasons_all', _hang)

    started = time.monotonic()
    reasons, elapsed_ms = await health._degraded_reasons_bounded()

    assert reasons == []
    assert time.monotonic() - started < 1.0
    assert elapsed_ms >= 0


# --------------------------------------------------------------- 自观测
def test_slow_health_logs_warning(caplog):
    """慢健康检查必须自己打一条日志（原先 /api/health 完全不在慢请求日志里）。"""
    with caplog.at_level('WARNING'):
        health._log_if_slow_health(
            time.monotonic() - health._HEALTH_SLOW_LOG_S - 1.0, {'db': 5000.0})

    assert any('慢健康检查' in rec.getMessage() for rec in caplog.records), (
        f'慢健康检查没有任何日志：{[r.getMessage() for r in caplog.records]}'
    )


def test_fast_health_does_not_log(caplog):
    with caplog.at_level('WARNING'):
        health._log_if_slow_health(time.monotonic(), {'db': 1.0})
    assert not any('慢健康检查' in rec.getMessage() for rec in caplog.records)


def test_probe_timings_are_per_call_not_global():
    """段耗时必须是调用方传入的局部值：模块级全局会被并发请求互相覆盖（评审 Medium）。"""
    assert not hasattr(health, '_last_probe_ms'), (
        '探针耗时又变回模块级全局了 —— 并发请求/其它探针端点会互相覆盖'
    )
    snap = health._probe_ms_snapshot({'db': 12.0})
    assert snap['db'] == 12.0 and 'budget_ms' in snap


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


def test_supervisor_db_recheck_returns_true_on_success(monkeypatch):
    """连通成功时必须返回 True（否则「永远 False」的退化不会被任何用例抓到）。"""
    import sqlalchemy

    from fastapi_app.core import prod_runner

    seen: dict = {}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute(self, _stmt):
            return None

    class _Engine:
        def connect(self):
            return _Conn()

        def dispose(self):
            seen['disposed'] = True

    def _create_engine(url, **kwargs):
        seen['url'] = url
        seen['kwargs'] = kwargs
        return _Engine()

    monkeypatch.setattr(sqlalchemy, 'create_engine', _create_engine)

    assert prod_runner._db_reachable_from_supervisor(url='postgresql+psycopg://u:p@h/db') is True
    # 复检必须自我限时：一次性空池 + 连接/语句超时
    assert seen['kwargs']['connect_args']['connect_timeout'] == prod_runner._DB_RECHECK_TIMEOUT_S
    assert 'statement_timeout' in seen['kwargs']['connect_args']['options']
    assert seen.get('disposed') is True, '复检用的 engine 必须 dispose（不做池复用）'


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
    """库从监督器也连不上 → 本轮不杀进程树，且状态必须如实降级（ready:false）。"""
    kills: list = []
    svc = _managed(monkeypatch, db_reachable=False, kills=kills)

    svc.poll()

    assert kills == [], '库不可达时仍杀了进程树 —— 事故现场会少一个能报警的进程'
    assert svc.status == 'degraded', '否决重启却不降级 → 状态文件仍写 ready:true，运维看不见'
    assert svc.consecutive_health_fail >= 10, '健康失败计数不该被清零'
    assert svc._db_veto_count == 1


def test_force_restart_veto_is_bounded(monkeypatch):
    """否决不能是永久的：达到上限后仍回到原逻辑重启（可能是本进程自己占满连接）。"""
    from fastapi_app.core import prod_runner

    kills: list = []
    svc = _managed(monkeypatch, db_reachable=False, kills=kills)
    svc._db_veto_count = prod_runner._DB_VETO_MAX_CONSECUTIVE
    # 复检节流会让本轮直接返回 None；这里显式放开，验证「次数用尽即重启」这条分支
    svc._last_db_recheck_at = 0.0

    svc.poll()

    assert kills == [1], '否决次数用尽后仍不重启 —— 自伤型不可达会让进程永久卡死'
    assert svc.status == 'crashed'
    assert svc._db_veto_count == 0, '重启后否决计数必须清零'


def test_force_restart_proceeds_when_db_reachable(monkeypatch):
    """库可达 + 探针持续失败 10 分钟 → 照旧强制重启（原行为不变）。"""
    kills: list = []
    svc = _managed(monkeypatch, db_reachable=True, kills=kills)

    svc.poll()

    assert kills == [1], '库可达时应当按原逻辑强制重启'
    assert svc.status == 'crashed'


def test_db_recheck_is_throttled(monkeypatch):
    """复检必须节流：降级期间每 tick 都新建 engine 会把主循环单轮从 3s 拉到 ~6s。"""
    from fastapi_app.core import prod_runner

    calls: list = []
    svc = _managed(monkeypatch, db_reachable=False, kills=[])
    monkeypatch.setattr(prod_runner, '_db_reachable_from_supervisor',
                        lambda *a, **kw: (calls.append(1), False)[1])

    svc._last_db_recheck_at = time.monotonic()  # 刚探过
    assert svc._db_recheck_throttled() is None
    assert calls == [], '节流窗口内仍去敲了库'

    svc._last_db_recheck_at = time.monotonic() - prod_runner._DB_RECHECK_MIN_INTERVAL_S - 1
    assert svc._db_recheck_throttled() is False
    assert calls == [1]
