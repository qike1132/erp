"""domain.state_machine 的回归测试。

本模块守的是全项目最高风险的事故：**开发模式与生产模式互相厮杀**。
测试用例的设计原则是「每条断言都能对应到一次真实事故」，而不是追求覆盖率。

事故索引（详见 v8-P1执行记录-20260914.md）：
    §6.1  v5.33 超时分支返回 2 元组 → 调用方解包 3 元组崩溃
    P0-2  v5.33 生产停不掉（空洞的失败，无原因）
    P0-3  v5.33 宽特征扫描误杀 NSSM 被管进程 → 5 秒复活死循环
    #1    v5.39 因 sc 输出子串误判，互杀防护被从新入口绕过
    A5    v5.40 自证断言：状态未知且确认不了 → 中止切换，绝不静默放行
"""

from __future__ import annotations

import pytest

from server_manager_v8.domain.models import RunMode
from server_manager_v8.domain.service_state import ServiceStatus
from server_manager_v8.domain.state_machine import (
    DevProcessSpec,
    GuardKind,
    PreflightPlan,
    ServiceDecision,
    ServiceDisposition,
    StopResult,
    SwitchGuard,
    build_protected_pids,
    build_stop_abort_reason,
    decide_service_action,
    guard_sequence,
    is_residual_prod_runner,
    needs_restart_guard,
    plan_production_stop,
    select_dev_processes_to_stop,
)


# ═══════════════════════════════════════════════════════════════════
# StopResult —— 防 §6.1 的解包崩溃
# ═══════════════════════════════════════════════════════════════════


class TestStopResultContract:
    """§6.1：v5.33 的超时分支只返回 2 元组，调用方解包 3 元组 → 崩溃。

    frozen dataclass 从类型定义层面固定字段数，杜绝「少返回一个」。
    """

    def test_success_has_three_fields(self):
        r = StopResult.success(stopped_any=True)
        ok, reason, stopped_any = r  # 必须能三字段解包
        assert ok is True
        assert reason is None
        assert stopped_any is True

    def test_abort_has_three_fields(self):
        r = StopResult.abort('boom')
        ok, reason, stopped_any = r
        assert ok is False
        assert reason == 'boom'
        assert stopped_any is False

    @pytest.mark.parametrize('ok,stopped_any', [(True, True), (True, False), (False, True), (False, False)])
    def test_tuple_unpacking_never_raises(self, ok, stopped_any):
        """穷举 ok / stopped_any 组合，解包都不能抛异常。"""
        reason = None if ok else 'because'
        r = StopResult(ok=ok, reason=reason, stopped_any=stopped_any)
        assert len(tuple(r)) == 3

    def test_failure_without_reason_is_rejected(self):
        """P0-2：v5.33「生产停不掉」的一部分原因是失败没有可诊断的原因。"""
        with pytest.raises(ValueError, match='reason'):
            StopResult(ok=False)

    def test_failure_with_empty_reason_is_rejected(self):
        with pytest.raises(ValueError):
            StopResult(ok=False, reason='')

    def test_abort_forces_stopped_any_false(self):
        r = StopResult.abort('x')
        assert r.stopped_any is False

    def test_success_never_carries_reason(self):
        assert StopResult.success(stopped_any=False).reason is None

    def test_is_frozen(self):
        """不可变 —— 结果对象不允许被下游改写。"""
        r = StopResult.success(stopped_any=True)
        with pytest.raises(Exception):
            r.ok = False


# ═══════════════════════════════════════════════════════════════════
# decide_service_action —— 单个服务四态判定
# ═══════════════════════════════════════════════════════════════════


