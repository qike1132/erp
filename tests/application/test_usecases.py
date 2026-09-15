"""用例层的单测 —— 编排、权限、幂等、保守中止。

═══════════════════════════════════════════════════════════════════
本文件重点覆盖「不讲出来就会被写错」的行为
═══════════════════════════════════════════════════════════════════

    · **中止语义**：互斥防护失败 → 后续步骤一步都不能跑
    · **幂等**：已在目标模式时不重复操作
    · **保守方向**：「未知」状态一律按危险侧处理（不停 = 不放行）
    · **确认流程**：L2 要弹窗、L3 要输入名称 + 填原因
    · **被拒留痕**：权限不足必须写审计（4A 要求）
    · **口径不可混用**：杀进程只认 LISTENING，展示才用 ESTABLISHED
    · **返回值与副作用**：`OpResult` 说成功，实际状态必须真的变了

★ 一条贯穿全文件的纪律：**断言副作用，不只断言返回值**。
  用例最容易犯的错就是「返回成功但什么都没做」，
  而只断言 `result.ok` 的测试完全看不出这种错。
"""

from __future__ import annotations

import pytest

from server_manager_v8.application.auth.guard import (
    ConfirmKind,
    ConfirmationToken,
)
from server_manager_v8.application.auth.session import Session
from server_manager_v8.application.usecases.alert_ops import (
    AlertOps,
    MAX_SILENCE_S,
)
from server_manager_v8.application.usecases.backup_ops import (
    CONFIRM_WORD_RESTORE,
    PRERESTORE_SUFFIX,
    BackupOps,
)
from server_manager_v8.application.usecases.config_ops import (
    CONFIRM_WORD_RESET,
    ConfigOps,
)
from server_manager_v8.application.usecases.deps import Deps, make_deps
from server_manager_v8.application.usecases.install_services import (
    CONFIRM_WORD_INSTALL,
    CONFIRM_WORD_UNINSTALL,
    InstallServices,
    UninstallServices,
    required_confirmation,
)
from server_manager_v8.application.usecases.kill_port import KillPort
from server_manager_v8.application.usecases.log_ops import LogOps
from server_manager_v8.application.usecases.start_dev import (
    STARTUP_STEPS,
    StartDev,
)
from server_manager_v8.application.usecases.start_prod import (
    PROD_START_STEPS,
    StartProd,
)
from server_manager_v8.application.usecases.stop_all import (
    REDIS_SERVICES,
    StopAll,
)
from server_manager_v8.application.usecases.switch_mode import (
    SwitchMode,
    detect_mode,
)
from server_manager_v8.domain.models import RunMode
from server_manager_v8.domain.permissions import Action, Role
from server_manager_v8.domain.results import (
    AuditOutcome,
    KillResult,
    OpResult,
    ServiceCmd,
    Severity,
)
from server_manager_v8.domain.service_state import ServiceStatus
from tests.application.conftest import (
    FakeAudit,
    FakeClock,
    FakeProcess,
    FakeService,
    FakeStorage,
)

# ═══════════════════════════════════════════════════════════════════
# 测试辅助
# ═══════════════════════════════════════════════════════════════════


def admin_session(deps: Deps, role: Role = Role.ADMIN) -> Session:
    """提权到指定角色的会话。"""
    session = Session(clock=deps.clock)
    session.elevate(role)
    return session


def modal_token() -> ConfirmationToken:
    """L2 二次确认令牌。"""
    return ConfirmationToken(kind=ConfirmKind.MODAL, impact='测试')


def typed_token(word: str, reason: str = '测试原因') -> ConfirmationToken:
    """L3 输入名称确认令牌。"""
    return ConfirmationToken(kind=ConfirmKind.TYPED, typed_name=word,
                             reason=reason)


def running_states(*names: str) -> dict[str, ServiceStatus]:
    return {name: ServiceStatus.RUNNING for name in names}


def stopped_states(*names: str) -> dict[str, ServiceStatus]:
    return {name: ServiceStatus.STOPPED for name in names}


# ═══════════════════════════════════════════════════════════════════
# StopAll —— 停止全部
# ═══════════════════════════════════════════════════════════════════


class TestStopAllPipeline:
    def test_steps_include_guard_before_stop(self):
        """★ 守卫步骤必须在「停止服务」**之前** —— 顺序反了会死循环。"""
        deps = make_deps()
        names = StopAll(deps)._build_pipeline(stop_redis=True, target='prod').step_names
        assert names.index('挂载重启守卫') < names.index('停止生产服务')

    def test_guard_released_last(self):
        """守卫解除必须在最后（若在前面解除，服务还没停稳会被拉起）。"""
        deps = make_deps()
        names = StopAll(deps)._build_pipeline(stop_redis=True, target='prod').step_names
        assert names[-1] == '解除重启守卫'

    def test_redis_step_optional(self):
        deps = make_deps()
        with_redis = StopAll(deps)._build_pipeline(stop_redis=True, target='p').step_names
        without = StopAll(deps)._build_pipeline(stop_redis=False, target='p').step_names
        assert '停止 Redis 服务' in with_redis
        assert '停止 Redis 服务' not in without

    def test_residual_cleanup_is_non_critical(self):
        """★ 残留清理失败不阻断整体流程（尽力而为语义）。"""
        deps = make_deps()
        pipeline = StopAll(deps)._build_pipeline(stop_redis=True, target='p')
        critical = {s.name: s.critical for s in pipeline._steps}
        assert critical['清理残留进程'] is False
        assert critical['停止生产服务'] is True


