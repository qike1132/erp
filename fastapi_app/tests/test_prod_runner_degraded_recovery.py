"""AUD-08（2026-10-24 审计）回归锁：prod_runner 的「总宕机显示绿」修复。

D7 的三条件重启闸门（连续失败+窗口+进程已死）消掉了误杀，也挡住了真故障：
uvicorn --workers>1 时 master 无限 respawn 崩溃 worker 而自身长存——proc_alive
恒 True，三条件永差一个；且不健康分支不降级 status，prod_runner.json 持续
ready:true（2026-10-22 site-packages 批量损坏事故的同型重演即触发）。

修复后（本文件锁定）：
1. 新纯函数 _should_force_restart_degraded：连续失败 ≥3 且窗口 ≥600s 即重启
   （不管进程死活；窗口远高于探针抖动，不回退 D7 防误杀）；
2. poll：进程存活、不健康窗口 ≥600s → kill_tree + crashed（自愈）；
3. poll：进程存活、窗口 <600s → status 降级 "degraded"（ready:false 如实反映），
   不 kill；crashed/failed/starting 等状态不被覆盖；
4. D7 原判据 _should_restart 行为不变（proc_alive=True 永不重启）。
"""
import time
from unittest.mock import MagicMock

from fastapi_app.core import prod_runner as pr


def test_force_restart_degraded_boundaries():
    # 窗口界：600s 整成立，599.999 不成立
    assert pr._should_force_restart_degraded(3, 600.0) is True
    assert pr._should_force_restart_degraded(3, 599.999) is False
    # 连续次数界：与 _should_restart 同门槛（3）
    assert pr._should_force_restart_degraded(2, 10 ** 6) is False
    assert pr._should_force_restart_degraded(10 ** 6, 10 ** 6) is True
    # 不看 proc_alive（本函数不接收该参数——由调用方先行判定进程存活）


def test_d7_should_restart_unchanged():
    """D7 原判据不得被本修复改动（防误杀语义保持）。"""
    assert pr._should_restart(10 ** 6, 10 ** 9, proc_alive=True) is False
    assert pr._should_restart(3, 90.0, proc_alive=False) is True
    assert pr._should_restart(3, 89.999, proc_alive=False) is False


def _managed(status='ready', fail_window_s=None):
    """跳过 __init__ 构造最小 _Managed（poll 只触达这些属性）。"""
    m = pr._Managed.__new__(pr._Managed)
    m.name = 'backend'
    m.status = status
    m.proc = MagicMock()
    m.proc.poll.return_value = None  # 进程存活
    m.health_url = 'http://127.0.0.1:5002/api/health'
    m.consecutive_health_fail = 0
    m.health_fail_start = None if fail_window_s is None else time.monotonic() - fail_window_s
    # H2（2026-10-26）：杀树失败后的重试时刻（poll 会读它）
    m._kill_retry_at = 0.0
    m.delay = 2.0
    m.backoff_step = 0
    m.workers = 4
    m.last_health = ''
    return m


def test_poll_force_restarts_after_degraded_window(monkeypatch):
    """进程存活 + 不健康窗口 ≥600s：kill_tree 重启并标记 crashed。"""
    m = _managed(status='ready', fail_window_s=601.0)
    m.consecutive_health_fail = 3
    killed = []

    def _kill() -> bool:
        killed.append(1)
        return True  # H2 契约：kill_tree 返回「是否已确认终止」

    monkeypatch.setattr(m, 'kill_tree', _kill)
    monkeypatch.setattr(m, '_probe_health', lambda: (False, 0.1))

    m.poll()

    assert killed == [1], '窗口超阈必须强制重启（AUD-08）'
    assert m.status == 'crashed'
    assert m.health_fail_start is None
    assert m.consecutive_health_fail == 0


def test_poll_degrades_status_without_kill_under_window(monkeypatch):
    """进程存活 + 窗口 <600s：status 降级 degraded、不杀进程。"""
    m = _managed(status='ready', fail_window_s=100.0)
    killed = []
    monkeypatch.setattr(m, 'kill_tree', lambda: killed.append(1))
    monkeypatch.setattr(m, '_probe_health', lambda: (False, 0.1))

    m.poll()

    assert killed == [], '窗口未到不得杀进程树（防误杀语义保持）'
    assert m.status == 'degraded', '不健康期间状态必须降级（AUD-08）'


def test_poll_does_not_override_terminal_statuses(monkeypatch):
    """crashed/failed/starting 语义不动（maybe_restart 依赖）。"""
    for status in ('crashed', 'failed', 'starting'):
        m = _managed(status=status, fail_window_s=100.0)
        monkeypatch.setattr(m, 'kill_tree', lambda: True)
        monkeypatch.setattr(m, '_probe_health', lambda: (False, 0.1))
        m.poll()
        assert m.status == status, f'{status} 不得被降级逻辑覆盖'


def test_poll_recovers_to_ready(monkeypatch):
    """恢复健康：status 回 ready、失败计数清零（降级可自愈）。"""
    m = _managed(status='degraded', fail_window_s=100.0)
    m.consecutive_health_fail = 5
    monkeypatch.setattr(m, '_probe_health', lambda: (True, 0.05))

    m.poll()

    assert m.status == 'ready'
    assert m.consecutive_health_fail == 0
    assert m.health_fail_start is None
