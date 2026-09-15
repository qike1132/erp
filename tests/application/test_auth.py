"""权限矩阵与会话的单测。

重点覆盖：
    1. ★ 默认拒绝（新增 Action 忘登记 → 任何角色都不能用，fail-closed）
    2. 三级角色的授权边界（方案 §2.5 的角色表）
    3. JIT 提权的滑动过期与**立即降权不可逆**
    4. 高危确认流程（L3 的名称输入与强制原因）
"""

from __future__ import annotations

import pytest

from server_manager_v8.application.auth.guard import (
    ConfirmKind,
    ConfirmationToken,
    check_permission,
    require,
)
from server_manager_v8.application.auth.session import Session
from server_manager_v8.domain.permissions import (
    Action,
    DangerLevel,
    Role,
    actions_for,
    check,
    danger_actions_at,
    is_allowed,
    required_role,
)
from server_manager_v8.domain.results import OpResult
from tests.application.conftest import FakeAudit, FakeClock


# ═══════════════════════════════════════════════════════════════════
# 权限矩阵
# ═══════════════════════════════════════════════════════════════════


class TestDangerLevels:
    def test_all_actions_have_a_level(self):
        """★ 每个 Action 都必须被登记到某个高危等级。

        没登记的话 `danger` 会保守返回 L3 —— 那是安全网，
        但说明有人加了操作忘了分级，应当补登。
        """
        from server_manager_v8.domain.permissions import DANGER_MATRIX

        registered = set()
        for actions in DANGER_MATRIX.values():
            registered |= actions
        for action in Action:
            assert action in registered, f'{action.value} 未登记高危等级'

    def test_levels_match_spec(self):
        """方案 §2.5 的管控矩阵逐条核对。"""
        assert danger_actions_at(DangerLevel.L0) == (
            Action.VIEW_ALL, Action.REFRESH, Action.EXPORT_LOGS, Action.ACK_ALERT,
        )
        assert Action.RESTART_SERVICE.danger is DangerLevel.L1
        assert Action.CLEAR_LOGS.danger is DangerLevel.L1
        assert Action.SILENCE_ALERT.danger is DangerLevel.L1
        assert Action.STOP_PROD_SERVICE.danger is DangerLevel.L2
        assert Action.KILL_PORT.danger is DangerLevel.L2
        assert Action.SWITCH_MODE.danger is DangerLevel.L2
        assert Action.UNINSTALL_SERVICE.danger is DangerLevel.L3
        assert Action.RESTORE_BACKUP.danger is DangerLevel.L3
        assert Action.MANAGE_ROLES.danger is DangerLevel.L3

    def test_only_l3_requires_reason_and_typed(self):
        assert DangerLevel.L3.requires_reason is True
        assert DangerLevel.L3.requires_typed_confirmation is True
        assert DangerLevel.L2.requires_reason is False
        assert DangerLevel.L2.requires_modal_confirm is True
        assert DangerLevel.L1.supports_undo is True
        assert DangerLevel.L2.supports_undo is False, 'L2 不该给「可撤销」的错觉'

    def test_labels_are_chinese(self):
        assert DangerLevel.L3.label == '极高危'
        assert Role.VIEWER.label == '只读'


class TestRoleGrants:
    def test_viewer_can_only_read(self):
        """Viewer 只能做 L0 —— 任何启停、配置写入都不行。"""
        for action in danger_actions_at(DangerLevel.L0):
            assert is_allowed(Role.VIEWER, action)
        for action in Action:
            if action.danger is not DangerLevel.L0:
                assert not is_allowed(Role.VIEWER, action), (
                    f'Viewer 不该能做 {action.value}（{action.danger.label}）'
                )

    def test_operator_can_do_l0_l1_l2(self):
        for level in (DangerLevel.L0, DangerLevel.L1, DangerLevel.L2):
            for action in danger_actions_at(level):
                assert is_allowed(Role.OPERATOR, action), (
                    f'Operator 应当能做 {action.value}'
                )

    def test_operator_cannot_do_l3(self):
        """★ Operator 不能卸载服务 / 恢复备份 —— 方案明确的边界。"""
        for action in danger_actions_at(DangerLevel.L3):
            assert not is_allowed(Role.OPERATOR, action), (
                f'Operator 不该能做 {action.value}'
            )

    def test_admin_can_do_everything(self):
        for action in Action:
            assert is_allowed(Role.ADMIN, action)

    def test_required_role_matches(self):
        assert required_role(Action.VIEW_ALL) is Role.VIEWER
        assert required_role(Action.RESTART_SERVICE) is Role.OPERATOR
        assert required_role(Action.UNINSTALL_SERVICE) is Role.ADMIN

    def test_actions_for_role_is_consistent_with_is_allowed(self):
        for role in Role:
            listed = set(actions_for(role))
            for action in Action:
                assert (action in listed) == is_allowed(role, action)

    def test_role_ordering(self):
        assert Role.ADMIN.at_least(Role.OPERATOR)
        assert Role.OPERATOR.at_least(Role.VIEWER)
        assert not Role.VIEWER.at_least(Role.OPERATOR)


