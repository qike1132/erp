"""`adapters.service_nssm` 的测试。

重点覆盖三处最容易出错、且都有事故背景的地方：

  1. **`query_state` 的失败语义**：查询失败必须判「未知」而非「未安装」
     —— 判错会导致 `_ensure_production_stopped` 静默跳过仍在跑的生产服务，
     开发模式随即抢占 5002/3000 与生产互杀（v5.36 事故）。
  2. **`run_verb` 的失败文案**：三种文案要能被运维认出来（旧实现逐字保留）。
  3. **`VerbResult` 的字段契约**：失败必须带 reason（防空洞的失败）。
"""

from __future__ import annotations

import pytest

from server_manager_v8.adapters import service_nssm as S
from server_manager_v8.domain.models import SVC_API, SVC_ARQ
from server_manager_v8.domain.service_state import ServiceStatus
from server_manager_v8.domain.state_machine import GuardKind

NSSM = r'C:\nssm\nssm.exe'


# ═══════════════════════════════════════════════════════════════════
# find_nssm
# ═══════════════════════════════════════════════════════════════════


class TestFindNssm:
    """迁移自 `_find_nssm()`（L1359-1367）。优先级：配置 → PATH → 候选路径。"""

    def test_configured_exe_takes_priority(self, tmp_path):
        exe = tmp_path / 'nssm.exe'
        exe.write_text('')
        found = S.find_nssm(str(exe), which=lambda _: '/from/path/nssm')
        assert found == str(exe)

    def test_configured_non_exe_suffix_is_rejected(self, tmp_path):
        """★ 配置里写非 .exe 时**不能盲目相信**，要退回自动探测。"""
        weird = tmp_path / 'nssm.txt'
        weird.write_text('')
        found = S.find_nssm(str(weird), which=lambda _: None, candidates=())
        assert found is None

    def test_configured_missing_file_falls_back(self, tmp_path):
        found = S.find_nssm(
            str(tmp_path / 'nope.exe'), which=lambda _: '/path/nssm', candidates=()
        )
        assert found == '/path/nssm'

    def test_path_lookup_used_when_no_config(self):
        found = S.find_nssm(None, which=lambda cmd: '/usr/local/bin/nssm', candidates=())
        assert found == '/usr/local/bin/nssm'

    def test_candidates_used_as_last_resort(self, tmp_path):
        exe = tmp_path / 'nssm.exe'
        exe.write_text('')
        found = S.find_nssm(None, which=lambda _: None, candidates=(tmp_path / 'a.exe', exe))
        assert found == str(exe)

    def test_returns_none_when_nothing_found(self, tmp_path):
        assert S.find_nssm(None, which=lambda _: None, candidates=(tmp_path / 'x.exe',)) is None

    def test_empty_config_string_is_falsy(self):
        """配置值为 '' / None 时不该当路径处理。"""
        assert S.find_nssm('', which=lambda _: None, candidates=()) is None

    def test_has_nssm_true_false(self, tmp_path):
        exe = tmp_path / 'nssm.exe'
        exe.write_text('')
        assert S.has_nssm(str(exe)) is True
        assert S.has_nssm(None, which=lambda _: None, candidates=()) is False

    def test_default_candidates_are_the_four_real_paths(self):
        """★ 保真核对：候选清单必须与 v5.40 L78-79 逐字一致。"""
        got = [str(p) for p in S.nssm_candidates()]
        assert got == [
            r'C:\nssm\nssm.exe',
            r'C:\Program Files\nssm\nssm.exe',
            r'C:\Program Files (x86)\nssm\nssm.exe',
            r'C:\tools\nssm\nssm.exe',
        ]


# ═══════════════════════════════════════════════════════════════════
# query_state
# ═══════════════════════════════════════════════════════════════════


RUNNING_OUT = """
SERVICE_NAME: erp-prod
        TYPE               : 10  WIN32_OWN_PROCESS
        STATE              : 4  RUNNING
                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)
        WIN32_EXIT_CODE    : 0  (0x0)
"""