class TestStopAllBehaviour:
    def test_missing_psutil_reports_skip_not_success(self):
        """★ 缺 psutil 时「跳过」必须显式报告，不能装成「扫了没发现」。"""
        deps = make_deps(process=FakeProcess(psutil_ok=False))
        ctx = __import__(
            'server_manager_v8.application.usecases.stop_all', fromlist=['StopAllContext'],
        ).StopAllContext(deps=deps)
        result = StopAll(deps)._kill_residual(ctx)
        assert not result.ok
        assert 'psutil' in result.detail

    def test_unknown_state_is_not_accepted_as_stopped(self):
        """★ 「未知」不算已停止 —— 必须继续等到能确认（保守方向）。"""
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.UNKNOWN}))
        ctx = __import__(
            'server_manager_v8.application.usecases.stop_all', fromlist=['StopAllContext'],
        ).StopAllContext(deps=deps)
        result = StopAll(deps)._confirm_nssm_stopped(ctx)
        assert not result.ok
        assert '保守中止' in result.reason

    def test_absent_counts_as_stopped(self):
        """「未安装」算已停止（服务不存在，无需等待）。"""
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.ABSENT,
                                                     'erp-arq': ServiceStatus.ABSENT}))
        ctx = __import__(
            'server_manager_v8.application.usecases.stop_all', fromlist=['StopAllContext'],
        ).StopAllContext(deps=deps)
        result = StopAll(deps)._confirm_nssm_stopped(ctx)
        assert result.ok

    def test_guard_failure_aborts_before_stopping(self):
        """★ 守卫挂不上 → 关键失败（继续停服务可能触发自动重启死循环）。"""
        svc = FakeService()
        svc.guard_result = OpResult.failure('nssm 拒绝访问')
        deps = make_deps(service=svc)
        ctx = __import__(
            'server_manager_v8.application.usecases.stop_all', fromlist=['StopAllContext'],
        ).StopAllContext(deps=deps)
        result = StopAll(deps)._set_guard(ctx)
        assert not result.ok
        assert '重启守卫' in result.reason

    def test_viewer_cannot_stop_prod(self):
        """L2 操作需要 Operator+。"""
        deps = make_deps()
        result = StopAll(deps).execute(
            session=Session(clock=deps.clock), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert result.reason == '权限不足'

    def test_missing_modal_confirmation_is_rejected(self):
        """L2 需要二次确认；不给令牌必须被拦。"""
        deps = make_deps()
        result = StopAll(deps).execute(
            session=admin_session(deps), event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert result.reason == '缺少确认'

    def test_denied_attempt_is_audited(self):
        """★ 被拒必须留痕（4A：谁在什么权限下被拦）。"""
        deps = make_deps()
        StopAll(deps).execute(
            session=Session(clock=deps.clock), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert len(deps.audit.entries) == 1
        assert deps.audit.last.outcome is AuditOutcome.DENIED
        assert deps.audit.last.action == Action.STOP_PROD_SERVICE.value


# ═══════════════════════════════════════════════════════════════════
# StartDev —— 启动开发模式
# ═══════════════════════════════════════════════════════════════════


class TestStartDevSteps:
    def test_step_names_are_verbatim_from_legacy(self):
        """★ 步骤名逐字保留旧 `_startup_steps` —— UI 进度条直接显示它们。"""
        deps = make_deps()
        assert StartDev(deps)._build_pipeline().step_names == STARTUP_STEPS

    def test_legacy_step_names_exact_strings(self):
        assert STARTUP_STEPS == (
            '停止生产模式', '检查Redis服务', '启动后端服务',
            '启动前端服务', '完成',
        )


class TestStartDevMutexProtection:
    def test_production_running_causes_stop_first(self):
        """★ 互斥防护：生产在跑 → 第一步必须先把它停掉。"""
        svc = FakeService(states=running_states('erp-prod', 'erp-arq',
                                                'erp-redis', 'erp-redis-broker'))
        deps = make_deps(service=svc)
        start = StartDev(deps)
        result = start.execute(
            session=admin_session(deps), confirm=modal_token(), target='dev',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        # 后端启动未接入 → 整体失败，但停止流程必须已执行过
        actions = [c for c in svc.calls if c[0] in ('set_restart_guard', 'request_stop')]
        assert actions, '生产在跑时未执行停止流程'

    def test_unknown_state_blocks_switch(self):
        """★ 「未知」算运行中 → 保守中止，绝不继续启动后端。"""
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.UNKNOWN,
                                                     'erp-arq': ServiceStatus.STOPPED}))
        svc = deps.service
        start = StartDev(deps)
        start.execute(session=admin_session(deps), confirm=modal_token(),
                      target='dev', event_bus=deps.event_bus, audit=deps.audit)
        # 未接入后端的失败在前，但绝不能发出 START 命令
        starts = [c for c in svc.calls
                  if c[0] == 'control' and c[1][1] is ServiceCmd.START]
        assert not starts, '状态未知时不得启动任何服务'

    def test_nothing_running_skips_stop_entirely(self):
        """生产本来就没跑 → 跳过整个停止流程（省掉挂守卫的副作用）。"""
        svc = FakeService(states=stopped_states('erp-prod', 'erp-arq',
                                               'erp-redis', 'erp-redis-broker'))
        deps = make_deps(service=svc)
        StartDev(deps).execute(
            session=admin_session(deps), confirm=modal_token(), target='dev',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not [c for c in svc.calls if c[0] == 'set_restart_guard']


class TestStartDevRedis:
    def test_redis_missing_is_warning_not_failure(self):
        """★ Redis 未安装是**警告**（旧实现行为）—— 直接失败会让没装 Redis 的机器无法用。"""
        deps = make_deps(service=FakeService(states={
            'erp-prod': ServiceStatus.STOPPED, 'erp-arq': ServiceStatus.STOPPED,
            'erp-redis': ServiceStatus.ABSENT, 'erp-redis-broker': ServiceStatus.ABSENT,
        }))
        ctx = __import__(
            'server_manager_v8.application.usecases.start_dev', fromlist=['StartDevContext'],
        ).StartDevContext(deps=deps)
        result = StartDev(deps)._ensure_redis(ctx)
        assert result.ok
        assert '未安装' in result.detail

    def test_stopped_redis_is_started(self):
        svc = FakeService(states={'erp-redis': ServiceStatus.STOPPED,
                                  'erp-redis-broker': ServiceStatus.STOPPED})
        deps = make_deps(service=svc)
        ctx = __import__(
            'server_manager_v8.application.usecases.start_dev', fromlist=['StartDevContext'],
        ).StartDevContext(deps=deps)
        StartDev(deps)._ensure_redis(ctx)
        starts = [c for c in svc.calls
                  if c[0] == 'control' and c[1][1] is ServiceCmd.START]
        assert len(starts) == len(REDIS_SERVICES)


class TestStartDevUnimplemented:
    def test_backend_start_reports_not_implemented(self):
        """★ 依赖尚未实现的 spawn() → 明确失败，**不假装成功**。"""
        deps = make_deps()
        ctx = __import__(
            'server_manager_v8.application.usecases.start_dev', fromlist=['StartDevContext'],
        ).StartDevContext(deps=deps)
        result = StartDev(deps)._start_backend(ctx)
        assert not result.ok
        assert '未接入' in result.reason
        assert 'spawn' in result.detail

    def test_aborts_at_backend_step(self):
        """后端启动失败（关键步骤）→ 中止，前端步骤不再执行。"""
        deps = make_deps()
        result = StartDev(deps).execute(
            session=admin_session(deps), confirm=modal_token(), target='dev',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert '启动后端服务' in result.reason
        assert '中止' in result.detail


# ═══════════════════════════════════════════════════════════════════
# StartProd —— 启动生产模式
# ═══════════════════════════════════════════════════════════════════


class TestStartProd:
    def test_step_names_present(self):
        deps = make_deps()
        assert StartProd(deps)._build_pipeline().step_names == PROD_START_STEPS

    def test_own_service_pids_excluded_from_intruders(self):
        """★ 生产服务自己的进程不能算「残留」——
        否则每次重启生产都先自杀再启动。"""
        svc = FakeService(states=stopped_states('erp-prod', 'erp-arq'),
                          pids={'erp-prod': 111, 'erp-arq': 222})
        proc = FakeProcess(port_pids={5002: [111]})
        deps = make_deps(service=svc, process=proc,
                         ports={'backend': 5002, 'frontend': 3000})
        start = StartProd(deps)
        ctx = __import__(
            'server_manager_v8.application.usecases.start_prod', fromlist=['StartProdContext'],
        ).StartProdContext(deps=deps)
        start._stop_dev_residual(ctx)
        assert 111 not in [c[1] for c in proc.calls if c[0] == 'kill_tree']

    def test_intruder_is_killed_with_narrow_filter(self):
        """★ 决定杀谁时必须用窄口径（只认 LISTENING）。"""
        proc = FakeProcess(port_pids={5002: [999]})
        deps = make_deps(process=proc, ports={'backend': 5002, 'frontend': 3000})
        ctx = __import__(
            'server_manager_v8.application.usecases.start_prod', fromlist=['StartProdContext'],
        ).StartProdContext(deps=deps)
        StartProd(deps)._stop_dev_residual(ctx)
        probes = [c[1] for c in proc.calls if c[0] == 'find_port_pids']
        assert probes, '未查询端口'
        assert all(listening_only is True for _, listening_only in probes), \
            '杀进程前必须用 LISTENING_ONLY 口径'
        assert [c[1] for c in proc.calls if c[0] == 'kill_tree'] == [999]

    def test_intruder_kill_failure_aborts(self):
        """★ 清不干净 → 中止（与 StartDev 的互斥防护等位）。"""
        proc = FakeProcess(port_pids={5002: [999]}, release_on_kill=False)
        deps = make_deps(process=proc, ports={'backend': 5002, 'frontend': 3000})
        ctx = __import__(
            'server_manager_v8.application.usecases.start_prod', fromlist=['StartProdContext'],
        ).StartProdContext(deps=deps)
        result = StartProd(deps)._stop_dev_residual(ctx)
        assert not result.ok
        assert '中止' in result.reason

    def test_redis_missing_is_failure(self):
        """★ 与 StartDev 相反：生产模式 Redis 缺失**必须失败**。"""
        deps = make_deps(service=FakeService(states={
            'erp-redis': ServiceStatus.ABSENT, 'erp-redis-broker': ServiceStatus.ABSENT,
        }))
        ctx = __import__(
            'server_manager_v8.application.usecases.start_prod', fromlist=['StartProdContext'],
        ).StartProdContext(deps=deps)
        result = StartProd(deps)._ensure_redis(ctx)
        assert not result.ok
        assert 'Redis' in result.reason

    def test_success_path_when_all_running(self):
        deps = make_deps(service=FakeService(states=running_states(
            'erp-prod', 'erp-arq', 'erp-redis', 'erp-redis-broker')))
        result = StartProd(deps).execute(
            session=admin_session(deps), confirm=modal_token(), target='prod',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '2 个服务就绪' in result.detail

    def test_missing_ports_are_reported_not_silently_passed(self):
        """★ 没配端口时明确说「未探活」，不能说成「探活通过」。"""
        deps = make_deps(service=FakeService(states=running_states(
            'erp-prod', 'erp-arq', 'erp-redis', 'erp-redis-broker')))
        ctx = __import__(
            'server_manager_v8.application.usecases.start_prod', fromlist=['StartProdContext'],
        ).StartProdContext(deps=deps)
        notes = StartProd(deps)._probe_http('erp-prod', ctx)
        assert notes and '未做 HTTP 探活' in notes[0]

    def test_probe_failure_is_note_not_failure(self):
        """★ HTTP 探活失败降级为备注（worker 类服务可能没有 HTTP 端口）。"""
        from server_manager_v8.domain.results import HealthSample

        health = __import__('tests.application.conftest', fromlist=['FakeHealth']).FakeHealth(
            results=[HealthSample(ok=False, detail='连接被拒')])
        deps = make_deps(health=health, ports={'backend': 5002, 'frontend': 3000})
        ctx = __import__(
            'server_manager_v8.application.usecases.start_prod', fromlist=['StartProdContext'],
        ).StartProdContext(deps=deps)
        notes = StartProd(deps)._probe_http('erp-prod', ctx)
        assert any('未通过' in n for n in notes)


# ═══════════════════════════════════════════════════════════════════
# SwitchMode —— 模式探测与幂等
# ═══════════════════════════════════════════════════════════════════


class TestDetectMode:
    def test_nothing_running_is_none(self):
        assert detect_mode(make_deps()).mode is RunMode.NONE

    def test_prod_services_running_is_prod(self):
        deps = make_deps(service=FakeService(states=running_states('erp-prod')))
        assert detect_mode(deps).mode is RunMode.PROD

    def test_port_occupied_without_services_is_dev(self):
        """★ 开发模式是裸进程，不注册为服务 → 只能靠端口判定。"""
        deps = make_deps(process=FakeProcess(port_pids={5002: [999]}),
                         ports={'backend': 5002, 'frontend': 3000})
        assert detect_mode(deps).mode is RunMode.DUAL_DEV

    def test_both_present_is_conflict(self):
        deps = make_deps(service=FakeService(states=running_states('erp-prod')),
                         process=FakeProcess(port_pids={5002: [999]}),
                         ports={'backend': 5002, 'frontend': 3000})
        snap = detect_mode(deps)
        assert snap.is_conflicting

    def test_unknown_service_is_ambiguous(self):
        """★ 未知状态 → 不能宣称「已在某模式」（会跳过必要的停止）。"""
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.UNKNOWN}))
        snap = detect_mode(deps)
        assert snap.ambiguous
        assert snap.prod_services_unknown == ('erp-prod',)

    def test_pending_counts_as_running(self):
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.PENDING}))
        assert detect_mode(deps).mode is RunMode.PROD

    def test_uses_narrow_port_filter(self):
        """★ 用宽口径会让「有客户端连接」被误判成「开发模式在跑」。"""
        proc = FakeProcess(port_pids={5002: [999]})
        deps = make_deps(process=proc, ports={'backend': 5002, 'frontend': 3000})
        detect_mode(deps)
        probes = [c[1] for c in proc.calls if c[0] == 'find_port_pids']
        assert all(listening_only is True for _, listening_only in probes)


