"""service_state 领域模块单测。

重点：为 v5.39 审查 #1 的子串误判漏洞建立**回归防护**——
该漏洞曾使「防互杀的防线自身成为新洞」，属于最高价值测试。
"""

from __future__ import annotations

import pytest

from server_manager_v8.domain.service_state import (
    STATE_ABSENT,
    STATE_UNKNOWN,
    ServiceStatus,
    classify,
    is_absent,
    is_unknown,
    parse_sc_query_output,
    parse_sc_queryex_pid,
)

# ── 真实的 sc query 输出样本（Windows 10/11 英文系统） ──

SC_RUNNING = """
SERVICE_NAME: erp-prod
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
        CHECKPOINT         : 0x0
        WAIT_HINT          : 0x0
"""

SC_STOPPED = """
SERVICE_NAME: erp-arq
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 1  STOPPED
        WIN32_EXIT_CODE    : 0  (0x0)
        SERVICE_EXIT_CODE  : 0  (0x0)
"""

SC_STOP_PENDING = """
SERVICE_NAME: erp-prod
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 3  STOP_PENDING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
"""

SC_NOT_EXIST = "[SC] OpenService FAILED 1060:\n\nThe specified service does not exist as an installed service.\n"

SC_ACCESS_DENIED = "[SC] OpenService FAILED 5:\n\nAccess is denied.\n"


class TestParseScQueryOutput:
    """parse_sc_query_output —— 纯函数解析。"""

    def test_running(self):
        assert parse_sc_query_output(0, SC_RUNNING) == '4 RUNNING'

    def test_stopped(self):
        assert parse_sc_query_output(0, SC_STOPPED) == '1 STOPPED'

    def test_stop_pending(self):
        assert parse_sc_query_output(0, SC_STOP_PENDING) == '3 STOP_PENDING'

    def test_not_installed_by_returncode(self):
        """rc == 1060 → 未安装。"""
        assert parse_sc_query_output(1060, SC_NOT_EXIST) == STATE_ABSENT

    def test_not_installed_by_text_without_state_line(self):
        """1060 错误文本且无 STATE 行 → 未安装。"""
        assert parse_sc_query_output(1, SC_NOT_EXIST) == STATE_ABSENT

    # ═══════════════════════════════════════════════════════════
    # ★ 回归防护：v5.39 审查 #1 —— 子串误判漏洞
    # ═══════════════════════════════════════════════════════════

    def test_pid_1060_must_not_be_treated_as_absent(self):
        """★ 核心回归：运行中服务的输出含 `PID : 1060` 时，不得误判「未安装」。

        这正是 v5.40 修复的漏洞。若此测试失败，说明防线又退化成 `'1060' in out`，
        将导致开发模式抢占生产端口、互杀事故复发。
        """
        out_running_with_pid_1060 = SC_RUNNING + "        PID                : 1060\n"
        got = parse_sc_query_output(0, out_running_with_pid_1060)
        assert got == '4 RUNNING', f'含 PID:1060 的运行中服务被误判为 {got!r}'
        assert not is_absent(got)

    def test_other_pid_values_unaffected(self):
        """其它 PID 值同样不受影响（防御性）。"""
        for pid in (106, 1060, 10600, 21060):
            out = SC_STOPPED + f"        PID                : {pid}\n"
            assert parse_sc_query_output(0, out) == '1 STOPPED'

    def test_access_denied_is_unknown_not_absent(self):
        """★ 拒绝访问必须判「未知」，绝不能判「未安装」。

        否则 _ensure_production_stopped 会静默跳过仍在运行的生产服务。
        """
        got = parse_sc_query_output(5, SC_ACCESS_DENIED)
        assert got == STATE_UNKNOWN
        assert not is_absent(got)
        assert is_unknown(got)

    def test_nonzero_code_without_service_name_is_unknown(self):
        assert parse_sc_query_output(1, 'something unexpected') == STATE_UNKNOWN

    def test_empty_output_is_unknown(self):
        assert parse_sc_query_output(0, '') == STATE_UNKNOWN


class TestClassify:
    """classify —— 状态文本 → 领域枚举。"""

    @pytest.mark.parametrize('raw,expected', [
        ('4 RUNNING', ServiceStatus.RUNNING),
        ('1 STOPPED', ServiceStatus.STOPPED),
        ('2 START_PENDING', ServiceStatus.PENDING),
        ('3 STOP_PENDING', ServiceStatus.PENDING),
        ('6 PAUSED', ServiceStatus.PENDING),
        (STATE_ABSENT, ServiceStatus.ABSENT),
        (STATE_UNKNOWN, ServiceStatus.UNKNOWN),
    ])
    def test_classification(self, raw, expected):
        assert classify(raw) is expected

    def test_unknown_for_unparsable(self):
        assert classify('garbage') is ServiceStatus.UNKNOWN


class TestConservativeRunning:
    """保守判定语义 —— 决定模式切换能否放行。"""

    def test_unknown_is_conservatively_running(self):
        """未知必须按运行中处理 —— 这是互杀事故的核心防线。"""
        assert classify(STATE_UNKNOWN).is_conservatively_running

    def test_running_and_pending_are_conservatively_running(self):
        assert classify('4 RUNNING').is_conservatively_running
        assert classify('3 STOP_PENDING').is_conservatively_running

    def test_stopped_and_absent_are_not_conservatively_running(self):
        """停止与未安装可以放行。"""
        assert not classify('1 STOPPED').is_conservatively_running
        assert not classify(STATE_ABSENT).is_conservatively_running

    def test_absent_and_unknown_are_mutually_exclusive(self):
        """「未安装」与「未知」语义必须互斥 —— 混淆即事故。"""
        absent, unknown = classify(STATE_ABSENT), classify(STATE_UNKNOWN)
        assert absent.is_absent and not absent.is_unknown
        assert unknown.is_unknown and not unknown.is_absent


class TestParseScQueryexPid:
    """parse_sc_queryex_pid —— 从 queryex 输出提取 PID。"""

    def test_extract_pid(self):
        out = SC_RUNNING + "        PID                : 4380\n"
        assert parse_sc_queryex_pid(out) == 4380

    def test_no_pid_when_stopped(self):
        assert parse_sc_queryex_pid(SC_STOPPED) is None

    def test_pid_1060_extracted_correctly(self):
        """PID 1060 应被正确提取为整数（与「未安装」判定互不干扰）。"""
        out = SC_RUNNING + "        PID                : 1060\n"
        assert parse_sc_queryex_pid(out) == 1060

    def test_empty_output(self):
        assert parse_sc_queryex_pid('') is None