class TestQueryState:
    def test_parses_running(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc', 'query', SVC_API], 0, RUNNING_OUT)
        q = S.query_state(SVC_API, runner=runner.run)
        assert q.status is ServiceStatus.RUNNING
        assert q.code == 0
        assert 'RUNNING' in q.state_text

    def test_1060_rc_means_absent(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc', 'query', SVC_API], 1060, '', 'ERROR 1060')
        q = S.query_state(SVC_API, runner=runner.run)
        assert q.status is ServiceStatus.ABSENT
        assert q.is_absent is True

    def test_access_denied_is_unknown_not_absent(self, fake_runner_cls):
        """★ v5.36 核心断言。

        rc=5 是 ERROR_ACCESS_DENIED（拒绝访问 / 被安全软件拦截），
        必须判「未知」而不是「未安装」。

        若误判「未安装」→ `plan_production_stop` 给出 SKIP_ABSENT →
        生产服务没被停 → 开发模式抢占端口 → 互杀事故复发。
        """
        runner = fake_runner_cls().on(['sc', 'query', SVC_API], 5, '', 'Access is denied.')
        q = S.query_state(SVC_API, runner=runner.run)
        assert q.status is ServiceStatus.UNKNOWN
        assert q.is_unknown is True
        assert q.is_absent is False

    def test_exception_is_unknown(self, fake_runner_cls):
        """★ 查询异常（超时/命令缺失）→ 未知，绝不能判未安装。"""
        runner = fake_runner_cls()
        runner.raise_on(['sc', 'query', SVC_API], OSError('sc not found'))
        q = S.query_state(SVC_API, runner=runner.run)
        assert q.status is ServiceStatus.UNKNOWN
        assert q.is_absent is False

    def test_raw_is_preserved_for_diagnostics(self, fake_runner_cls):
        """留痕需要：判「未知」时运维必须能看到 sc 到底回了什么。"""
        runner = fake_runner_cls().on(['sc', 'query', SVC_API], 5, '', 'Access is denied.')
        q = S.query_state(SVC_API, runner=runner.run)
        assert 'Access is denied' in q.raw
        assert q.code == 5

    def test_stdout_and_stderr_both_land_in_raw(self, fake_runner_cls):
        """旧实现是 stdout+stderr 拼接，保真。"""
        runner = fake_runner_cls().on(['sc', 'query', 'x'], 0, 'OUT', 'ERR')
        q = S.query_state('x', runner=runner.run)
        assert q.raw == 'OUTERR'

    def test_stop_pending_maps_to_pending(self, fake_runner_cls):
        out = 'SERVICE_NAME: x\n        STATE              : 3  STOP_PENDING\n'
        runner = fake_runner_cls().on(['sc', 'query', 'x'], 0, out)
        assert S.query_state('x', runner=runner.run).status is ServiceStatus.PENDING

    def test_start_pending_maps_to_pending(self, fake_runner_cls):
        out = 'SERVICE_NAME: x\n        STATE              : 2  START_PENDING\n'
        runner = fake_runner_cls().on(['sc', 'query', 'x'], 0, out)
        assert S.query_state('x', runner=runner.run).status is ServiceStatus.PENDING

    def test_stopped_maps_to_stopped(self, fake_runner_cls):
        out = 'SERVICE_NAME: x\n        STATE              : 1  STOPPED\n'
        runner = fake_runner_cls().on(['sc', 'query', 'x'], 0, out)
        assert S.query_state('x', runner=runner.run).status is ServiceStatus.STOPPED

    def test_pid_1060_in_output_not_treated_as_absent(self, fake_runner_cls):
        """★ v5.39 审查 #1 的回归防护（适配器视角）。

        运行中的服务输出里有 `PID : 1060`（开机早期自启服务的 PID 完全可能落在 1060），
        旧版裸写 `'1060' in out` 会误判「未安装」。
        判定由领域层负责，这里验证整条链路不复现该 bug。
        """
        out = (
            'SERVICE_NAME: erp-prod\n'
            '        TYPE               : 10  WIN32_OWN_PROCESS\n'
            '        STATE              : 4  RUNNING\n'
            '        WIN32_EXIT_CODE    : 0\n'
            '        PID                : 1060\n'
        )
        runner = fake_runner_cls().on(['sc', 'query', SVC_API], 0, out)
        q = S.query_state(SVC_API, runner=runner.run)
        assert q.status is ServiceStatus.RUNNING
        assert q.is_absent is False

    def test_query_uses_oem_decoding(self, fake_runner_cls):
        """中文 Windows 上 sc 输出是 GBK，必须 oem 解码。"""
        runner = fake_runner_cls().on(['sc', 'query', SVC_API], 0, RUNNING_OUT)
        S.query_state(SVC_API, runner=runner.run)
        kw = runner.kwargs_for(['sc', 'query', SVC_API])
        assert kw['encoding'] == 'oem'
        assert kw['errors'] == 'replace'


# ═══════════════════════════════════════════════════════════════════
# query_pid
# ═══════════════════════════════════════════════════════════════════


class TestQueryPid:
    """迁移自 `_svc_pid()`（L1396-1408）。"""

    def test_extracts_pid(self, fake_runner_cls):
        out = 'SERVICE_NAME: erp-prod\n        PID                : 8288\n'
        runner = fake_runner_cls().on(['sc', 'queryex', SVC_API], 0, out)
        assert S.query_pid(SVC_API, runner=runner.run) == 8288

    def test_pid_zero_is_not_valid(self, fake_runner_cls):
        """★ 收紧点：PID 0 不是有效进程号。

        与 `domain.port_contract`（v5.40 审查 #23，TIME_WAIT 行 PID 恒为 0）
        及 `domain.state_machine.build_protected_pids` 的 `> 0` 判定一致。
        旧实现只判 isdigit()，会返回 0。
        """
        out = 'SERVICE_NAME: erp-prod\n        PID                : 0\n'
        runner = fake_runner_cls().on(['sc', 'queryex', SVC_API], 0, out)
        assert S.query_pid(SVC_API, runner=runner.run) is None

    def test_no_pid_line_returns_none(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc', 'queryex', SVC_API], 0, 'STATE: 1 STOPPED')
        assert S.query_pid(SVC_API, runner=runner.run) is None

    def test_exception_returns_none(self, fake_runner_cls):
        runner = fake_runner_cls()
        runner.raise_on(['sc', 'queryex', SVC_API], OSError('boom'))
        assert S.query_pid(SVC_API, runner=runner.run) is None

    def test_non_numeric_pid_returns_none(self, fake_runner_cls):
        out = 'SERVICE_NAME: x\n        PID                : N/A\n'
        runner = fake_runner_cls().on(['sc', 'queryex', 'x'], 0, out)
        assert S.query_pid('x', runner=runner.run) is None

    def test_lowercase_pid_line_not_matched(self, fake_runner_cls):
        """旧实现用 `startswith('PID')` —— 大小写敏感（保真）。"""
        out = 'SERVICE_NAME: x\n        pid                : 100\n'
        runner = fake_runner_cls().on(['sc', 'queryex', 'x'], 0, out)
        assert S.query_pid('x', runner=runner.run) is None


# ═══════════════════════════════════════════════════════════════════
# VerbResult 契约
# ═══════════════════════════════════════════════════════════════════


class TestVerbResultContract:
    def test_failure_without_reason_rejected(self):
        with pytest.raises(ValueError, match='reason'):
            S.VerbResult(service='x', verb='stop', ok=False)

    def test_success_has_no_reason(self):
        r = S.VerbResult.success('x', 'stop')
        assert r.ok is True and r.reason is None

    def test_failure_requires_reason(self):
        r = S.VerbResult.failure('x', 'stop', '拒绝访问')
        assert r.ok is False and r.reason == '拒绝访问'

    def test_frozen(self):
        r = S.VerbResult.success('x', 'stop')
        with pytest.raises(Exception):
            r.ok = False

    def test_carries_service_and_verb(self):
        r = S.VerbResult.failure('erp-prod', 'restart', 'boom')
        assert r.service == 'erp-prod' and r.verb == 'restart'


# ═══════════════════════════════════════════════════════════════════
# run_verb
# ═══════════════════════════════════════════════════════════════════


class TestRunVerb:
    """迁移自 `_service_one()`（L1477-1495）的命令执行部分。"""

    def test_uses_nssm_when_available(self, fake_runner_cls):
        runner = fake_runner_cls().on(['nssm', 'start', SVC_API], 0)
        r = S.run_verb(SVC_API, 'start', NSSM, runner=runner.run)
        assert r.ok is True
        assert runner.called_with(['nssm', 'start', SVC_API])

    def test_uses_sc_when_no_nssm(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc', 'start', SVC_API], 0)
        r = S.run_verb(SVC_API, 'start', None, runner=runner.run)
        assert r.ok is True
        assert runner.called_with(['sc', 'start', SVC_API])

    def test_nssm_path_passed_as_executable(self, fake_runner_cls):
        """argv[0] 是 'nssm' 但真实路径由 executable 提供（旧实现如此）。"""
        runner = fake_runner_cls().on(['nssm', 'stop', SVC_API], 0)
        S.run_verb(SVC_API, 'stop', NSSM, runner=runner.run)
        kw = runner.kwargs_for(['nssm', 'stop', SVC_API])
        assert kw['executable'] == NSSM

    def test_nonzero_exit_gives_code_and_output(self, fake_runner_cls):
        """★ 文案逐字保真：`{verb} 命令失败(退出码 {code}): {out or "无输出"}`"""
        runner = fake_runner_cls().on(['nssm', 'stop', SVC_API], 5, '', 'Access denied')
        r = S.run_verb(SVC_API, 'stop', NSSM, runner=runner.run)
        assert r.ok is False
        assert r.reason == 'stop 命令失败(退出码 5): Access denied'

    def test_nonzero_exit_with_empty_output_says_no_output(self, fake_runner_cls):
        runner = fake_runner_cls().on(['nssm', 'stop', SVC_API], 1, '', '')
        r = S.run_verb(SVC_API, 'stop', NSSM, runner=runner.run)
        assert r.reason == 'stop 命令失败(退出码 1): 无输出'

    def test_generic_exception_wording(self, fake_runner_cls):
        """★ 文案逐字保真：`{verb} 命令异常: {type}: {e}`"""
        runner = fake_runner_cls()
        runner.raise_on(['nssm', 'start', SVC_API], OSError('spawn failed'))
        r = S.run_verb(SVC_API, 'start', NSSM, runner=runner.run)
        assert r.ok is False
        assert r.reason == 'start 命令异常: OSError: spawn failed'

    def test_timeout_wording(self, fake_runner_cls):
        """★ 文案逐字保真：`{verb} 命令超时(30s)`"""
        import subprocess as sp

        runner = fake_runner_cls()
        runner.raise_on(['nssm', 'stop', SVC_API], sp.TimeoutExpired('nssm', 30))
        r = S.run_verb(SVC_API, 'stop', NSSM, timeout=30, runner=runner.run)
        assert r.ok is False
        assert r.reason == 'stop 命令超时(30s)'

    def test_timeout_uses_actual_timeout_value(self, fake_runner_cls):
        import subprocess as sp

        runner = fake_runner_cls()
        runner.raise_on(['sc', 'stop', 'x'], sp.TimeoutExpired('sc', 7))
        r = S.run_verb('x', 'stop', None, timeout=7, runner=runner.run)
        assert r.reason == 'stop 命令超时(7s)'

    @pytest.mark.parametrize('verb', ['start', 'stop', 'restart'])
    def test_all_verbs_supported(self, fake_runner_cls, verb):
        runner = fake_runner_cls().on(['nssm', verb, SVC_API], 0)
        assert S.run_verb(SVC_API, verb, NSSM, runner=runner.run).ok is True

    def test_detail_carries_output_on_success(self, fake_runner_cls):
        runner = fake_runner_cls().on(['nssm', 'stop', SVC_API], 0, 'stopped ok', '')
        r = S.run_verb(SVC_API, 'stop', NSSM, runner=runner.run)
        assert r.detail == 'stopped ok'


# ═══════════════════════════════════════════════════════════════════
# request_stop
# ═══════════════════════════════════════════════════════════════════


class TestRequestStop:
    """迁移自 `_wait_service_stopped` 的前半段（L1416-1419）。"""

    def test_prefers_nssm_stop(self, fake_runner_cls):
        """★ 有 nssm 时必须走 `nssm stop` 而不是 `sc stop` —— 语义不同。"""
        runner = fake_runner_cls().on(['nssm', 'stop', SVC_API], 0)
        assert S.request_stop(SVC_API, NSSM, runner=runner.run) is True
        assert runner.called_with(['nssm', 'stop', SVC_API])
        assert not runner.called_with(['sc', 'stop', SVC_API])

    def test_falls_back_to_sc_without_nssm(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc', 'stop', SVC_API], 0)
        assert S.request_stop(SVC_API, None, runner=runner.run) is True
        assert runner.called_with(['sc', 'stop', SVC_API])

    def test_failure_returns_false_but_never_raises(self, fake_runner_cls):
        """★ 失败不得抛 —— 旧实现要求「即便 nssm stop 失败也要继续走轮询」。"""
        runner = fake_runner_cls()
        runner.raise_on(['nssm', 'stop', SVC_API], OSError('boom'))
        assert S.request_stop(SVC_API, NSSM, runner=runner.run) is False

    def test_uses_15s_timeout(self, fake_runner_cls):
        runner = fake_runner_cls().on(['nssm', 'stop', SVC_API], 0)
        S.request_stop(SVC_API, NSSM, runner=runner.run)
        kw = runner.kwargs_for(['nssm', 'stop', SVC_API])
        assert kw['timeout'] == 15


# ═══════════════════════════════════════════════════════════════════
# set_restart_guard
# ═══════════════════════════════════════════════════════════════════


class TestSetRestartGuard:
    """迁移自 `_service_restart_guard()`（L1459-1475）。

    ★ D6：guard 只对 NSSM 托管服务（erp-prod / erp-arq）有效。
    """

    def test_no_nssm_means_no_calls(self, fake_runner_cls):
        runner = fake_runner_cls()
        assert S.set_restart_guard(GuardKind.DISABLE, None, runner=runner.run) == ()
        assert runner.calls == []

    def test_disable_sets_appexit_exit(self, fake_runner_cls):
        runner = fake_runner_cls()
        for name in (SVC_API, SVC_ARQ):
            runner.on(['nssm', 'set', name, 'AppExit', 'Default', 'Exit'], 0)
        results = S.set_restart_guard(GuardKind.DISABLE, NSSM, runner=runner.run)
        assert all(r.ok for r in results)
        assert runner.called_with(['nssm', 'set', SVC_API, 'AppExit', 'Default', 'Exit'])

    def test_enable_sets_appexit_restart(self, fake_runner_cls):
        runner = fake_runner_cls()
        for name in (SVC_API, SVC_ARQ):
            runner.on(['nssm', 'set', name, 'AppExit', 'Default', 'Restart'], 0)
        results = S.set_restart_guard(GuardKind.ENABLE, NSSM, runner=runner.run)
        assert all(r.ok for r in results)
        assert runner.called_with(['nssm', 'set', SVC_ARQ, 'AppExit', 'Default', 'Restart'])

    def test_covers_both_nssm_services_only(self, fake_runner_cls):
        """★ D6：只对 erp-prod / erp-arq，不含 erp-redis（原生服务无 AppExit）。"""
        runner = fake_runner_cls()
        for name in (SVC_API, SVC_ARQ):
            runner.on(['nssm', 'set', name, 'AppExit', 'Default', 'Exit'], 0)
        S.set_restart_guard(GuardKind.DISABLE, NSSM, runner=runner.run)
        targets = [a[2] for a in runner.argvs if a[:2] == ['nssm', 'set']]
        assert set(targets) == {SVC_API, SVC_ARQ}
        assert 'erp-redis' not in targets

    def test_reports_failure_with_reason(self, fake_runner_cls):
        """旧实现 suppress 掉一切、无留痕；新实现报告失败原因。"""
        runner = fake_runner_cls()
        runner.on(['nssm', 'set', SVC_API, 'AppExit', 'Default', 'Exit'], 1)
        runner.on(['nssm', 'set', SVC_ARQ, 'AppExit', 'Default', 'Exit'], 0)
        results = S.set_restart_guard(GuardKind.DISABLE, NSSM, runner=runner.run)
        by_name = {r.service: r for r in results}
        assert by_name[SVC_API].ok is False
        assert 'AppExit=Exit' in by_name[SVC_API].reason
        assert by_name[SVC_ARQ].ok is True

    def test_guard_kind_values_match_nssm_syntax(self, fake_runner_cls):
        """枚举值就是 nssm 认识的字面量（Exit / Restart）。"""
        runner = fake_runner_cls()
        for name in (SVC_API, SVC_ARQ):
            runner.on(['nssm', 'set', name, 'AppExit', 'Default', 'Restart'], 0)
        S.set_restart_guard(GuardKind.ENABLE, NSSM, runner=runner.run)
        assert all(c['argv'][4] == 'Default' and c['argv'][5] == 'Restart'
                   for c in runner.calls)


# ═══════════════════════════════════════════════════════════════════
# control_many / detect_installed
# ═══════════════════════════════════════════════════════════════════


class TestControlMany:
    """迁移自 `_service_cmd_sync()`（L1506-1534）的循环体。"""

    def _snap(self, name, text):
        return S.ServiceQuery(name, 0, text, text)

    def test_skips_absent_services(self, fake_runner_cls):
        runner = fake_runner_cls()
        snapshots = {
            SVC_API: S.ServiceQuery(SVC_API, 1060, 'ERROR 1060', '未安装'),
            SVC_ARQ: S.ServiceQuery(SVC_ARQ, 0, 'STATE: 4 RUNNING', '4 RUNNING'),
        }
        runner.on(['nssm', 'stop', SVC_ARQ], 0)
        results = S.control_many('stop', snapshots, NSSM, runner=runner.run)
        by = {r.service: r for r in results}
        assert by[SVC_API].detail == '未安装，跳过'
        assert by[SVC_ARQ].ok is True
        assert not runner.called_with(['nssm', 'stop', SVC_API])

    def test_does_not_skip_unknown_services(self, fake_runner_cls):
        """★ 未知 ≠ 未安装：未知状态必须照常执行命令（保守处理）。"""
        runner = fake_runner_cls()
        snapshots = {
            SVC_API: S.ServiceQuery(SVC_API, 5, 'Access denied', '未知'),
        }
        runner.on(['nssm', 'stop', SVC_API], 0)
        results = S.control_many('stop', snapshots, NSSM, runner=runner.run)
        assert results[0].ok is True
        assert runner.called_with(['nssm', 'stop', SVC_API])

    def test_skip_absent_can_be_disabled(self, fake_runner_cls):
        runner = fake_runner_cls()
        snapshots = {SVC_API: S.ServiceQuery(SVC_API, 1060, '', '未安装')}
        runner.on(['nssm', 'stop', SVC_API], 0)
        results = S.control_many('stop', snapshots, NSSM, skip_absent=False,
                                runner=runner.run)
        assert results[0].ok is True

    def test_preserves_snapshot_order(self, fake_runner_cls):
        runner = fake_runner_cls()
        snapshots = {
            SVC_API: S.ServiceQuery(SVC_API, 0, 'STATE: 4 RUNNING', '4 RUNNING'),
            SVC_ARQ: S.ServiceQuery(SVC_ARQ, 0, 'STATE: 4 RUNNING', '4 RUNNING'),
        }
        runner.on(['nssm', 'stop', SVC_API], 0)
        runner.on(['nssm', 'stop', SVC_ARQ], 0)
        results = S.control_many('stop', snapshots, NSSM, runner=runner.run)
        assert [r.service for r in results] == [SVC_API, SVC_ARQ]


class TestDetectInstalled:
    def test_returns_all_requested_names(self, fake_runner_cls):
        """★ 未安装的服务也要返回 —— 「未安装」与「查不到」语义不同，
        领域层必须都看到。"""
        runner = fake_runner_cls()
        runner.on(['sc', 'query', SVC_API], 0, RUNNING_OUT)
        runner.on(['sc', 'query', SVC_ARQ], 1060, '', 'ERROR 1060')
        out = S.detect_installed(runner=runner.run)
        assert set(out) == {SVC_API, SVC_ARQ}
        assert out[SVC_API].status is ServiceStatus.RUNNING
        assert out[SVC_ARQ].status is ServiceStatus.ABSENT

    def test_custom_names(self, fake_runner_cls):
        runner = fake_runner_cls().on(['sc', 'query', 'erp-redis'], 0, RUNNING_OUT)
        out = S.detect_installed(('erp-redis',), runner=runner.run)
        assert set(out) == {'erp-redis'}