class TestDecideServiceAction:
    """迁移自 _ensure_production_stopped 循环体（L1559-1574）。"""

    def test_absent_is_skipped(self):
        """未安装 → 无需停止（服务不存在，也就没什么可停）。"""
        d = decide_service_action('erp-prod', ServiceStatus.ABSENT)
        assert d.disposition is ServiceDisposition.SKIP_ABSENT
        assert d.releases_immediately is True
        assert d.needs_stop_attempt is False

    def test_stopped_is_skipped(self):
        """已确认 STOPPED → 直接放行。"""
        d = decide_service_action('erp-prod', ServiceStatus.STOPPED)
        assert d.disposition is ServiceDisposition.ALREADY_STOPPED
        assert d.releases_immediately is True
        assert d.needs_stop_attempt is False

    def test_running_must_stop(self):
        d = decide_service_action('erp-prod', ServiceStatus.RUNNING)
        assert d.disposition is ServiceDisposition.MUST_STOP
        assert d.needs_stop_attempt is True
        assert d.releases_immediately is False
        assert d.is_unknown is False

    @pytest.mark.parametrize(
        'pseudo_status',
        [ServiceStatus.RUNNING, ServiceStatus.PENDING, ServiceStatus.UNKNOWN],
    )
    def test_all_non_stopped_states_must_attempt_stop(self, pseudo_status):
        """RUNNING / PENDING / UNKNOWN 一律必须尝试停止。

        PENDING（START_PENDING / STOP_PENDING）是中间态，
        此时端口可能仍被占用 —— 不能因为我们「没看清」就放行。
        """
        d = decide_service_action('erp-arq', pseudo_status)
        assert d.needs_stop_attempt is True

    @pytest.mark.parametrize(
        'status,expected',
        [
            (ServiceStatus.ABSENT, False),
            (ServiceStatus.STOPPED, False),
            (ServiceStatus.RUNNING, True),
            (ServiceStatus.PENDING, True),
            (ServiceStatus.UNKNOWN, True),
        ],
    )
    def test_full_state_cross_product(self, status, expected):
        """五态 × 是否需停止的完整对照表。"""
        assert decide_service_action('svc', status).needs_stop_attempt is expected

    def test_unknown_flag_only_on_unknown(self):
        """is_unknown 只对 UNKNOWN 为真 —— 它驱动警告文案的分支。"""
        assert decide_service_action('s', ServiceStatus.UNKNOWN).is_unknown is True
        for st in (
            ServiceStatus.ABSENT,
            ServiceStatus.STOPPED,
            ServiceStatus.RUNNING,
            ServiceStatus.PENDING,
        ):
            assert decide_service_action('s', st).is_unknown is False, st

    def test_decision_preserves_name_and_status(self):
        d = decide_service_action('erp-prod', ServiceStatus.RUNNING)
        assert d.service == 'erp-prod'
        assert d.status is ServiceStatus.RUNNING

    def test_is_frozen(self):
        d = decide_service_action('s', ServiceStatus.RUNNING)
        with pytest.raises(Exception):
            d.service = 'other'

    def test_decision_delegates_needs_stop_attempt(self):
        """ServiceDecision.needs_stop_attempt 必须与 disposition 保持一致。"""
        for st in ServiceStatus:
            d = decide_service_action('s', st)
            assert d.needs_stop_attempt == d.disposition.needs_stop_attempt


# ═══════════════════════════════════════════════════════════════════
# plan_production_stop —— 编排判定
# ═══════════════════════════════════════════════════════════════════


