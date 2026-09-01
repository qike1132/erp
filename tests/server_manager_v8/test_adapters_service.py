"""NSSM 服务适配器测试：sc/wmic 输出解析（纯函数）+ 真实查询（不破坏环境）。"""
from __future__ import annotations

import sys

import pytest

from server_manager_v8.adapters.service_nssm import (
    NssmServiceAdapter,
    parse_sc_state,
    parse_wmic_deps,
)
from server_manager_v8.domain import ServiceState

IS_WIN = sys.platform == 'win32'


class TestParseScState:
    def test_running(self) -> None:
        out = (
            'SERVICE_NAME: erp-prod\n'
            '        TYPE               : 10  WIN32_OWN_PROCESS\n'
            '        STATE              : 4  RUNNING\n'
            '        WIN32_EXIT_CODE    : 0  (0x0)\n'
        )
        assert parse_sc_state(out, 0) is ServiceState.RUNNING

    def test_stopped(self) -> None:
        out = 'SERVICE_NAME: x\n        STATE              : 1  STOPPED\n'
        assert parse_sc_state(out, 0) is ServiceState.STOPPED

    def test_pending_is_unknown_not_stopped(self) -> None:
        """STOP_PENDING 必须 UNKNOWN（不得降级 STOPPED，v6 踩坑语义）。"""
        out = 'SERVICE_NAME: x\n        STATE              : 3  STOP_PENDING\n'
        assert parse_sc_state(out, 0) is ServiceState.UNKNOWN

    def test_absent_on_1060(self) -> None:
        """服务不存在（返回码 1060）→ ABSENT。"""
        assert parse_sc_state('', 1060) is ServiceState.ABSENT
        assert parse_sc_state('ERROR 1060', 1060) is ServiceState.ABSENT

    def test_no_service_name_is_absent(self) -> None:
        assert parse_sc_state('  STATE: 4 RUNNING\n', 0) is ServiceState.ABSENT

    def test_unknown_raw_state(self) -> None:
        out = 'SERVICE_NAME: x\n        STATE              : 9  SOMETHING_WEIRD\n'
        assert parse_sc_state(out, 0) is ServiceState.UNKNOWN


class TestParseWmicDeps:
    def test_auto_running_pg_redis_only(self) -> None:
        out = (
            'Name                                      StartMode  State\n'
            'postgresql-x64-16                          Auto       Running\n'
            'Redis                                     Auto       Running\n'
            'MySQL                                     Auto       Running\n'
            'postgresql-replica-1                      Auto       Running\n'
            'Memurai                                   Manual     Stopped\n'
        )
        deps = parse_wmic_deps(out)
        assert deps == ['postgresql-x64-16', 'Redis']  # 排除 MySQL/replica/Manual

    def test_env_override_precedence(self) -> None:
        import os

        os.environ['SERVICE_DEPENDS_ON'] = 'pg-a; pg-b,redis-c'
        try:
            adapter = NssmServiceAdapter()
            assert adapter.detect_dependencies() == ['pg-a', 'pg-b', 'redis-c']
        finally:
            del os.environ['SERVICE_DEPENDS_ON']


class TestRealQueries:
    @pytest.mark.skipif(not IS_WIN, reason='仅 Windows')
    def test_state_nonexistent_service_never_running(self) -> None:
        """真实 sc query：随机不存在的服务名 → ABSENT 或 UNKNOWN（沙箱可能拦截 sc）。

        关键不变量：不存在/不可查询的服务**绝不**被判定为 RUNNING/STOPPED
        （v6 踩坑：探测失败误判已停止会漏停服务）。
        """
        import uuid

        name = f'nonexistent_{uuid.uuid4().hex[:8]}'
        adapter = NssmServiceAdapter()
        state = adapter.state(name)
        assert state not in (ServiceState.RUNNING, ServiceState.STOPPED)

    @pytest.mark.skipif(not IS_WIN, reason='仅 Windows')
    def test_control_fails_when_no_nssm_or_no_service(self) -> None:
        """缺 NSSM 或服务不存在 → 显式失败（绝不静默）。"""
        import uuid

        name = f'nonexistent_{uuid.uuid4().hex[:8]}'
        adapter = NssmServiceAdapter()
        result = adapter.control(name, 'start')
        assert not result.ok and result.reason

    def test_invalid_control_command_rejected(self) -> None:
        adapter = NssmServiceAdapter()
        assert not adapter.control('x', 'explode').ok

    def test_wait_state_absent_returns_false_quickly(self) -> None:
        """等待一个永远到不了的状态 → 超时 False（小超时）。"""
        import uuid

        adapter = NssmServiceAdapter()
        assert adapter.wait_state(f'no_{uuid.uuid4().hex[:6]}', ServiceState.RUNNING,
                                  timeout_s=2.0) is False