class TestSwitchMode:
    def test_idempotent_when_already_target(self):
        """★ 已在目标模式 → 不重复操作（旧实现会再启动一遍）。"""
        deps = make_deps(service=FakeService(states=running_states('erp-prod', 'erp-arq')))
        result = SwitchMode(deps).execute(
            session=admin_session(deps), confirm=modal_token(), mode='prod',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '无需切换' in result.detail

    def test_ambiguous_aborts_conservatively(self):
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.UNKNOWN}))
        result = SwitchMode(deps).execute(
            session=admin_session(deps), confirm=modal_token(), mode='prod',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert '保守中止' in result.reason
        assert '互杀' in result.detail

    def test_conflicting_state_goes_through_full_switch(self):
        """★ 两套同时存在 → 不幂等跳过，走完整清场。"""
        deps = make_deps(service=FakeService(states=running_states('erp-prod', 'erp-arq')),
                         process=FakeProcess(port_pids={5002: [999]}),
                         ports={'backend': 5002, 'frontend': 3000})
        result = SwitchMode(deps).execute(
            session=admin_session(deps), confirm=modal_token(), mode='prod',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert '无需切换' not in (result.detail or '')

    @pytest.mark.parametrize('raw', ['prod', 'production', 'PROD', ' prod '])
    def test_accepts_prod_aliases(self, raw):
        deps = make_deps(service=FakeService(states=running_states('erp-prod', 'erp-arq')))
        result = SwitchMode(deps).execute(
            session=admin_session(deps), confirm=modal_token(), mode=raw,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok

    @pytest.mark.parametrize('raw', ['dev', 'dual_dev', 'development'])
    def test_accepts_dev_aliases(self, raw):
        """'dev' 与 'dual_dev' 都接受，但都映射到同一个枚举值。"""
        deps = make_deps()
        result = SwitchMode(deps).execute(
            session=admin_session(deps), confirm=modal_token(), mode=raw,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        # 走的是切换流程（不是「无效模式」）
        assert result.reason != '无效的目标模式'

    def test_rejects_unknown_mode(self):
        deps = make_deps()
        result = SwitchMode(deps).execute(
            session=admin_session(deps), confirm=modal_token(), mode='zzz',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert result.reason == '无效的目标模式'

    def test_switch_does_not_require_second_confirmation(self):
        """★ 切换时用户只确认一次 —— 子用例不应再要一次令牌。

        若子用例重复要确认，UI 上表现为「确认后没反应」
        （第二个弹窗被上层忽略），是极度困惑的体验。
        """
        deps = make_deps(service=FakeService(states=running_states(
            'erp-prod', 'erp-arq', 'erp-redis', 'erp-redis-broker')))
        # 只给一次 MODAL 令牌，能走到「已有结果」即证明没有二次拦截
        result = SwitchMode(deps).execute(
            session=admin_session(deps), confirm=modal_token(), mode='prod',
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.reason not in ('缺少确认', '权限不足')


# ═══════════════════════════════════════════════════════════════════
# KillPort —— 端口清理
# ═══════════════════════════════════════════════════════════════════


class TestKillPort:
    def test_free_port_is_success_noop(self):
        deps = make_deps()
        result = KillPort(deps).execute(
            5002, session=admin_session(deps), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '空闲' in result.detail

    def test_invalid_port_rejected(self):
        deps = make_deps()
        for bad in (0, 65536, -1, 'abc'):
            result = KillPort(deps).execute(
                bad, session=admin_session(deps), confirm=modal_token(),
                event_bus=deps.event_bus, audit=deps.audit,
            )
            assert not result.ok
            assert result.reason == '端口非法'

    def test_kills_all_occupiers(self):
        proc = FakeProcess(port_pids={5002: [111, 222]},
                           names={111: 'python.exe', 222: 'node.exe'})
        deps = make_deps(process=proc)
        result = KillPort(deps).execute(
            5002, session=admin_session(deps), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert [c[1] for c in proc.calls if c[0] == 'kill_tree'] == [111, 222]
        assert 'python.exe' in result.detail

    def test_uses_narrow_filter_for_killing(self):
        """★ 用宽口径会杀掉所有连到这个端口的客户端进程。"""
        proc = FakeProcess(port_pids={5002: [111]}, port_pids_all={5002: [111, 999, 888]})
        deps = make_deps(process=proc)
        KillPort(deps).execute(
            5002, session=admin_session(deps), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        killed = [c[1] for c in proc.calls if c[0] == 'kill_tree']
        assert 999 not in killed and 888 not in killed

    def test_audit_written_before_kill(self):
        """★ 留痕必须在杀之前 —— 进程死后 PID 会被复用，「当时是谁」永久丢失。"""
        proc = FakeProcess(port_pids={5002: [111]}, names={111: 'python.exe'})
        deps = make_deps(process=proc)
        KillPort(deps).execute(
            5002, session=admin_session(deps), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        # 审计里记的是「即将终止」，且带进程名 → 证明是杀前写的
        assert deps.audit.entries
        assert '即将终止' in deps.audit.last.detail
        assert 'python.exe' in deps.audit.last.detail

    def test_recheck_catches_unreleased_port(self):
        """★ 旧实现杀完直接报成功，不复查 —— 端口没释放而界面说成功。"""
        proc = FakeProcess(port_pids={5002: [111]}, release_on_kill=False)
        deps = make_deps(process=proc)
        result = KillPort(deps).execute(
            5002, session=admin_session(deps), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert '仍被占用' in result.reason
        assert '111' in result.detail

    def test_recheck_retries_before_giving_up(self):
        proc = FakeProcess(port_pids={5002: [111]}, release_on_kill=False)
        deps = make_deps(process=proc)
        KillPort(deps).execute(
            5002, session=admin_session(deps), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert deps.clock.sleep_count > 0, '复查之间必须有等待'

    def test_zero_targeted_is_failure(self):
        """★ 「没找到可杀的目标」不是成功 —— 端口仍然被占。"""
        proc = FakeProcess(port_pids={5002: [111]})
        proc.kill_result = KillResult(targeted=0)
        deps = make_deps(process=proc)
        result = KillPort(deps).execute(
            5002, session=admin_session(deps), confirm=modal_token(),
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok

    def test_inspect_uses_wide_filter(self):
        """★ 只读巡查用宽口径（展示需要看到连接方），但绝不用于杀。"""
        proc = FakeProcess(port_pids={6379: [9]},
                           port_pids_all={6379: [7, 8, 9]})
        deps = make_deps(process=proc)
        infos = KillPort(deps).inspect(6379)
        assert {i.pid for i in infos} == {7, 8, 9}, \
            '宽口径应包含 LISTENING 的 9 与两个 ESTABLISHED 连接方'
        probes = [c[1] for c in proc.calls if c[0] == 'find_port_pids']
        assert all(listening_only is False for _, listening_only in probes)

    def test_kill_port_is_l2(self):
        assert Action.KILL_PORT.danger.name == 'L2'


# ═══════════════════════════════════════════════════════════════════
# Install / Uninstall
# ═══════════════════════════════════════════════════════════════════


class TestInstallServices:
    def test_already_installed_is_noop(self):
        deps = make_deps(service=FakeService(states=running_states('erp-prod', 'erp-arq')))
        result = InstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_INSTALL),
            confirm_target=CONFIRM_WORD_INSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '无需操作' in result.detail

    def test_unknown_state_aborts_conservatively(self):
        """★ 状态未知时安装可能覆盖既有配置 → 保守中止。"""
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.UNKNOWN}))
        result = InstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_INSTALL),
            confirm_target=CONFIRM_WORD_INSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert '保守中止' in result.reason

    def test_absent_services_report_not_implemented(self):
        """★ 需要服务规格（P4）→ 明确失败，不假装成功。"""
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.ABSENT,
                                                     'erp-arq': ServiceStatus.ABSENT}))
        result = InstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_INSTALL),
            confirm_target=CONFIRM_WORD_INSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert '未接入' in result.detail

    def test_wrong_confirm_word_rejected(self):
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.ABSENT}))
        result = InstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token('错词'),
            confirm_target=CONFIRM_WORD_INSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert result.reason == '缺少确认'

    def test_l3_requires_reason(self):
        """★ L3 必须填原因 —— 审计要能回答「为什么做这次变更」。"""
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.ABSENT}))
        token = ConfirmationToken(kind=ConfirmKind.TYPED,
                                  typed_name=CONFIRM_WORD_INSTALL, reason='   ')
        result = InstallServices(deps).execute(
            session=admin_session(deps), confirm=token,
            confirm_target=CONFIRM_WORD_INSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert '原因' in result.detail

    def test_operator_cannot_uninstall(self):
        """L3 操作需要 Admin。"""
        deps = make_deps(service=FakeService(states=running_states('erp-prod')))
        result = UninstallServices(deps).execute(
            session=admin_session(deps, Role.OPERATOR),
            confirm=typed_token(CONFIRM_WORD_UNINSTALL),
            confirm_target=CONFIRM_WORD_UNINSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert not result.ok
        assert result.reason == '权限不足'


class TestUninstallServices:
    def test_all_absent_is_noop(self):
        deps = make_deps(service=FakeService(states={'erp-prod': ServiceStatus.ABSENT,
                                                     'erp-arq': ServiceStatus.ABSENT}))
        result = UninstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_UNINSTALL),
            confirm_target=CONFIRM_WORD_UNINSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '无需卸载' in result.detail

    def test_stops_running_service_before_uninstall(self):
        """★ 正在运行的服务 NSSM 拒绝卸载 → 必须先停。"""
        svc = FakeService(states=running_states('erp-prod', 'erp-arq'))

        def state_after_uninstall(name):
            uninstalled = any(c[0] == 'control' and c[1][1] is ServiceCmd.UNINSTALL
                              for c in svc.calls)
            if uninstalled:
                return ServiceStatus.ABSENT
            return svc.states.get(name, ServiceStatus.STOPPED)

        svc.state = state_after_uninstall
        deps = make_deps(service=svc)
        result = UninstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_UNINSTALL),
            confirm_target=CONFIRM_WORD_UNINSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        verbs = [c[1][1] for c in svc.calls if c[0] == 'control']
        # 每个服务都是先 STOP 再 UNINSTALL
        assert verbs[:2] == [ServiceCmd.STOP, ServiceCmd.UNINSTALL]

    def test_uninstall_not_effective_is_failure(self):
        """★ 命令返回成功但状态没变 → 必须失败（可能需重启才彻底移除）。"""
        svc = FakeService(states=running_states('erp-prod'))
        deps = make_deps(service=svc)
        result = UninstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_UNINSTALL),
            confirm_target=CONFIRM_WORD_UNINSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
            names=('erp-prod',),
        )
        assert not result.ok
        assert '未生效' in result.detail
        assert '重启' in result.detail

    def test_uninstall_unknown_after_removal_is_failure(self):
        svc = FakeService(states=running_states('erp-prod'))
        svc.state = lambda name: ServiceStatus.UNKNOWN
        deps = make_deps(service=svc)
        result = UninstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_UNINSTALL),
            confirm_target=CONFIRM_WORD_UNINSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
            names=('erp-prod',),
        )
        assert not result.ok
        assert '状态未知' in result.reason or '状态未知' in result.detail

    def test_name_filter_limits_targets(self):
        svc = FakeService(states=running_states('erp-prod', 'erp-arq'))
        deps = make_deps(service=svc)
        UninstallServices(deps).execute(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_UNINSTALL),
            confirm_target=CONFIRM_WORD_UNINSTALL,
            event_bus=deps.event_bus, audit=deps.audit,
            names=('erp-prod',),
        )
        touched = {c[1][0] for c in svc.calls if c[0] == 'control'}
        assert touched == {'erp-prod'}