class TestDefaultDeny:
    def test_unknown_role_gets_nothing(self):
        """★ 默认拒绝：不在授权表里的角色拿不到任何权限。"""

        class FakeRole:
            value = 'unknown'
            level = 99

        assert is_allowed(FakeRole(), Action.VIEW_ALL) is False  # type: ignore[arg-type]

    def test_unregistered_action_falls_back_to_l3(self):
        """★ 未登记等级的操作按 L3 保守处理。

        这比「按 L0 处理」安全：新增操作忘了登记，至少不会因为
        「以为是低危」而被 Viewer 随意执行。
        """
        from server_manager_v8.domain.permissions import DANGER_MATRIX

        # 构造一个「不在矩阵里」的动作：临时移除一个
        saved = DANGER_MATRIX[DangerLevel.L0]
        try:
            DANGER_MATRIX[DangerLevel.L0] = frozenset(
                a for a in saved if a is not Action.ACK_ALERT
            )
            assert Action.ACK_ALERT.danger is DangerLevel.L3
        finally:
            DANGER_MATRIX[DangerLevel.L0] = saved

    def test_check_returns_reason_on_denial(self):
        verdict = check(Role.VIEWER, Action.KILL_PORT)
        assert verdict.allowed is False
        assert verdict.reason
        assert 'operator' in verdict.reason

    def test_check_message_is_user_friendly(self):
        verdict = check(Role.VIEWER, Action.UNINSTALL_SERVICE)
        assert '管理员' in verdict.message
        assert '只读' in verdict.message

    def test_check_requires_reason(self):
        """PermissionCheck 被拒时必须带 reason（禁止空拒绝）。"""
        from server_manager_v8.domain.permissions import PermissionCheck

        with pytest.raises(ValueError, match='reason'):
            PermissionCheck(allowed=False, role=Role.VIEWER, action=Action.KILL_PORT)


# ═══════════════════════════════════════════════════════════════════
# 会话与 JIT 提权
# ═══════════════════════════════════════════════════════════════════


class TestSession:
    def test_starts_as_default_role(self):
        s = Session(clock=FakeClock())
        assert s.role is Role.VIEWER
        assert s.is_elevated is False

    def test_elevate_grants_and_sets_expiry(self):
        clock = FakeClock()
        s = Session(clock=clock, elevate_ttl_s=1800)
        s.elevate(Role.OPERATOR)
        assert s.role is Role.OPERATOR
        assert s.is_elevated is True
        assert s.expires_at == 1800.0

    def test_expires_after_ttl(self):
        clock = FakeClock()
        s = Session(clock=clock, elevate_ttl_s=1800)
        s.elevate(Role.ADMIN)
        clock.advance(1799)
        assert s.role is Role.ADMIN, '未到期不能掉权限'
        clock.advance(2)
        assert s.role is Role.VIEWER, '到期必须自动回收'

    def test_sliding_expiry(self):
        """★ 滑动过期：持续操作期间权限不掉。"""
        clock = FakeClock()
        s = Session(clock=clock, elevate_ttl_s=100)
        s.elevate(Role.OPERATOR)
        for _ in range(5):
            clock.advance(90)      # 每次都在过期前
            s.touch()
        assert s.role is Role.OPERATOR, '持续 touch 应当保持权限'
        assert s.remaining_s == 100.0

    def test_demote_is_immediate_and_irreversible(self):
        """★ 降权必须立即生效，且不能因为后续 touch 而复活。

        这是本模块最重要的一条安全性质：只清 role 不清 expires_at 的话，
        一次 touch 就会把权限续回来 —— 用户点了「立即降权」却仍有权限。
        """
        clock = FakeClock()
        s = Session(clock=clock, elevate_ttl_s=1800)
        s.elevate(Role.ADMIN)
        s.demote()

        assert s.role is Role.VIEWER
        assert s.expires_at is None
        assert s.is_elevated is False

        # 关键：touch 不能把权限续回来
        s.touch()
        assert s.role is Role.VIEWER, '降权后一次 touch 又拿到权限 = 权限漏洞'
        assert s.expires_at is None

    def test_touch_on_default_role_does_nothing(self):
        s = Session(clock=FakeClock(), elevate_ttl_s=100)
        s.touch()
        assert s.expires_at is None
        assert s.role is Role.VIEWER

    def test_remaining_seconds(self):
        clock = FakeClock()
        s = Session(clock=clock, elevate_ttl_s=600)
        s.elevate(Role.OPERATOR)
        clock.advance(200)
        assert s.remaining_s == 400.0

    def test_remaining_zero_when_not_elevated(self):
        assert Session(clock=FakeClock()).remaining_s == 0.0

    def test_rejects_non_positive_ttl(self):
        with pytest.raises(ValueError, match='正数'):
            Session(clock=FakeClock(), elevate_ttl_s=0)
        with pytest.raises(ValueError, match='正数'):
            Session(clock=FakeClock(), elevate_ttl_s=-5)

    def test_can_and_check(self):
        s = Session(clock=FakeClock())
        assert s.can(Action.VIEW_ALL) is True
        assert s.can(Action.KILL_PORT) is False
        s.elevate(Role.OPERATOR)
        assert s.can(Action.KILL_PORT) is True

    def test_emits_auth_changed(self):
        clock = FakeClock()
        events: list = []
        s = Session(clock=clock, emit=events.append)
        s.elevate(Role.ADMIN)
        assert len(events) == 1
        assert events[0].role == 'admin'

    def test_emit_failure_does_not_break_elevation(self):
        def broken(event):
            raise RuntimeError('总线炸了')

        s = Session(clock=FakeClock(), emit=broken)
        s.elevate(Role.ADMIN)
        assert s.role is Role.ADMIN


