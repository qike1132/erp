"""后端健康型进程「误杀」修复的回归测试（D7）。

背景（2026-09-17 取证）：`_Managed.poll()` 旧逻辑在健康检查持续失败时**无条件**
`kill_tree()`，把「探针偶发超时（进程其实健在）」与「进程真的死了」混为一谈，造成
大量误杀（累计误杀次数见另报，口径以实测定值为准）。

修复后：仅当「连续失败 ≥3 次」且「失败窗口 ≥90s」且「进程确已死亡」三者同时成立
才重启；进程存活时只告警 + 放宽退避，绝不误杀。探针超时 2s→5s 且同 tick 重试 1 次。

全部打桩，绝不触碰任何真实服务。
"""
from __future__ import annotations

import time

import pytest

from fastapi_app.core import prod_runner


class _AliveProc:
    """进程存活（poll() 恒返回 None）。"""

    pid = 4321
    returncode = None

    def poll(self) -> None:
        return None


class _DeadProc:
    """进程已退出（poll() 返回退出码）。"""

    pid = 4321
    returncode = 1

    def poll(self) -> int:
        return 1


class _RaceProc:
    """竞态：探针期间 master 死掉——顶部 poll 返 None，复检 poll 返退出码。"""

    pid = 4321
    returncode = 1

    def __init__(self) -> None:
        self._n = 0

    def poll(self) -> int | None:
        self._n += 1
        return None if self._n == 1 else 1


def _mk(proc, workers: int = 8) -> prod_runner._Managed:
    m = prod_runner._Managed(
        "后端(uvicorn)", ["x"], prod_runner.PROJECT_ROOT,
        health_url="http://127.0.0.1:5002/api/health", workers=workers,
    )
    m.proc = proc
    m.status = "ready"
    return m


# ---------------------------------------------------------------------------
# 纯函数：判定与退避
# ---------------------------------------------------------------------------
class TestShouldRestart:
    def test_restart_only_when_dead_and_thresholds_met(self):
        assert prod_runner._should_restart(3, 90.0, proc_alive=False) is True
        assert prod_runner._should_restart(9, 500.0, proc_alive=False) is True

    def test_no_restart_when_process_alive(self):
        """核心：进程活着，哪怕连续失败很久也绝不重启（消掉误杀）。"""
        assert prod_runner._should_restart(50, 9999.0, proc_alive=True) is False

    def test_no_restart_when_below_thresholds(self):
        assert prod_runner._should_restart(2, 9999.0, proc_alive=False) is False  # 次数不足
        assert prod_runner._should_restart(9, 10.0, proc_alive=False) is False    # 窗口不足


class TestNextBackoff:
    def test_ladder_caps(self):
        assert prod_runner._next_backoff(2.0, 0) == 4.0
        assert prod_runner._next_backoff(16.0, 3) == 32.0
        assert prod_runner._next_backoff(200.0, 3) == 300.0  # 封顶 300
        assert prod_runner._next_backoff(999.0, 9) == 300.0  # step 超界仍封顶


# ---------------------------------------------------------------------------
# poll()：进程存活但健康失败 → 不杀
# ---------------------------------------------------------------------------
class TestPollKeepsAliveProcess:
    def test_does_not_kill_alive_process(self, monkeypatch, capsys):
        m = _mk(_AliveProc())
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        killed = {"n": 0}
        monkeypatch.setattr(m, "kill_tree", lambda: killed.__setitem__("n", killed["n"] + 1))
        m.consecutive_health_fail = 5
        m.health_fail_start = time.monotonic() - 200.0  # 窗口已远超 90s

        m.poll()

        assert killed["n"] == 0, "进程存活时绝不能 kill_tree"
        assert m.status != "crashed"
        assert m.consecutive_health_fail == 6  # 计数继续累加
        assert m.delay > 2.0  # 放宽退避
        out = capsys.readouterr().out
        assert "健康检查失败但进程存活" in out
        assert "proc_alive=True" in out
        assert "workers=8" in out

    def test_healthy_resets_counters(self, monkeypatch):
        m = _mk(_AliveProc())
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: True)
        m.consecutive_health_fail = 7
        m.delay = 60.0
        m.poll()
        assert m.status == "ready"
        assert m.consecutive_health_fail == 0
        assert m.delay == 2.0


