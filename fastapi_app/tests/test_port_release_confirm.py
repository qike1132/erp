"""端口清理必须**确认**结果（2026-10-26 重启实测事故）。

`taskkill_many` 是 best-effort、异常全吞；旧实现杀完就按 flags 返回 'killed'，
即使 taskkill 因为「提权进程拒绝访问」一个都没杀掉。调用方据此认为端口已清空，
于是新实例绑在被占用的端口上（Windows SO_REUSEADDR 允许两个 LISTEN），旧实例继续
accept —— 界面上「启动成功」，线上跑的还是旧代码。

本文件锁两件事：
1. `kill_port_sync` 杀完要复扫，仍有非受管占用者就返回 'still_occupied'（错误态）；
2. `_release_ports` 必须把它当成失败（返回 False + ERROR 日志），而不是静默继续。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from server_manager import windows_ops


@pytest.fixture
def fast(monkeypatch):
    """去掉实现里的 0.5s 轮询等待。"""
    monkeypatch.setattr(windows_ops.time, "sleep", lambda _s: None)


def _sequence(values):
    """按调用顺序返回 values，用完后固定返回最后一个。"""
    calls = {"i": 0}

    def _fn(*_a, **_k):
        idx = min(calls["i"], len(values) - 1)
        calls["i"] += 1
        return list(values[idx])

    return _fn


def test_clean_when_port_free(monkeypatch, fast):
    monkeypatch.setattr(windows_ops, "find_port_pids", lambda _p: [])
    killed: list = []
    monkeypatch.setattr(windows_ops, "taskkill_many", lambda pids: killed.append(pids))
    assert windows_ops.kill_port_sync(5002) == "clean"
    assert killed == []


def test_killed_when_kill_succeeds(monkeypatch, fast):
    # 轮询里先看到占用者，杀完复扫为空
    monkeypatch.setattr(windows_ops, "find_port_pids", _sequence([["111"], []]))
    killed: list = []
    monkeypatch.setattr(windows_ops, "taskkill_many", lambda pids: killed.append(pids))

    assert windows_ops.kill_port_sync(5002) == "killed"
    assert killed == [[111]]


def test_still_occupied_when_kill_is_denied(monkeypatch, fast):
    """taskkill 被拒（提权进程）→ 端口还在 → 必须如实上报，不能报 killed。"""
    monkeypatch.setattr(windows_ops, "find_port_pids", lambda _p: ["25064"])
    monkeypatch.setattr(windows_ops, "taskkill_many", lambda _pids: None)  # 静默失败

    assert windows_ops.kill_port_sync(5002) == "still_occupied"


def test_all_exempted_keeps_managed_processes(monkeypatch, fast):
    monkeypatch.setattr(windows_ops, "find_port_pids", lambda _p: ["999"])
    killed: list = []
    monkeypatch.setattr(windows_ops, "taskkill_many", lambda pids: killed.append(pids))

    state = windows_ops.kill_port_sync(5002, managed_pids_fn=lambda: {"999"})

    assert state == "all_exempted"
    assert killed == [], "受管进程绝不能杀（NSSM 会 5 秒拉起，形成杀不死的循环）"


def test_managed_unknown_fails_safe(monkeypatch, fast):
    monkeypatch.setattr(windows_ops, "find_port_pids", lambda _p: ["999"])
    killed: list = []
    monkeypatch.setattr(windows_ops, "taskkill_many", lambda pids: killed.append(pids))

    assert windows_ops.kill_port_sync(5002, managed_pids_fn=lambda: None) == "managed_unknown"
    assert killed == []


# ---------------------------------------------------------------------------
# 管理器侧：必须消费 still_occupied
# ---------------------------------------------------------------------------
def _app(monkeypatch, *, kill_state: str, survivors=("25064",)):
    import server_manager.app as sm

    app = object.__new__(sm.ServerManagerApp)
    logs: list[tuple[str, str]] = []
    app.log_message = lambda text, level="INFO": logs.append((text, level))
    app._managed_service_pids = lambda: set()
    app._kill_port_sync = lambda *_a, **_k: kill_state
    app._find_port_pids = lambda *_a, **_k: list(survivors)
    return app, logs


def test_release_ports_returns_false_and_errors_when_still_occupied(monkeypatch):
    app, logs = _app(monkeypatch, kill_state="still_occupied")

    assert app._release_ports() is False

    errors = [t for t, lvl in logs if lvl == "ERROR"]
    assert errors and "25064" in errors[0]
    assert "taskkill" in errors[0], "必须给出可执行的处置提示"


def test_release_ports_returns_true_when_clean(monkeypatch):
    app, logs = _app(monkeypatch, kill_state="clean")

    assert app._release_ports() is True
    assert logs == []


def test_release_ports_returns_false_when_managed_unknown(monkeypatch):
    app, _ = _app(monkeypatch, kill_state="managed_unknown")

    assert app._release_ports() is False


def test_release_ports_returns_false_on_exception(monkeypatch):
    app, logs = _app(monkeypatch, kill_state="clean")

    def _boom(*_a, **_k):
        raise OSError("netstat 不可用")

    app._kill_port_sync = _boom

    assert app._release_ports() is False
    assert any(level == "ERROR" for _t, level in logs)


def test_release_ports_allows_managed_occupancy(monkeypatch):
    """生产正在跑时点启动：占用者全是受管进程 → 不算失败（随后由服务停止收走）。"""
    app, logs = _app(monkeypatch, kill_state="all_exempted")

    assert app._release_ports() is True
    assert logs == []


def test_state_contract_is_documented():
    """六态契约写进文档字符串，避免以后又被简化成两布尔。"""
    doc = windows_ops.kill_port_sync.__doc__ or ""
    for state in ("clean", "killed", "all_exempted", "killed_and_exempted",
                  "managed_unknown", "still_occupied"):
        assert state in doc, f"返回值 {state} 未在文档中约定"


_ = SimpleNamespace  # 保持导入（部分用例按需构造替身）
