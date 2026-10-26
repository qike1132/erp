"""P0（2026-10-26 重启实测事故）回归锁：健康 200 必须能证明「应答的是我」。

事故现场：08:11 起的孤儿后端树一直持有 :5002；15:11 用户点「启动生产服务」，
新栈（新代码）也确实起来了、日志打了 ``Uvicorn running``，但 Windows 的
SO_REUSEADDR 让两个 socket 绑同一端口，孤儿继续 accept —— 站点跑的仍是旧代码。
而 ``prod_runner.json`` 显示 ``ready: true``：探活只看 HTTP 200，不看**谁在应答**。

本文件锁定修复后的两道判据：
1. 应答体 ``runtime.pid`` 必须落在本进程树内（无 ``runtime`` = 旧代码/外挂，也判失败）；
2. 端口上不得存在非本进程树的 LISTEN（双实例时新实例收不到流量）。
两者任一不成立 → ``degraded``（ready:false），且**不重启**自家子进程（重启没用）。
"""
from __future__ import annotations

from types import SimpleNamespace

import psutil

from fastapi_app.core import prod_runner as pr


def _managed(monkeypatch, *, verify: bool = True):
    m = pr._Managed(
        "后端(uvicorn)", ["x"], cwd=pr.PROJECT_ROOT,
        health_url="http://127.0.0.1:5002/api/health",
        verify_identity=verify,
    )
    alive = SimpleNamespace(pid=4242, poll=lambda: None)
    m.proc = alive
    m.status = "running"
    m.consecutive_health_fail = 0
    m.health_fail_start = None
    m.next_start = 0.0
    return m


# ---------------------------------------------------------------------------
# 判据 1：runtime.pid 归属
# ---------------------------------------------------------------------------
def test_verify_identity_rejects_missing_runtime(monkeypatch):
    """无 runtime 字段 = 不提供指纹的旧代码（本次事故的直接指纹）→ 必须判失败。"""
    m = _managed(monkeypatch)
    monkeypatch.setattr(pr, "_http_json", lambda *_a, **_k: {"status": "healthy"})

    problem = m._verify_identity()

    assert problem and "runtime" in problem


def test_verify_identity_rejects_foreign_pid(monkeypatch):
    m = _managed(monkeypatch)
    monkeypatch.setattr(
        pr, "_http_json",
        lambda *_a, **_k: {"status": "healthy", "runtime": {"pid": 999999, "commit": "a" * 40}},
    )
    monkeypatch.setattr(pr, "_pid_in_tree", lambda pid, root: False)

    problem = m._verify_identity()

    assert problem and "999999" in problem


def test_verify_identity_accepts_own_worker(monkeypatch):
    m = _managed(monkeypatch)
    monkeypatch.setattr(
        pr, "_http_json",
        lambda *_a, **_k: {"status": "healthy", "runtime": {"pid": 4242, "commit": "a" * 40}},
    )
    monkeypatch.setattr(pr, "_pid_in_tree", lambda pid, root: True)
    monkeypatch.setattr(pr, "_foreign_listeners", lambda port, root: set())

    assert m._verify_identity() is None


# ---------------------------------------------------------------------------
# 判据 2：端口上不许有别人的 LISTEN
# ---------------------------------------------------------------------------
def test_verify_identity_rejects_foreign_listener(monkeypatch):
    """双实例：应答者是我的 worker，但端口上还挂着别人的监听 → 迟早被抢流量。"""
    m = _managed(monkeypatch)
    monkeypatch.setattr(
        pr, "_http_json",
        lambda *_a, **_k: {"status": "healthy", "runtime": {"pid": 4242}},
    )
    monkeypatch.setattr(pr, "_pid_in_tree", lambda pid, root: True)
    monkeypatch.setattr(pr, "_foreign_listeners", lambda port, root: {25064})

    problem = m._verify_identity()

    assert problem and "25064" in problem


def test_foreign_listeners_excludes_own_tree(monkeypatch):
    conns = [
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=5002), pid=4242),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=5002), pid=777),
        SimpleNamespace(status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=3000), pid=888),
    ]
    monkeypatch.setattr(psutil, "net_connections", lambda kind="tcp": conns, raising=False)
    monkeypatch.setattr(
        psutil, "Process",
        lambda pid: SimpleNamespace(children=lambda recursive=True: [SimpleNamespace(pid=4242)]),
        raising=False,
    )

    assert pr._foreign_listeners(5002, 4242) == {777}


def test_foreign_listeners_fails_open(monkeypatch):
    """取证失败（psutil 报错）返回空集：不能因为探针能力缺失把正常服务判成故障。"""
    def _boom(*_a, **_k):
        raise OSError("denied")

    monkeypatch.setattr(psutil, "net_connections", _boom, raising=False)

    assert pr._foreign_listeners(5002, 4242) == set()


# ---------------------------------------------------------------------------
# poll() 接线：不得在身份未证实时判 ready
# ---------------------------------------------------------------------------
def test_poll_marks_degraded_when_identity_unproven(monkeypatch):
    m = _managed(monkeypatch)
    monkeypatch.setattr(m, "_probe_health", lambda: (True, 0.05))
    m._verify_identity = lambda: "应答进程 pid=25064 不属于本进程树"

    m.poll()

    assert m.status == "degraded", "身份未证实不得判 ready（否则上线等于没上）"
    assert m.identity_problem


def test_poll_ready_when_identity_proven(monkeypatch):
    m = _managed(monkeypatch)
    monkeypatch.setattr(m, "_probe_health", lambda: (True, 0.05))
    m._verify_identity = lambda: None

    m.poll()

    assert m.status == "ready"
    assert m.identity_problem is None


def test_identity_check_runs_once_per_start(monkeypatch):
    """身份证实只做一次（每 tick 都去 net_connections 太贵），重启后重新证实。"""
    m = _managed(monkeypatch)
    monkeypatch.setattr(m, "_probe_health", lambda: (True, 0.05))
    calls = []

    def _verify():
        calls.append(1)
        return None

    m._verify_identity = _verify
    m.poll()
    m.poll()

    assert len(calls) == 1
    assert m.status == "ready"

    # start() 会重置标记（不真起进程，只验证重置逻辑）
    m._identity_checked = True
    m.proc = SimpleNamespace(pid=4242, poll=lambda: 0, wait=lambda: None)  # 已退出
    m._logf = None
    m.start()
    assert m._identity_checked is False


def test_verify_identity_skipped_when_flag_off(monkeypatch):
    """未开启校验的服务（如 ARQ）行为不变：健康通过即 ready。"""
    m = _managed(monkeypatch, verify=False)
    monkeypatch.setattr(m, "_probe_health", lambda: (True, 0.05))
    called = []
    monkeypatch.setattr(m, "_verify_identity", lambda: called.append(1) or "boom")

    m.poll()

    assert m.status == "ready"
    assert called == []