class TestPlanProductionStop:
    """迁移自 _ensure_production_stopped 前半段。"""

    def test_empty_snapshots_needs_no_stop(self):
        plan = plan_production_stop({})
        assert plan.services_to_stop == []
        assert plan.needs_any_stop is False
        assert plan.warnings == []

    def test_both_absent_needs_no_stop(self):
        plan = plan_production_stop(
            {'erp-prod': ServiceStatus.ABSENT, 'erp-arq': ServiceStatus.ABSENT}
        )
        assert plan.needs_any_stop is False
        assert plan.warnings == []

    def test_one_running_triggers_stop(self):
        plan = plan_production_stop(
            {'erp-prod': ServiceStatus.RUNNING, 'erp-arq': ServiceStatus.STOPPED}
        )
        assert plan.services_to_stop == ['erp-prod']
        assert plan.needs_any_stop is True

    def test_unknown_produces_warning_with_exact_wording(self):
        """警告文案必须逐字迁移（运维靠它认日志）。"""
        plan = plan_production_stop({'erp-prod': ServiceStatus.UNKNOWN})
        assert plan.warnings == ['无法查询 erp-prod 状态（sc 查询失败），按运行中保守处理']
        assert plan.unknown_services == ['erp-prod']

    def test_unknown_still_must_stop(self):
        """A5 安全性质：未知 ≠ 放行，仍须尝试停止。"""
        plan = plan_production_stop({'erp-prod': ServiceStatus.UNKNOWN})
        assert plan.services_to_stop == ['erp-prod']

    def test_each_unknown_gets_its_own_warning(self):
        plan = plan_production_stop(
            {'erp-prod': ServiceStatus.UNKNOWN, 'erp-arq': ServiceStatus.UNKNOWN}
        )
        assert len(plan.warnings) == 2
        assert plan.unknown_services == ['erp-prod', 'erp-arq']
        assert plan.services_to_stop == ['erp-prod', 'erp-arq']

    def test_no_warning_for_known_states(self):
        plan = plan_production_stop(
            {
                'erp-prod': ServiceStatus.RUNNING,
                'erp-arq': ServiceStatus.STOPPED,
            }
        )
        assert plan.warnings == []

    def test_decision_order_follows_snapshot_order(self):
        plan = plan_production_stop(
            {'erp-prod': ServiceStatus.RUNNING, 'erp-arq': ServiceStatus.RUNNING}
        )
        assert [d.service for d in plan.decisions] == ['erp-prod', 'erp-arq']

    def test_plan_has_default_empty_collections(self):
        plan = PreflightPlan()
        assert plan.decisions == []
        assert plan.warnings == []
        assert plan.needs_any_stop is False

    def test_realistic_all_five_states(self):
        """一次覆盖全部五态，验证只有该停的才进 services_to_stop。"""
        plan = plan_production_stop(
            {
                'erp-prod': ServiceStatus.RUNNING,
                'erp-arq': ServiceStatus.PENDING,
                'erp-redis': ServiceStatus.UNKNOWN,
                'erp-redis-broker': ServiceStatus.STOPPED,
                'erp-ghost': ServiceStatus.ABSENT,
            }
        )
        assert plan.services_to_stop == ['erp-prod', 'erp-arq', 'erp-redis']
        assert plan.unknown_services == ['erp-redis']
        assert len(plan.warnings) == 1


# ═══════════════════════════════════════════════════════════════════
# build_stop_abort_reason —— 中止原因文案
# ═══════════════════════════════════════════════════════════════════


class TestBuildStopAbortReason:
    """迁移自 L1571-1572，两种文案按「是否未知」区分。"""

    def test_unknown_wording(self):
        msg = build_stop_abort_reason('erp-prod', ServiceStatus.UNKNOWN)
        assert msg == 'erp-prod 状态未知且未能在超时内确认 STOPPED，已中止切换'

    @pytest.mark.parametrize(
        'status',
        [
            ServiceStatus.RUNNING,
            ServiceStatus.PENDING,
            ServiceStatus.STOPPED,
            ServiceStatus.ABSENT,
        ],
    )
    def test_non_unknown_wording(self, status):
        msg = build_stop_abort_reason('erp-arq', status)
        assert msg == 'erp-arq 停止超时（STOP_PENDING 未确认），已中止切换'

    def test_reason_is_never_empty(self):
        """中止必须带原因 —— 与 StopResult 的约束呼应。"""
        for st in ServiceStatus:
            assert build_stop_abort_reason('svc', st).strip()

    def test_abort_reason_integrates_with_stop_result(self):
        r = StopResult.abort(build_stop_abort_reason('erp-prod', ServiceStatus.UNKNOWN))
        assert r.ok is False
        assert 'erp-prod' in r.reason


