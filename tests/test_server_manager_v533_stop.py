"""server_manager v5.33 紧急停止回归测试（纯逻辑，无 Tk 实例）。

背景：紧急停止 stop_all 曾出现「错误触发重启」缺陷 —— 端口清理强杀 NSSM 受管
进程（erp-prod 监听 5002），被 AppExit=Default Restart 判定崩溃、5 秒后自动重启。
本文件锁定「受管进程绝不误杀」的核心契约。

运行: python -m pytest tests/test_server_manager_v533_stop.py -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_manager.app as sm  # (模块级代码无 Tk root, 导入安全;2026-09-28 包化)


def _make_app():
    """绕过 Tk 构造（__init__ 会触碰 self.root），仅取无状态逻辑。"""
    return object.__new__(sm.ServerManagerApp)


def _netstat_runs(stdout):
    """构造一个 subprocess.run 替身，返回给定 stdout。"""
    class _R:
        pass
    r = _R()
    r.stdout = stdout
    return lambda *a, **k: r


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="_find_port_pids 经 server_manager 调 netstat + subprocess.CREATE_NO_WINDOW，仅 Windows 可跑",
)
class TestFindPortPidsExclude:
    """_find_port_pids 必须按 exclude 跳过受管 PID，且端口精确匹配。"""

    def test_exclude_managed_pid_skipped(self, monkeypatch):
        netstat = (
            'TCP    0.0.0.0:5002    0.0.0.0:0    LISTENING    12345\r\n'
            'TCP    127.0.0.1:5002  127.0.0.1:0   LISTENING    999\r\n'
        )
        app = _make_app()
        monkeypatch.setattr(sm.subprocess, 'run', _netstat_runs(netstat))
        pids = app._find_port_pids(5002, exclude={12345})
        assert '999' in pids
        assert '12345' not in pids

    def test_no_exclude_returns_all(self, monkeypatch):
        netstat = (
            'TCP    0.0.0.0:5002    0.0.0.0:0    LISTENING    12345\r\n'
            'TCP    127.0.0.1:5002  127.0.0.1:0   LISTENING    999\r\n'
        )
        app = _make_app()
        monkeypatch.setattr(sm.subprocess, 'run', _netstat_runs(netstat))
        pids = app._find_port_pids(5002)
        assert '12345' in pids and '999' in pids

    def test_port_substring_not_matched(self, monkeypatch):
        # 5002 不得误匹配 50022（端口子串陷阱）
        netstat = (
            'TCP    0.0.0.0:50022   0.0.0.0:0    LISTENING    777\r\n'
            'TCP    0.0.0.0:5002    0.0.0.0:0    LISTENING    888\r\n'
        )
        app = _make_app()
        monkeypatch.setattr(sm.subprocess, 'run', _netstat_runs(netstat))
        pids = app._find_port_pids(5002)
        assert '888' in pids
        assert '777' not in pids


class TestStopManagedServices:
    """_stop_managed_services 正常停服务、返回受管 PID 集合(T4 包化后实现已迁 ServiceOps)。"""

    def _ops_with_state(self, monkeypatch, states):
        ops = object.__new__(sm.ServiceOps)
        ops._msg_queue = type('Q', (), {'put': lambda self, m: None})()
        ops.find_nssm = lambda: None
        ops.svc_state = lambda name: states[name]
        ops.run_capture = lambda args, timeout=20: (0, '')
        return ops

    def test_returns_managed_pids(self, monkeypatch):
        ops = self._ops_with_state(monkeypatch, {'erp-prod': '1 STOPPED', 'erp-arq': '1 STOPPED', 'erp-web': '1 STOPPED',
                                                      'erp-redis': '1 STOPPED', 'erp-redis-broker': '1 STOPPED'})
        ops.managed_service_pids = lambda: {12345, 67890}
        _stopped, managed, _failed = ops.stop_managed_services()
        assert managed == {12345, 67890}
        assert _failed == []

    def test_stops_running_service(self, monkeypatch):
        # erp-prod 运行中 → 应发 stop 并计数；erp-arq 未安装/停止 → 跳过；erp-web 未安装 → 跳过
        states = {'erp-prod': '4 RUNNING', 'erp-arq': '未安装', 'erp-web': '未安装',
                  'erp-redis': '未安装', 'erp-redis-broker': '未安装'}
        ops = self._ops_with_state(monkeypatch, states)
        ops.managed_service_pids = lambda: {12345}
        # 模拟：第一次查询 RUNNING，随后 STOPPED
        seq = {'erp-prod': iter(['4 RUNNING', '1 STOPPED']), 'erp-arq': iter(['未安装']),
               'erp-web': iter(['未安装']), 'erp-redis': iter(['未安装']),
               'erp-redis-broker': iter(['未安装'])}
        ops.svc_state = lambda name: next(seq[name])
        stop_calls = []
        ops.run_capture = lambda args, timeout=20: stop_calls.append(args[1]) or (0, '')
        stopped, managed, failed = ops.stop_managed_services()
        assert 'stop' in stop_calls  # 确实发起了 sc stop
        assert stopped == 1
        assert managed == {12345}
        assert failed == []

    def test_does_not_checkpoint(self):
        """_stop_managed_services 不得调用 checkpoint（否则紧急停止会半路抛取消）。"""
        ops = object.__new__(sm.ServiceOps)
        ops._msg_queue = type('Q', (), {'put': lambda self, m: None})()
        ops.find_nssm = lambda: None
        ops.managed_service_pids = lambda: set()
        ops.svc_state = lambda name: '未安装'
        ops.run_capture = lambda args, timeout=20: (0, '')
        # 无 _gate 属性时也能跑完，证明不依赖 checkpoint
        stopped, managed, failed = ops.stop_managed_services()
        assert stopped == 0
        assert managed == set()
        assert failed == []