# ═══════════════════════════════════════════════════════════════════
# 确认令牌
# ═══════════════════════════════════════════════════════════════════


class TestConfirmationToken:
    def test_l0_and_l1_need_no_confirmation(self):
        token = ConfirmationToken()
        assert token.satisfies(DangerLevel.L0)[0] is True
        assert token.satisfies(DangerLevel.L1)[0] is True

    def test_l2_needs_modal(self):
        assert ConfirmationToken().satisfies(DangerLevel.L2)[0] is False
        assert ConfirmationToken(kind=ConfirmKind.MODAL).satisfies(DangerLevel.L2)[0] is True

    def test_l3_needs_typed_and_reason(self):
        # 只给了 kind，没给名称与原因
        ok, why = ConfirmationToken(kind=ConfirmKind.TYPED).satisfies(DangerLevel.L3)
        assert ok is False
        assert '原因' in why

        ok, _ = ConfirmationToken(
            kind=ConfirmKind.TYPED, reason='迁移到新机器',
        ).satisfies(DangerLevel.L3)
        assert ok is True

    def test_l3_typed_name_must_match_target(self):
        """★ 名称不匹配必须拒绝 —— 这是防误点的核心机制。"""
        token = ConfirmationToken(
            kind=ConfirmKind.TYPED, typed_name='erp-arq', reason='x',
        )
        ok, why = token.satisfies(DangerLevel.L3, target='erp-prod')
        assert ok is False
        assert '不匹配' in why

        right = ConfirmationToken(
            kind=ConfirmKind.TYPED, typed_name='erp-prod', reason='x',
        )
        assert right.satisfies(DangerLevel.L3, target='erp-prod')[0] is True

    def test_l3_blank_reason_rejected(self):
        ok, why = ConfirmationToken(
            kind=ConfirmKind.TYPED, typed_name='erp-prod', reason='   ',
        ).satisfies(DangerLevel.L3, target='erp-prod')
        assert ok is False
        assert '原因' in why

    def test_l2_token_does_not_satisfy_l3(self):
        ok, why = ConfirmationToken(kind=ConfirmKind.MODAL).satisfies(DangerLevel.L3)
        assert ok is False
        assert '极高危' in why, '提示用中文标签（给用户看），而非 L3 这种内部代号'


# ═══════════════════════════════════════════════════════════════════
# @require 装饰器
# ═══════════════════════════════════════════════════════════════════


class FakeUseCase:
    """用 @require 保护的假用例。"""

    def __init__(self):
        self.ran = 0

    @require(Action.KILL_PORT, target_arg='port')
    def kill_port(self, port, *, session, confirm=None, event_bus=None,
                  audit=None) -> OpResult:
        self.ran += 1
        return OpResult.success(f'已释放端口 {port}')

    @require(Action.UNINSTALL_SERVICE, target_arg='service')
    def uninstall(self, service, *, session, confirm=None, event_bus=None,
                  audit=None) -> OpResult:
        self.ran += 1
        return OpResult.success(f'已卸载 {service}')

    @require(Action.VIEW_ALL)
    def view(self, *, session, confirm=None, event_bus=None, audit=None) -> OpResult:
        self.ran += 1
        return OpResult.success('ok')