# ═══════════════════════════════════════════════════════════════════
# build_protected_pids —— P0-3 修复点
# ═══════════════════════════════════════════════════════════════════


class TestBuildProtectedPids:
    """迁移自 L1576-1580。★ v5.33 P0-3 的修复点。

    v5.33 的宽特征扫描误杀了 NSSM 被管进程：
      → NSSM 检测到 Exit → 5 秒后重启 → 又被误杀 → 死循环
    正解 = 精准特征 + PID 白名单双保险。
    """

    def test_self_pid_always_protected(self):
        assert build_protected_pids(9999, {}) == frozenset({9999})

    def test_service_pids_are_protected(self):
        protected = build_protected_pids(100, {'erp-prod': 200, 'erp-arq': 300})
        assert protected == frozenset({100, 200, 300})

    def test_none_pids_are_dropped(self):
        """服务未安装时 _svc_pid 返回 None，不能把 None 放进集合。"""
        protected = build_protected_pids(100, {'erp-prod': None, 'erp-arq': None})
        assert protected == frozenset({100})
        assert None not in protected

    def test_zero_pid_is_dropped(self):
        """PID 0 不是有效进程号（v5.40 审查 #23：TIME_WAIT 行的 PID 恒为 0）。"""
        protected = build_protected_pids(100, {'erp-prod': 0})
        assert protected == frozenset({100})

    def test_mixed_valid_and_invalid(self):
        protected = build_protected_pids(
            42, {'erp-prod': 7, 'erp-arq': None, 'erp-x': 0}
        )
        assert protected == frozenset({42, 7})

    def test_returns_frozenset(self):
        assert isinstance(build_protected_pids(1, {}), frozenset)

    def test_own_service_pid_never_killed(self):
        """端到端安全性质：自身管理的服务进程绝不在可杀集合里。"""
        protected = build_protected_pids(100, {'erp-prod': 200})
        assert is_residual_prod_runner(['python', 'prod_runner.py'], 200, protected) is False


# ═══════════════════════════════════════════════════════════════════
# is_residual_prod_runner —— 精准特征（非宽特征扫描）
# ═══════════════════════════════════════════════════════════════════


class TestIsResidualProdRunner:
    """迁移自 L1581-1589。关键是「精准」二字。"""

    def test_prod_runner_in_cmdline(self):
        assert is_residual_prod_runner(
            ['python', 'C:/erp/prod_runner.py', '--port', '5002'], 500, frozenset()
        ) is True

    def test_prod_runner_as_bare_token(self):
        assert is_residual_prod_runner(['prod_runner'], 500, frozenset()) is True

    def test_plain_python_is_not_a_residual(self):
        """★ P0-3 核心断言：普通 python 进程**不是**残留，不能杀。

        v5.33 用宽特征（'python' in cmdline）扫描，把 NSSM 正在监管的
        服务进程也一并杀掉，触发 NSSM AppExit 5 秒重启 → 死循环。
        """
        assert is_residual_prod_runner(['python', 'manage.py'], 500, frozenset()) is False

    def test_node_is_not_a_residual(self):
        """同理，node 进程（前端 dev server）也不该被误杀。"""
        assert is_residual_prod_runner(['node', 'vite.js'], 500, frozenset()) is False

    def test_erp_keyword_alone_is_not_enough(self):
        """'erp' 这种宽泛关键词不能作为特征。"""
        assert is_residual_prod_runner(['python', 'erp_server.py'], 500, frozenset()) is False

    def test_protected_pid_is_never_a_residual(self):
        assert is_residual_prod_runner(
            ['python', 'prod_runner.py'], 500, frozenset({500})
        ) is False

    def test_empty_cmdline_is_not_a_residual(self):
        assert is_residual_prod_runner([], 500, frozenset()) is False
        assert is_residual_prod_runner(None, 500, frozenset()) is False

    def test_falsy_pid_is_not_a_residual(self):
        assert is_residual_prod_runner(['prod_runner'], 0, frozenset()) is False
        assert is_residual_prod_runner(['prod_runner'], None, frozenset()) is False

    def test_tuple_cmdline_accepted(self):
        """psutil 返回的是 list，但测试/适配层可能传 tuple。"""
        assert is_residual_prod_runner(('python', 'prod_runner.py'), 500, frozenset()) is True

    def test_case_sensitive(self):
        """旧实现是大小写敏感的 `in`；这里保持原语义（迁移保真）。"""
        assert is_residual_prod_runner(['PROD_RUNNER.PY'], 500, frozenset()) is False

    def test_path_containing_prod_runner_matches(self):
        """子串匹配 —— 路径中任意位置出现即命中（对齐旧实现）。"""
        assert is_residual_prod_runner(
            ['python', 'D:/erp/scripts/prod_runner_v2.py'], 500, frozenset()
        ) is True


