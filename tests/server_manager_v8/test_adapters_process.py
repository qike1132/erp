"""进程/端口适配器测试：netstat 解析（纯函数）+ 真实子进程启停（集成）。"""
from __future__ import annotations

import socket
import sys
import time

import pytest

from server_manager_v8.adapters.process_win import ProcessWinAdapter, parse_netstat_pids
from server_manager_v8.domain import SpawnSpec

IS_WIN = sys.platform == 'win32'
PY = sys.executable


class TestParseNetstat:
    def test_listening_and_time_wait(self) -> None:
        lines = (
            '  TCP    0.0.0.0:5002           0.0.0.0:0              LISTENING       12345\n'
            '  TCP    127.0.0.1:5002         127.0.0.1:54321        TIME_WAIT       0\n'
            '  TCP    127.0.0.1:54321        127.0.0.1:5002         ESTABLISHED     6789\n'
            '  TCP    0.0.0.0:3000           0.0.0.0:0              LISTENING       9999\n'
        )
        assert parse_netstat_pids(lines, 5002) == [12345]
        assert parse_netstat_pids(lines, 3000) == [9999]
        assert parse_netstat_pids(lines, 99999) == []

    def test_ignores_pid_zero(self) -> None:
        lines = '  TCP    0.0.0.0:5002  0.0.0.0:0  LISTENING  0\n'
        assert parse_netstat_pids(lines, 5002) == []

    def test_malformed_lines(self) -> None:
        assert parse_netstat_pids('garbage\n', 5002) == []


@pytest.mark.skipif(not IS_WIN, reason='仅 Windows')
class TestProcessAdapterIntegration:
    def test_spawn_and_kill_tree(self) -> None:
        """真实子进程：spawn → 存活 → kill_tree → 消失。"""
        adapter = ProcessWinAdapter()
        handle = adapter.spawn(SpawnSpec(
            argv=(PY, '-u', '-c', 'import time; time.sleep(300)'),
        ))
        assert adapter.handle(handle.pid) is not None
        kill = adapter.kill_tree(handle.pid)
        assert kill.ok
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and adapter.handle(handle.pid) is not None:
            time.sleep(0.5)
        assert adapter.handle(handle.pid) is None, '进程树应已被清理'

    def test_spawn_failure_raises_reason(self) -> None:
        """启动失败抛 SpawnError（显式异常，绝不静默）。"""
        from server_manager_v8.domain import SpawnError

        adapter = ProcessWinAdapter()
        with pytest.raises(SpawnError):
            adapter.spawn(SpawnSpec(argv=(r'Z:\no_such_exe_xyz.exe', '--x')))

    def test_find_and_kill_port(self) -> None:
        """子进程监听随机端口 → find_port_pids 命中 → kill_port 清理。"""
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()

        adapter = ProcessWinAdapter()
        script = (
            f'import socket,time; s=socket.socket(); s.bind(("127.0.0.1", {port})); '
            's.listen(); time.sleep(300)'
        )
        adapter.spawn(SpawnSpec(argv=(PY, '-u', '-c', script)))
        deadline = time.monotonic() + 10
        pids = []
        while time.monotonic() < deadline:
            pids = adapter.find_port_pids(port)
            if pids:
                break
            time.sleep(0.5)
        assert pids, '未探测到监听进程'
        kill = adapter.kill_port(port, rounds=2)
        assert kill.ok and not kill.partial, f'残留进程: {kill.survivors}'
        assert adapter.find_port_pids(port) == []

    def test_kill_tree_invalid_pid(self) -> None:
        adapter = ProcessWinAdapter()
        result = adapter.kill_tree(0)
        assert not result.ok

    def test_kill_nonexistent_pid_reports_survivor_clean(self) -> None:
        """不存在的 PID：taskkill 报错但进程不存在 → 视为已清理（非失败）。"""
        adapter = ProcessWinAdapter()
        result = adapter.kill_tree(999_999_999)
        assert result.ok and not result.partial