class TestRequireDecorator:
    def test_denies_insufficient_role(self):
        uc = FakeUseCase()
        s = Session(clock=FakeClock())  # Viewer
        result = uc.kill_port(3000, session=s)
        assert result.ok is False
        assert result.reason == '权限不足'
        assert uc.ran == 0, '被拒时函数体绝不能执行'

    def test_allows_sufficient_role(self):
        uc = FakeUseCase()
        s = Session(clock=FakeClock())
        s.elevate(Role.OPERATOR)
        result = uc.kill_port(3000, session=s,
                              confirm=ConfirmationToken(kind=ConfirmKind.MODAL))
        assert result.ok is True
        assert uc.ran == 1

    def test_l2_without_confirm_is_denied(self):
        """★ L2 操作没有二次确认必须被拒 —— 校验在服务端做，不信前端。"""
        uc = FakeUseCase()
        s = Session(clock=FakeClock())
        s.elevate(Role.OPERATOR)
        result = uc.kill_port(3000, session=s)
        assert result.ok is False
        assert result.reason == '缺少确认'
        assert uc.ran == 0

    def test_l3_requires_typed_name(self):
        uc = FakeUseCase()
        s = Session(clock=FakeClock())
        s.elevate(Role.ADMIN)

        bad = uc.uninstall('erp-prod', session=s,
                           confirm=ConfirmationToken(kind=ConfirmKind.MODAL))
        assert bad.ok is False
        assert uc.ran == 0

        good = uc.uninstall('erp-prod', session=s, confirm=ConfirmationToken(
            kind=ConfirmKind.TYPED, typed_name='erp-prod', reason='服务下线',
        ))
        assert good.ok is True
        assert uc.ran == 1

    def test_viewer_can_do_l0_without_confirm(self):
        uc = FakeUseCase()
        assert uc.view(session=Session(clock=FakeClock())).ok is True

    def test_denial_emits_event_and_audits(self):
        """★ 被拒必须留痕（4A 要求「谁在什么权限下被拦」）。"""
        uc = FakeUseCase()
        s = Session(clock=FakeClock())
        bus_events: list = []

        class Bus:
            def emit(self, e):
                bus_events.append(e)

        audit = FakeAudit()
        uc.kill_port(3000, session=s, event_bus=Bus(), audit=audit)

        assert len(bus_events) == 1
        assert type(bus_events[0]).__name__ == 'OperationDenied'
        assert audit.actions == [Action.KILL_PORT.value]

    def test_audit_failure_does_not_break_denial(self):
        uc = FakeUseCase()
        audit = FakeAudit(fail_on_record=True)
        result = uc.kill_port(3000, session=Session(clock=FakeClock()), audit=audit)
        assert result.ok is False  # 仍然正常拒绝

    def test_missing_session_is_a_programming_error(self):
        """漏传 session 属编程错误 —— 必须抛（不能静默放行）。

        静默放行会变成「一个越权入口」：忘了传 session 就能绕过权限检查。
        """
        uc = FakeUseCase()
        with pytest.raises(Exception):
            uc.view()

    def test_successful_call_touches_session(self):
        """成功执行后滑动续期。"""
        clock = FakeClock()
        s = Session(clock=clock, elevate_ttl_s=100)
        s.elevate(Role.OPERATOR)
        clock.advance(90)

        uc = FakeUseCase()
        uc.kill_port(3000, session=s, confirm=ConfirmationToken(kind=ConfirmKind.MODAL))
        assert s.remaining_s == 100.0, '成功后应当续期'

    def test_decorator_preserves_signature_metadata(self):
        assert FakeUseCase.kill_port.__required_action__ is Action.KILL_PORT  # type: ignore[attr-defined]
        assert FakeUseCase.uninstall.__danger_level__ is DangerLevel.L3  # type: ignore[attr-defined]


class TestCheckPermissionHelper:
    def test_returns_none_when_allowed(self):
        s = Session(clock=FakeClock())
        assert check_permission(s, Action.VIEW_ALL) is None

    def test_returns_failure_when_denied(self):
        s = Session(clock=FakeClock())
        result = check_permission(s, Action.KILL_PORT)
        assert result is not None
        assert result.ok is False

    def test_checks_confirmation_too(self):
        s = Session(clock=FakeClock())
        s.elevate(Role.OPERATOR)
        result = check_permission(s, Action.KILL_PORT)
        assert result is not None
        assert result.reason == '缺少确认'