# ---------------------------------------------------------------------------
# poll()：进程确已退出 → 安排重启
# ---------------------------------------------------------------------------
class TestPollRestartsDeadProcess:
    def test_exited_process_schedules_restart(self):
        m = _mk(_DeadProc())
        m.poll()
        assert m.status == "crashed"
        assert m.next_start > 0
        assert m.delay > 2.0

    def test_proc_dead_during_probe_is_restarted(self, monkeypatch):
        """探针最长 ~10s，期间 master 可能死掉 → 复检为死则允许强制重启。"""
        m = _mk(_RaceProc())
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        killed = {"n": 0}

        def _kill() -> bool:
            killed["n"] += 1
            return True  # 已确认终止（H2 契约：kill_tree 返回 bool）

        monkeypatch.setattr(m, "kill_tree", _kill)
        m.consecutive_health_fail = 2
        m.health_fail_start = time.monotonic() - 200.0

        m.poll()

        assert killed["n"] == 1
        assert m.status == "crashed"


# ---------------------------------------------------------------------------
# H2：杀树未确认成功 → 不得清身份、不得 mark_crashed、不得起新进程
# ---------------------------------------------------------------------------
class TestKillFailureKeepsIdentity:
    def test_poll_does_not_restart_when_kill_unconfirmed(self, monkeypatch, capsys):
        proc = _RaceProc()
        m = _mk(proc)
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        monkeypatch.setattr(m, "kill_tree", lambda: False)  # 杀树未确认
        m.consecutive_health_fail = 5
        m.health_fail_start = time.monotonic() - 200.0
        next_start_before = m.next_start

        m.poll()

        assert m.proc is proc, '未确认终止必须保留进程身份，不能 self.proc=None'
        assert m.status != "crashed", '未确认终止不得宣布 crashed（会触发同端口重启）'
        assert m.next_start == next_start_before, '未确认终止不得安排新进程'
        assert m._kill_retry_at > time.monotonic(), '必须设置重试时刻'
        out = capsys.readouterr().out
        assert "未确认终止" in out and "不启动新进程" in out

    def test_poll_skips_kill_during_retry_window(self, monkeypatch):
        m = _mk(_AliveProc())
        monkeypatch.setattr(prod_runner, "_http_ok", lambda *a, **k: False)
        calls = {"n": 0}

        def _kill() -> bool:
            calls["n"] += 1
            return False

        monkeypatch.setattr(m, "kill_tree", _kill)
        m.consecutive_health_fail = 50
        m.health_fail_start = time.monotonic() - 9999.0
        m._kill_retry_at = time.monotonic() + 60.0  # 重试窗口内

        m.poll()

        assert calls["n"] == 0, '重试窗口内不得再次发杀树（避免 taskkill 风暴）'

    def test_shutdown_reports_unconfirmed_kill(self, monkeypatch, capsys):
        sup = prod_runner.Supervisor.__new__(prod_runner.Supervisor)
        sup._shutdown_done = False
        backend = _mk(_AliveProc())
        backend.name = "backend"
        arq = _mk(_AliveProc())
        arq.name = "arq"
        sup.backend = backend
        sup.arq = arq
        monkeypatch.setattr(backend, "kill_tree", lambda: False)
        monkeypatch.setattr(arq, "kill_tree", lambda: True)

        sup.shutdown()

        out = capsys.readouterr().out
        assert "已停止" not in out, '存在未确认终止的服务时不得宣称已停止'
        assert "关闭未完成" in out and "backend" in out
        assert "arq" not in out.split("关闭未完成")[1]

    def test_shutdown_reports_success_when_all_confirmed(self, monkeypatch, capsys):
        sup = prod_runner.Supervisor.__new__(prod_runner.Supervisor)
        sup._shutdown_done = False
        backend = _mk(_AliveProc())
        sup.backend = backend
        sup.arq = None
        monkeypatch.setattr(backend, "kill_tree", lambda: True)

        sup.shutdown()

        assert "已停止" in capsys.readouterr().out


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