# ═══════════════════════════════════════════════════════════════════
# SwitchGuard / needs_restart_guard / guard_sequence
# ═══════════════════════════════════════════════════════════════════


class TestSwitchGuard:
    def test_same_mode_is_noop(self):
        g = SwitchGuard(current=RunMode.PROD, target=RunMode.PROD)
        assert g.is_noop is True
        assert g.must_stop_first is None

    def test_dev_to_prod_must_stop_dev(self):
        """互杀防护的主场景：启生产前必须先停开发。"""
        g = SwitchGuard(current=RunMode.DUAL_DEV, target=RunMode.PROD)
        assert g.must_stop_first is RunMode.DUAL_DEV
        assert g.is_noop is False
        assert g.involves_production is True

    def test_prod_to_dev_must_stop_prod(self):
        """反向同样成立：启开发前必须先停生产。"""
        g = SwitchGuard(current=RunMode.PROD, target=RunMode.DUAL_DEV)
        assert g.must_stop_first is RunMode.PROD
        assert g.involves_production is True

    def test_none_to_prod_needs_no_stop(self):
        """当前什么都没跑 → 无需先停，可直接启动。"""
        g = SwitchGuard(current=RunMode.NONE, target=RunMode.PROD)
        assert g.must_stop_first is None
        assert g.involves_production is True

    def test_none_to_dev_needs_no_stop(self):
        g = SwitchGuard(current=RunMode.NONE, target=RunMode.DUAL_DEV)
        assert g.must_stop_first is None
        assert g.involves_production is False

    def test_prod_to_none_must_stop_prod(self):
        g = SwitchGuard(current=RunMode.PROD, target=RunMode.NONE)
        assert g.must_stop_first is RunMode.PROD

    def test_dev_to_none_must_stop_dev(self):
        g = SwitchGuard(current=RunMode.DUAL_DEV, target=RunMode.NONE)
        assert g.must_stop_first is RunMode.DUAL_DEV

    def test_none_to_none_is_noop(self):
        g = SwitchGuard(current=RunMode.NONE, target=RunMode.NONE)
        assert g.is_noop is True
        assert g.must_stop_first is None

    def test_must_stop_first_equals_current_when_conflicting(self):
        """冲突时 must_stop_first 恒等于 current（语义清晰化）。"""
        for cur in RunMode:
            for tgt in RunMode:
                g = SwitchGuard(current=cur, target=tgt)
                if cur is RunMode.NONE or cur is tgt:
                    assert g.must_stop_first is None
                else:
                    assert g.must_stop_first is cur

    def test_involves_production_covers_both_directions(self):
        assert SwitchGuard(RunMode.PROD, RunMode.NONE).involves_production is True
        assert SwitchGuard(RunMode.NONE, RunMode.PROD).involves_production is True
        assert SwitchGuard(RunMode.PROD, RunMode.DUAL_DEV).involves_production is True
        assert SwitchGuard(RunMode.DUAL_DEV, RunMode.PROD).involves_production is True
        assert SwitchGuard(RunMode.NONE, RunMode.DUAL_DEV).involves_production is False

    def test_is_frozen(self):
        g = SwitchGuard(RunMode.NONE, RunMode.PROD)
        with pytest.raises(Exception):
            g.target = RunMode.DUAL_DEV


