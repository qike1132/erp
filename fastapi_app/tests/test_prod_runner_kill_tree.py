"""kill_tree 软杀优先测试（2026-10-11 复核 P1-9 / 2026-10-13 修正其回归）。

原实现对 uvicorn 子进程一律 `taskkill /F /T`，lifespan 关停段从不执行
（复核实测 84/160 次进入关停段未走完、收尾哨兵自 2026-10-02 起再未亮）。
契约：Windows 先发软杀（taskkill 不带 /F）；**软杀报告成功才轮询等待**，
否则立刻升级 /F。

2026-10-13：P1-9 原版无条件等 4s，而软杀对 CREATE_NO_WINDOW 子进程实测
0.06s 就回 rc=128（「只能强制终止此进程(带 /F 选项)」）、一个都没杀掉 ——
白等的 4s 超出 NSSM 的 3s 停机预算，监督器被 TerminateProcess 掉，
uvicorn 进程树成为继续占着 :5002 的孤儿（当日 08:12 现场）。
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
    # 必须钉住平台：kill_tree 在 os.name == "nt" 才走 taskkill 分支。不钉的话在
    # Linux CI 上会落进 POSIX 分支（os.killpg → self.proc.terminate()），
    # _FakeProc 没有 terminate → AttributeError，断言 /F 也永远不成立。
    monkeypatch.setattr(prod_runner.os, "name", "nt")
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
    # 同上：钉住平台，否则 Linux CI 会落进 POSIX 分支。
    monkeypatch.setattr(prod_runner.os, "name", "nt")
    svc.kill_tree()
    assert any("/F" in c for c in calls), f"软杀超时后必须升级 /F: {calls}"


def test_failed_soft_kill_escalates_without_waiting(monkeypatch) -> None:
    """软杀报告失败（Windows 实测 rc=128）→ 不进入等待窗口，立刻硬杀。

    等待窗口只在软杀**报告成功**时才有意义。白等会把监督器拖出 NSSM 的
    3s 停机预算（AppStopMethodConsole/Threads 各 1500ms），监督器被
    TerminateProcess 掉，uvicorn 进程树就没人回收、成为占着 :5002 的孤儿。
    """
    proc = _FakeProc(exit_after=10**9)  # 永不自己退出
    svc = _make_svc(proc)
    calls: list[list[str]] = []
    slept: list[float] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # 真实世界：不带 /F 的 taskkill 对 CREATE_NO_WINDOW 子进程回 128
        return subprocess.CompletedProcess(cmd, 128 if "/F" not in cmd else 0)

    monkeypatch.setattr(prod_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(prod_runner.time, "sleep", lambda s: slept.append(s))
    # 钉住平台，否则 Linux CI 会落进 POSIX 分支
    monkeypatch.setattr(prod_runner.os, "name", "nt")
    svc.kill_tree()
    assert any("/F" in c for c in calls), f"软杀失败必须立刻硬杀: {calls}"
    assert not slept, f"软杀失败不得进入等待窗口，实际 sleep={slept}"


def test_soft_kill_success_but_no_exit_is_logged(monkeypatch, capsys) -> None:
    """软杀报成功却没在窗口内退出 → 升级硬杀，且**必须留痕**。

    否则「优雅关停没走完」只能靠事后发现收尾哨兵不亮来反推（P1-9 的教训）。
    """
    proc = _FakeProc(exit_after=10**9)  # 永不自己退出
    svc = _make_svc(proc)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)  # 软杀「成功」

    monkeypatch.setattr(prod_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(prod_runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(prod_runner, "_SOFT_KILL_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(prod_runner, "_SOFT_KILL_POLL_INTERVAL", 0.001)
    monkeypatch.setattr(prod_runner.os, "name", "nt")
    svc.kill_tree()
    out = capsys.readouterr().out
    assert any("/F" in c for c in calls), f"窗口内没退出必须升级硬杀: {calls}"
    assert "软杀成功但" in out and "升级硬杀" in out, f"升级原因必须留痕，实际输出={out!r}"


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


def test_kill_tree_returns_true_and_clears_identity_when_dead(monkeypatch) -> None:
    """确认终止 → 返回 True 并清空 proc（调用方可安全安排新进程）。"""
    proc = _FakeProc(exit_after=1)
    svc = _make_svc(proc)

    def fake_run(cmd, **kwargs):
        proc._polls = proc._exit_after
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(prod_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(prod_runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(prod_runner, "_SOFT_KILL_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(prod_runner.os, "name", "nt")

    assert svc.kill_tree() is True
    assert svc.proc is None


def test_kill_tree_returns_false_and_keeps_identity_when_survives(monkeypatch) -> None:
    """H2：终止后仍存活 → 返回 False 且**不得**清 self.proc。

    旧实现无论成败都 ``self.proc = None``，调用方接着 ``_mark_crashed()`` 起新实例，
    而旧进程仍占着 :5002 —— 同端口双进程且监督器永久失去旧进程句柄。
    """
    proc = _FakeProc(exit_after=10**9)
    svc = _make_svc(proc)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(prod_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(prod_runner.time, "sleep", lambda s: None)
    monkeypatch.setattr(prod_runner, "_SOFT_KILL_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(prod_runner, "_SOFT_KILL_POLL_INTERVAL", 0.001)
    monkeypatch.setattr(prod_runner.os, "name", "nt")

    assert svc.kill_tree() is False
    assert svc.proc is proc, "未确认终止必须保留句柄，否则再也杀不掉该进程"