class TestRequiredConfirmation:
    """★ 确认提示由后端提供 —— 前端硬编码文案会导致两边不一致。"""

    def test_l3_returns_typed_kind(self):
        info = required_confirmation(Action.UNINSTALL_SERVICE)
        assert info['kind'] == 'typed'
        assert info['word'] == CONFIRM_WORD_UNINSTALL
        assert info['requires_reason'] == 'true'
        assert info['word'] in info['hint']

    def test_l2_returns_modal_kind(self):
        info = required_confirmation(Action.KILL_PORT)
        assert info['kind'] == 'modal'
        assert info['requires_reason'] == 'false'

    def test_l0_returns_none_kind(self):
        info = required_confirmation(Action.VIEW_ALL)
        assert info['kind'] == 'none'


# ═══════════════════════════════════════════════════════════════════
# LogOps —— 审计查询与链校验
# ═══════════════════════════════════════════════════════════════════


class TestLogOps:
    def test_query_returns_count(self):
        deps = make_deps()
        result = LogOps(deps).query(
            session=admin_session(deps), event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '0 条' in result.detail

    def test_query_is_truncated_at_max_limit(self):
        """★ 超过上限时截断并**明确告知**，不静默丢数据。"""
        from server_manager_v8.application.usecases.log_ops import MAX_QUERY_LIMIT

        deps = make_deps()
        result = LogOps(deps).query(
            session=admin_session(deps), event_bus=deps.event_bus, audit=deps.audit,
            limit=MAX_QUERY_LIMIT * 10,
        )
        assert result.ok
        assert '截断' in result.detail

    def test_chain_ok_is_success(self):
        """★ 校验动作本身成功 → success（断链是「结论」不是「操作失败」）。"""
        deps = make_deps()
        result = LogOps(deps).verify_chain(
            session=admin_session(deps), event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '完整' in result.detail

    def test_broken_chain_still_success_with_location(self):
        """★ 断链必须说清断在第几条（只说「断了」运维无从下手）。"""
        from server_manager_v8.domain.results import ChainVerifyResult

        deps = make_deps()
        deps.audit.verify_chain = lambda: ChainVerifyResult(
            ok=False, total=10, broken_at=4, reason='第 4 条 hash 不匹配')
        result = LogOps(deps).verify_chain(
            session=admin_session(deps), event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '4' in result.detail
        assert 'hash 不匹配' in result.detail

    def test_viewer_can_query(self):
        deps = make_deps()
        result = LogOps(deps).query(
            session=Session(clock=deps.clock), event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok, '查询是 L0，只读用户应当可以看'


# ═══════════════════════════════════════════════════════════════════
# AlertOps —— 告警确认 / 静默
# ═══════════════════════════════════════════════════════════════════


class TestAlertLifecycle:
    def test_raise_registers_and_emits(self):
        deps = make_deps()
        events = []
        deps.event_bus.subscribe(__import__(
            'server_manager_v8.application.events', fromlist=['AlertRaised'],
        ).AlertRaised, events.append)
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, '标题', '正文')
        assert 'k' in ops.alerts
        assert len(events) == 1
        assert events[0].alert_id == 'k'

    def test_same_key_does_not_duplicate(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P1, 'T1')
        ops.raise_alert('k', Severity.P0, 'T2')
        assert len(ops.alerts) == 1
        assert ops.alerts['k'].severity is Severity.P0

    def test_re_raise_clears_ack(self):
        """★ 已确认的告警再次触发 = 问题复发 → 必须重新变成未确认。"""
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P1, 'T')
        ops.ack('k', session=admin_session(deps))
        assert ops.alerts['k'].is_acked
        ops.raise_alert('k', Severity.P1, 'T')
        assert not ops.alerts['k'].is_acked

    def test_resolve_removes(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P1, 'T')
        result = ops.resolve_alert('k')
        assert result.ok
        assert not ops.alerts

    def test_resolve_unknown_key_is_success(self):
        """解决一个不存在的告警不是错误（幂等）。"""
        deps = make_deps()
        result = AlertOps(deps).resolve_alert('nope')
        assert result.ok


class TestAlertAck:
    def test_ack_marks_and_stops_notify(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        ops.ack('k', session=admin_session(deps))
        assert not ops.alerts['k'].should_notify(deps.clock.monotonic())

    def test_ack_twice_is_idempotent(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        ops.ack('k', session=admin_session(deps))
        first = ops.alerts['k'].acked_by
        result = ops.ack('k', session=admin_session(deps))
        assert result.ok
        assert '无需重复' in result.detail
        assert ops.alerts['k'].acked_by == first

    def test_ack_unknown_key_fails(self):
        deps = make_deps()
        result = AlertOps(deps).ack('nope', session=admin_session(deps))
        assert not result.ok
        assert result.reason == '告警不存在'

    def test_viewer_can_ack(self):
        """确认是 L0（只是标记「我看到了」，无副作用）。"""
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        result = ops.ack('k', session=Session(clock=deps.clock))
        assert result.ok


class TestAlertSilence:
    def test_silence_suppresses_notification(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        ops.silence('k', session=admin_session(deps), duration_s=60)
        assert not ops.alerts['k'].should_notify(deps.clock.monotonic())

    def test_silence_expires(self):
        """★ 静默必须有期限 —— 无限期静默等于永久关闭告警。"""
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        ops.silence('k', session=admin_session(deps), duration_s=60)
        deps.clock.advance(61)
        assert ops.alerts['k'].should_notify(deps.clock.monotonic())

    def test_silence_beyond_max_is_rejected(self):
        """★ 超上限**拒绝**而不是静默截断（截断会让用户误判真实期限）。"""
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        result = ops.silence('k', session=admin_session(deps),
                             duration_s=MAX_SILENCE_S * 2)
        assert not result.ok
        assert result.reason == '静默时长超出上限'
        assert ops.alerts['k'].silenced_until is None

    @pytest.mark.parametrize('bad', [0, -1, -100])
    def test_non_positive_silence_rejected(self, bad):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        result = ops.silence('k', session=admin_session(deps), duration_s=bad)
        assert not result.ok
        assert result.reason == '静默时长非法'

    def test_viewer_cannot_silence(self):
        """★ 静默是 L1 而非 L0 —— 它会让系统停止提醒真实故障。"""
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        result = ops.silence('k', session=Session(clock=deps.clock))
        assert not result.ok
        assert result.reason == '权限不足'

    def test_operator_can_silence(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('k', Severity.P0, 'T')
        result = ops.silence('k', session=admin_session(deps, Role.OPERATOR))
        assert result.ok


class TestAlertList:
    def test_empty_list(self):
        deps = make_deps()
        result = AlertOps(deps).list_active(session=admin_session(deps))
        assert result.ok
        assert '无告警' in result.detail

    def test_counts_paging_alerts(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('a', Severity.P0, 'T')
        ops.raise_alert('b', Severity.P3, 'T')
        result = ops.list_active(session=admin_session(deps))
        assert '2 条' in result.detail
        assert '1 条需立即介入' in result.detail

    def test_notify_only_filters_acked_and_silenced(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('a', Severity.P0, 'T')
        ops.raise_alert('b', Severity.P0, 'T')
        ops.ack('a', session=admin_session(deps))
        ops.silence('b', session=admin_session(deps), duration_s=60)
        ops.list_active(session=admin_session(deps), notify_only=True)
        assert ops.last_list == ()

    def test_notify_only_keeps_fresh_alerts(self):
        deps = make_deps()
        ops = AlertOps(deps)
        ops.raise_alert('a', Severity.P0, 'T')
        ops.list_active(session=admin_session(deps), notify_only=True)
        assert len(ops.last_list) == 1

    def test_viewer_can_list(self):
        deps = make_deps()
        result = AlertOps(deps).list_active(session=Session(clock=deps.clock))
        assert result.ok


# ═══════════════════════════════════════════════════════════════════
# ConfigOps —— 配置读写
# ═══════════════════════════════════════════════════════════════════


class TestConfigOpsLoad:
    def test_first_run_uses_defaults(self):
        deps = make_deps(storage=FakeStorage())
        result = ConfigOps(deps).load(
            session=admin_session(deps), event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '默认配置' in result.detail

    def test_missing_storage_gives_defaults_not_crash(self):
        """★ 无存储时明确告知，不静默给空配置。"""
        deps = make_deps(storage=None)
        result = ConfigOps(deps).load(
            session=admin_session(deps), event_bus=deps.event_bus, audit=deps.audit,
        )
        assert result.ok
        assert '默认配置' in result.detail

    def test_viewer_can_load(self):
        deps = make_deps()
        result = ConfigOps(deps).load(session=Session(clock=deps.clock))
        assert result.ok


class TestConfigOpsPorts:
    SDEFAULTS = {'api_port': 5002, 'web_port': 3000, 'redis_port': 6379}

    def test_save_single_port(self):
        deps = make_deps(storage=FakeStorage(data=dict(self.SDEFAULTS)))
        result = ConfigOps(deps).save_ports(
            session=admin_session(deps), confirm=modal_token(),
            ports={'api_port': 5003},
        )
        assert result.ok
        assert deps.storage.data['api_port'] == 5003
        assert deps.storage.data['web_port'] == 3000, '其他端口不该被改动'

    def test_all_three_same_port_rejected(self):
        """★ 端口互斥校验在领域层（`is_valid_port` + 冲突检查）。"""
        deps = make_deps(storage=FakeStorage(data=dict(self.SDEFAULTS)))
        result = ConfigOps(deps).save_ports(
            session=admin_session(deps), confirm=modal_token(),
            ports={'api_port': 3000},
        )
        assert not result.ok
        assert result.reason == '端口冲突'

    @pytest.mark.parametrize('bad', [0, 65536, -1, 'abc', None, True])
    def test_invalid_port_rejected(self, bad):
        """★ `True` 也要被拒 —— bool 是 int 子类，易被漏过。"""
        deps = make_deps(storage=FakeStorage(data=dict(self.SDEFAULTS)))
        result = ConfigOps(deps).save_ports(
            session=admin_session(deps), confirm=modal_token(),
            ports={'api_port': bad},
        )
        assert not result.ok
        assert result.reason == '端口值非法'

    def test_unknown_key_rejected(self):
        """★ 白名单：不在允许列表里的键一律拒绝写入。"""
        deps = make_deps(storage=FakeStorage(data=dict(self.SDEFAULTS)))
        result = ConfigOps(deps).save_ports(
            session=admin_session(deps), confirm=modal_token(),
            ports={'hack': 1234},
        )
        assert not result.ok
        assert '不可写' in result.reason

    def test_nothing_written_when_validation_fails(self):
        """★ 校验失败时一个字节都不能写（避免「一半新一半旧」）。"""
        deps = make_deps(storage=FakeStorage(data=dict(self.SDEFAULTS)))
        snapshot = dict(deps.storage.data)
        ConfigOps(deps).save_ports(
            session=admin_session(deps), confirm=modal_token(),
            ports={'api_port': 5003, 'web_port': 99999},
        )
        assert deps.storage.data == snapshot

    def test_empty_ports_rejected(self):
        deps = make_deps(storage=FakeStorage(data=dict(self.SDEFAULTS)))
        result = ConfigOps(deps).save_ports(
            session=admin_session(deps), confirm=modal_token(), ports={},
        )
        assert not result.ok

    def test_requires_modal(self):
        deps = make_deps(storage=FakeStorage(data=dict(self.SDEFAULTS)))
        result = ConfigOps(deps).save_ports(
            session=admin_session(deps), ports={'api_port': 5003},
        )
        assert not result.ok
        assert result.reason == '缺少确认'


class TestConfigOpsPaths:
    def test_save_strips_whitespace(self):
        deps = make_deps(storage=FakeStorage(data={}))
        result = ConfigOps(deps).save_paths(
            session=admin_session(deps), confirm=modal_token(),
            paths={'nssm_path': '  C:/nssm.exe  '},
        )
        assert result.ok
        assert deps.storage.data['nssm_path'] == 'C:/nssm.exe'

    def test_non_string_rejected(self):
        deps = make_deps(storage=FakeStorage(data={}))
        result = ConfigOps(deps).save_paths(
            session=admin_session(deps), confirm=modal_token(),
            paths={'nssm_path': 123},
        )
        assert not result.ok
        assert result.reason == '路径值非法'


class TestConfigOpsScalars:
    def test_save_positive_int(self):
        deps = make_deps(storage=FakeStorage(data={}))
        result = ConfigOps(deps).save_scalars(
            session=admin_session(deps), confirm=modal_token(),
            values={'max_log_lines': 5000},
        )
        assert result.ok

    @pytest.mark.parametrize('bad', [0, -5, True, 'many', 3.5])
    def test_bad_numbers_rejected(self, bad):
        deps = make_deps(storage=FakeStorage(data={}))
        result = ConfigOps(deps).save_scalars(
            session=admin_session(deps), confirm=modal_token(),
            values={'max_log_lines': bad},
        )
        assert not result.ok
        assert result.reason == '配置值非法'

    def test_empty_list_rejected(self):
        """★ 空列表 = 「不再托管任何 Redis 服务」，几乎不可能是用户本意。"""
        deps = make_deps(storage=FakeStorage(data={}))
        result = ConfigOps(deps).save_scalars(
            session=admin_session(deps), confirm=modal_token(),
            values={'redis_services': []},
        )
        assert not result.ok

    def test_list_with_empty_string_rejected(self):
        deps = make_deps(storage=FakeStorage(data={}))
        result = ConfigOps(deps).save_scalars(
            session=admin_session(deps), confirm=modal_token(),
            values={'redis_services': ['ok', '']},
        )
        assert not result.ok


class TestConfigOpsReset:
    def test_reset_needs_typed_confirmation(self):
        deps = make_deps(storage=FakeStorage(data={'api_port': 5003}))
        result = ConfigOps(deps).reset(
            session=admin_session(deps), confirm=modal_token(),
            confirm_target=CONFIRM_WORD_RESET,
        )
        assert not result.ok
        assert result.reason == '缺少确认'

    def test_reset_backs_up_first(self):
        """★ 重置前必须快照 —— 用户很可能只是想改回端口。"""
        storage = FakeStorage(data={'api_port': 5003})
        backups: list[str] = []
        original = storage.backup

        def track(suffix: str = '.bak') -> OpResult:
            backups.append(suffix)
            return original(suffix)

        storage.backup = track
        deps = make_deps(storage=storage)
        result = ConfigOps(deps).reset(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_RESET),
            confirm_target=CONFIRM_WORD_RESET,
        )
        assert result.ok
        assert '.prereset' in backups

    def test_reset_aborts_if_backup_fails(self):
        """★ 快照失败则不重置（宁可不动也不丢数据）。"""
        class BrokenStorage(FakeStorage):
            def backup(self, suffix: str = '.bak') -> OpResult:
                return OpResult.failure('磁盘满')

        deps = make_deps(storage=BrokenStorage(data={'api_port': 5003}))
        result = ConfigOps(deps).reset(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_RESET),
            confirm_target=CONFIRM_WORD_RESET,
        )
        assert not result.ok
        assert '已中止' in result.reason
        assert deps.storage.data['api_port'] == 5003, '配置不该被改动'


# ═══════════════════════════════════════════════════════════════════
# BackupOps —— 备份与恢复
# ═══════════════════════════════════════════════════════════════════


class TestBackupOps:
    def test_backup_succeeds_and_checks_chain(self):
        """★ 备份时顺带校验链 —— 用户已在「固化当前状态」的心理动作里。"""
        deps = make_deps(storage=FakeStorage(data={'api_port': 5002}))
        result = BackupOps(deps).run_backup(
            session=admin_session(deps), confirm=modal_token(),
        )
        assert result.ok
        assert '审计链完整' in result.detail

    def test_broken_chain_does_not_fail_backup(self):
        """★ 链断不是备份失败 —— 备份的是当前事实，事实包含「链断了」。"""
        from server_manager_v8.domain.results import ChainVerifyResult

        deps = make_deps(storage=FakeStorage(data={}))
        deps.audit.verify_chain = lambda: ChainVerifyResult(
            ok=False, total=5, broken_at=2, reason='hash 不匹配')
        result = BackupOps(deps).run_backup(
            session=admin_session(deps), confirm=modal_token(),
        )
        assert result.ok
        assert '断裂' in result.detail

    def test_chain_check_can_be_skipped(self):
        deps = make_deps(storage=FakeStorage(data={}))
        result = BackupOps(deps).run_backup(
            session=admin_session(deps), confirm=modal_token(),
            include_chain_check=False,
        )
        assert result.ok
        assert '审计链' not in result.detail

    def test_backup_without_storage_fails_explicitly(self):
        deps = make_deps(storage=None)
        result = BackupOps(deps).run_backup(
            session=admin_session(deps), confirm=modal_token(),
        )
        assert not result.ok
        assert '不可用' in result.reason

    def test_restore_requires_typed_token(self):
        deps = make_deps(storage=FakeStorage(data={'api_port': 5002}))
        result = BackupOps(deps).restore_backup(
            session=admin_session(deps), confirm=modal_token(),
            confirm_target=CONFIRM_WORD_RESTORE,
        )
        assert not result.ok
        assert result.reason == '缺少确认'

    def test_restore_snapshots_current_first(self):
        """★ 恢复前必须先备份当前 —— 用户可能选错文件。"""
        storage = FakeStorage(data={'api_port': 5002})
        suffixes: list[str] = []
        original = storage.backup

        def track(suffix: str = '.bak') -> OpResult:
            suffixes.append(suffix)
            return original(suffix)

        storage.backup = track
        deps = make_deps(storage=storage)
        result = BackupOps(deps).restore_backup(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_RESTORE),
            confirm_target=CONFIRM_WORD_RESTORE,
        )
        assert result.ok
        assert PRERESTORE_SUFFIX in suffixes

    def test_restore_aborts_if_snapshot_fails(self):
        """★ 前置快照失败 → 不恢复（否则误选备份就永久覆盖了）。"""
        class BrokenStorage(FakeStorage):
            def backup(self, suffix: str = '.bak') -> OpResult:
                return OpResult.failure('磁盘满')

        deps = make_deps(storage=BrokenStorage(data={'api_port': 5002}))
        result = BackupOps(deps).restore_backup(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_RESTORE),
            confirm_target=CONFIRM_WORD_RESTORE,
        )
        assert not result.ok
        assert '已中止' in result.reason
        assert '无法回退' in result.detail

    def test_restore_empty_backup_fails(self):
        deps = make_deps(storage=FakeStorage(data={}))
        result = BackupOps(deps).restore_backup(
            session=admin_session(deps), confirm=typed_token(CONFIRM_WORD_RESTORE),
            confirm_target=CONFIRM_WORD_RESTORE,
        )
        assert not result.ok
        assert '未做任何修改' in result.detail or '未被修改' in result.detail

    def test_operator_cannot_restore(self):
        """恢复是 L3（不可逆覆盖）→ 需要 Admin。"""
        deps = make_deps(storage=FakeStorage(data={'api_port': 5002}))
        result = BackupOps(deps).restore_backup(
            session=admin_session(deps, Role.OPERATOR),
            confirm=typed_token(CONFIRM_WORD_RESTORE),
            confirm_target=CONFIRM_WORD_RESTORE,
        )
        assert not result.ok
        assert result.reason == '权限不足'


# ═══════════════════════════════════════════════════════════════════
# 跨用例的一致性
# ═══════════════════════════════════════════════════════════════════


class TestCrossCutting:
    def test_all_l3_usecases_need_typed_confirmation(self):
        """★ 所有 L3 操作必须能通过 tokens 被拦下 —— 防误点的统一性。"""
        for action in Action:
            if action.danger.name == 'L3':
                ok, _ = ConfirmationToken(kind=ConfirmKind.MODAL).satisfies(action.danger)
                assert not ok, f'{action.value} 是 L3，不该被 MODAL 令牌放行'

    def test_all_l2_usecases_need_modal(self):
        for action in Action:
            if action.danger.name == 'L2':
                ok, _ = ConfirmationToken().satisfies(action.danger)
                assert not ok, f'{action.value} 是 L2，不该无令牌放行'

    def test_every_usecase_rejects_viewer(self):
        """★ 除只读用例外的全部用例都必须拦下只读角色。"""
        readonly_ok = {Action.VIEW_ALL, Action.REFRESH, Action.EXPORT_LOGS,
                       Action.ACK_ALERT}
        for action in Action:
            if action in readonly_ok:
                continue
            denied, _ = Session(clock=FakeClock()).check(action).allowed, None
            assert not denied, f'{action.value} 不应对只读角色开放'

    def test_deps_accepts_all_fake_ports(self):
        """`make_deps()` 造出的组合必须满足 `Deps` 的类型契约。"""
        deps = make_deps()
        assert deps.clock is not None
        assert deps.service is not None
        assert deps.process is not None
        assert deps.health is not None
        assert deps.audit is not None
        assert deps.event_bus is not None

    def test_deps_optional_ports_default_to_none(self):
        """★ 可选 Port 的 `None` 必须能被用例识别为「功能不可用」。"""
        deps = Deps(
            clock=FakeClock(), service=FakeService(), process=FakeProcess(),
            health=__import__('tests.application.conftest', fromlist=['FakeHealth']).FakeHealth(),
            audit=FakeAudit(),
            event_bus=__import__('server_manager_v8.application.event_bus',
                                 fromlist=['EventBus']).EventBus(),
        )
        assert deps.metrics is None
        assert deps.notify is None
        assert deps.storage is None
        assert deps.actor == 'local'