class TestNeedsRestartGuard:
    """D6 语义：guard 只对 NSSM 托管的 erp-prod / erp-arq 有效。"""

    def test_true_only_when_nssm_available(self):
        assert needs_restart_guard(RunMode.PROD, True) is True
        assert needs_restart_guard(RunMode.PROD, False) is False

    def test_target_mode_does_not_affect_decision(self):
        """★ D6：原生 Windows 服务（erp-redis）没有 AppExit 概念，
        所以判定只看 nssm 是否存在，与目标模式无关。"""
        for tgt in RunMode:
            assert needs_restart_guard(tgt, True) is True
            assert needs_restart_guard(tgt, False) is False

    def test_returns_plain_bool(self):
        """防止 `a or b if c else d` 这类优先级陷阱（本项目踩过）。"""
        assert needs_restart_guard(RunMode.PROD, True) is True
        assert isinstance(needs_restart_guard(RunMode.PROD, True), bool)


class TestGuardSequence:
    def test_no_nssm_means_no_guard_calls(self):
        assert guard_sequence(False) == ()

    def test_nssm_yields_disable_then_enable(self):
        """成对出现 —— finally 保证恢复。"""
        assert guard_sequence(True) == (GuardKind.DISABLE, GuardKind.ENABLE)

    def test_order_is_disable_before_enable(self):
        seq = guard_sequence(True)
        assert seq.index(GuardKind.DISABLE) < seq.index(GuardKind.ENABLE)

    def test_guard_values_match_nssm_appexit(self):
        """AppExit 取值必须与 NSSM 命令行一致（Exit / Restart）。"""
        assert GuardKind.DISABLE.value == 'Exit'
        assert GuardKind.ENABLE.value == 'Restart'

    def test_sequence_is_balanced(self):
        """Disable 与 Enable 数量必须相等，否则会留下禁用状态。"""
        seq = guard_sequence(True)
        assert seq.count(GuardKind.DISABLE) == seq.count(GuardKind.ENABLE)


# ═══════════════════════════════════════════════════════════════════
# select_dev_processes_to_stop
# ═══════════════════════════════════════════════════════════════════


class TestSelectDevProcessesToStop:
    """迁移自 _ensure_development_stopped 的循环条件。"""

    def test_processes_with_pid_are_selected(self):
        procs = [DevProcessSpec('前端', 100), DevProcessSpec('后端', 200)]
        assert select_dev_processes_to_stop(procs) == procs

    def test_processes_without_pid_are_skipped(self):
        """proc 为 None 或已退出（poll() 非 None）→ 无需终止。"""
        procs = [DevProcessSpec('前端', None), DevProcessSpec('后端', None)]
        assert select_dev_processes_to_stop(procs) == []

    def test_mixed_selection(self):
        procs = [DevProcessSpec('前端', 100), DevProcessSpec('后端', None)]
        result = select_dev_processes_to_stop(procs)
        assert [p.role_label for p in result] == ['前端']

    def test_empty_input(self):
        assert select_dev_processes_to_stop([]) == []

    def test_order_preserved(self):
        procs = [DevProcessSpec('前端', 1), DevProcessSpec('后端', 2)]
        assert [p.role_label for p in select_dev_processes_to_stop(procs)] == ['前端', '后端']

    def test_redis_is_not_in_the_dev_process_list(self):
        """★ 关键语义：只停开发子进程，不动 Redis。

        Redis 是生产与开发共用的基础设施 —— 停它会波及生产。
        本测试以「输入里根本不包含 Redis 角色」固化这个约定。
        """
        procs = [DevProcessSpec('前端', 1), DevProcessSpec('后端', 2)]
        selected = select_dev_processes_to_stop(procs)
        assert all('redis' not in p.role_label.lower() for p in selected)
