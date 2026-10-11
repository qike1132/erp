"""kill_tree 软杀优先测试（2026-10-11 复核 P1-9）。

原实现对 uvicorn 子进程一律 `taskkill /F /T`，lifespan 关停段从不执行
（复核实测 84/160 次进入关停段未走完、收尾哨兵自 2026-10-02 起再未亮）。
新契约：Windows 先发软杀（taskkill 不带 /F），轮询等退出，超时才升级 /F。
"""

from __future__ import annotations

import subprocess

from fastapi_app.core import prod_runner


class _FakeProc:
    def __init__(self, exit_after: int = 1) -> None:
        self.pid = 4242
        self._exited = False
        self._exit_after = exit_after
        self._polls = 0
        self._commands: list[list[str]] = []
        self.returncode = None

    def poll(self) -> int | None:
        self._polls += 1
        if self._polls > self._exit_after:
            self._exited = True
            self.returncode = 0
            return 0
        return None

    def wait(self, timeout=None):
        return 0 if self._exited else self._raise_timeout(timeout)

    def _raise_timeout(self, timeout):
        raise subprocess.TimeoutExpired("proc", timeout)


def _make_svc(proc: _FakeProc):
    svc = prod_runner._Managed.__new__(prod_runner._Managed)
    svc.name = "backend"
    svc.proc = proc
    svc._logf = None
    return svc


def test_soft_kill_tried_first_without_force(monkeypatch) -> None:
    """软杀窗口内退出：不调用带 /F 的 taskkill。"""
    proc = _FakeProc(exit_after=1)
    svc = _make_svc(proc)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "/F" in cmd:
            return subprocess.CompletedProcess(cmd, 128)
        proc._polls = proc._exit_after  # 软杀后下一轮 poll 判定退出
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(prod_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(prod_runner.time, "sleep", lambda s: None)
    svc.kill_tree()
    assert calls, "应至少调用过一次 taskkill"
    assert all("/F" not in c for c in calls), f"软杀窗口内不应升级 /F: {calls}"


def test_escalates_to_force_after_timeout(monkeypatch) -> None:
    """软杀无效（进程不退）→ 升级带 /F 的硬杀。"""
    proc = _FakeProc(exit_after=10**9)
    svc = _make_svc(proc)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(prod_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(prod_runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(prod_runner, "_SOFT_KILL_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(prod_runner, "_SOFT_KILL_POLL_INTERVAL", 0.001)
    svc.kill_tree()
    assert any("/F" in c for c in calls), f"软杀超时后必须升级 /F: {calls}"


def test_non_windows_uses_sigterm(monkeypatch) -> None:
    """非 Windows 路径维持 SIGTERM 行为（回归保护）。"""
    proc = _FakeProc()
    svc = _make_svc(proc)

    class _FakeOS:
        def killpg(self, pgid, sig):
            seen["pgid"] = pgid
            seen["sig"] = sig
            raise ProcessLookupError

        def getpgid(self, pid):
            return pid

    seen = {}
    monkeypatch.setattr(prod_runner.os, "name", "posix")
    monkeypatch.setattr(prod_runner.os, "killpg", _FakeOS().killpg, raising=False)
    monkeypatch.setattr(prod_runner.os, "getpgid", _FakeOS().getpgid, raising=False)
    import signal

    proc.terminate = lambda: seen.setdefault("terminated", True)
    svc.kill_tree()
    assert seen["sig"] == signal.SIGTERM
    assert seen.get("terminated"), "ProcessLookupError 后应回退 terminate()"
