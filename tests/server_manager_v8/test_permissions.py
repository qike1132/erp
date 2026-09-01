"""权限与高危管控测试：授权矩阵、JIT 提权 TTL、L3 原因强校验。"""
from __future__ import annotations

import pytest

from server_manager_v8.domain import (
    Action,
    AuthPolicy,
    DangerLevel,
    Role,
    Session,
)

NOW = 1000.0


class TestPermissionMatrix:
    def test_viewer_readonly(self) -> None:
        s = Session(base_role=Role.VIEWER)
        p = AuthPolicy()
        assert p.authorize(s, Action.VIEW, NOW).allowed
        assert p.authorize(s, Action.EXPORT_LOGS, NOW).allowed
        assert p.authorize(s, Action.ACK_ALERT, NOW).allowed
        assert not p.authorize(s, Action.STOP_SERVICE, NOW).allowed
        assert not p.authorize(s, Action.EDIT_PERMISSIONS, NOW).allowed

    def test_operator_runtime_actions(self) -> None:
        s = Session(base_role=Role.OPERATOR)
        p = AuthPolicy()
        for a in (Action.START_SERVICE, Action.RESTART_SERVICE, Action.STOP_SERVICE,
                  Action.KILL_PORT, Action.SWITCH_MODE, Action.SILENCE_ALERT,
                  Action.RUN_BACKUP, Action.CLEAR_LOGS):
            assert p.authorize(s, a, NOW).allowed, a
        for a in (Action.UNINSTALL_SERVICES, Action.RESTORE_BACKUP,
                  Action.EDIT_PERMISSIONS, Action.EDIT_CONFIG, Action.INSTALL_SERVICES):
            assert not p.authorize(s, a, NOW).allowed, a

    def test_admin_full(self) -> None:
        s = Session(base_role=Role.ADMIN)
        p = AuthPolicy()
        for a in Action:
            assert p.authorize(s, a, NOW).allowed, a

    def test_danger_mapping_matches_plan(self) -> None:
        """L2/L3 管控矩阵与方案 §2.5 一致。"""
        assert AuthPolicy().authorize(Session(Role.ADMIN), Action.RESTORE_BACKUP, NOW).danger is DangerLevel.L3
        assert AuthPolicy().authorize(Session(Role.ADMIN), Action.STOP_SERVICE, NOW).danger is DangerLevel.L2
        assert AuthPolicy().authorize(Session(Role.ADMIN), Action.RESTART_SERVICE, NOW).danger is DangerLevel.L1
        assert AuthPolicy().authorize(Session(Role.ADMIN), Action.VIEW, NOW).danger is DangerLevel.L0

    def test_control_mode_by_danger(self) -> None:
        p = AuthPolicy()
        assert p.authorize(Session(Role.ADMIN), Action.VIEW, NOW).control == 'none'
        assert p.authorize(Session(Role.ADMIN), Action.CLEAR_LOGS, NOW).control == 'toast_undo'
        assert p.authorize(Session(Role.ADMIN), Action.KILL_PORT, NOW).control == 'confirm_impact'
        assert p.authorize(Session(Role.ADMIN), Action.UNINSTALL_SERVICES, NOW).control == 'type_name_reason'


class TestDenyFlow:
    def test_deny_suggests_minimum_role(self) -> None:
        """无权限 → 禁用而非隐藏，返回建议提权到的最低角色。"""
        p = AuthPolicy()
        s = Session(base_role=Role.VIEWER)
        d = p.authorize(s, Action.STOP_SERVICE, NOW)
        assert not d.allowed and d.elevate_to is Role.OPERATOR
        d3 = p.authorize(s, Action.UNINSTALL_SERVICES, NOW)
        assert d3.elevate_to is Role.ADMIN

    def test_expired_elevation_falls_back(self) -> None:
        """JIT 过期自动降权。"""
        p = AuthPolicy()
        s = Session(base_role=Role.VIEWER, elevated=Role.OPERATOR, expires_at=NOW + 100)
        assert p.effective_role(s, NOW + 50) is Role.OPERATOR
        assert p.effective_role(s, NOW + 101) is Role.VIEWER  # 过期回落
        assert p.authorize(s, Action.STOP_SERVICE, NOW + 101).allowed is False


class TestJitElevation:
    def test_elevate_and_ttl(self) -> None:
        p = AuthPolicy()
        s = Session(base_role=Role.VIEWER)
        result, s2 = p.elevate(s, Role.OPERATOR, now=NOW)
        assert result.ok
        assert s2.elevated is Role.OPERATOR
        assert s2.expires_at == pytest.approx(NOW + AuthPolicy.ELEVATE_TTL_S)
        assert p.ttl_remaining(s2, NOW + 60) == pytest.approx(AuthPolicy.ELEVATE_TTL_S - 60)

    def test_elevate_rejects_lower_or_equal(self) -> None:
        p = AuthPolicy()
        s = Session(base_role=Role.OPERATOR)
        result, s2 = p.elevate(s, Role.OPERATOR, now=NOW)
        assert not result.ok and s2 is s
        result2, s3 = p.elevate(s, Role.VIEWER, now=NOW)
        assert not result2.ok and s3 is s

    def test_touch_sliding_expiry(self) -> None:
        """滑动续期：每次操作后过期时间顺延。"""
        p = AuthPolicy()
        _, s = p.elevate(Session(Role.VIEWER), Role.OPERATOR, now=NOW)
        s2 = p.touch(s, now=NOW + 1000)
        assert s2.expires_at == pytest.approx(NOW + 1000 + AuthPolicy.ELEVATE_TTL_S)
        # 未提权会话 touch 无效
        assert p.touch(Session(Role.OPERATOR), now=NOW).elevated_active is False

    def test_degrade_immediate(self) -> None:
        p = AuthPolicy()
        _, s = p.elevate(Session(Role.VIEWER), Role.ADMIN, now=NOW)
        s2 = p.degrade(s)
        assert not s2.elevated_active
        assert p.effective_role(s2, NOW) is Role.VIEWER

    def test_build_session(self) -> None:
        p = AuthPolicy()
        assert p.build_session(Role.VIEWER, None, NOW).elevated_active is False
        assert p.build_session(Role.VIEWER, Role.OPERATOR, NOW).elevated is Role.OPERATOR
        # 请求低于 base 的"提权"被忽略
        assert p.build_session(Role.ADMIN, Role.VIEWER, NOW).elevated_active is False


class TestL3Reason:
    def test_l3_requires_reason(self) -> None:
        p = AuthPolicy()
        assert not p.check_reason(DangerLevel.L3, '').ok
        assert not p.check_reason(DangerLevel.L3, '   ').ok
        assert p.check_reason(DangerLevel.L3, '服务器迁移，卸载旧机服务').ok

    def test_lower_levels_exempt(self) -> None:
        p = AuthPolicy()
        for d in (DangerLevel.L0, DangerLevel.L1, DangerLevel.L2):
            assert p.check_reason(d, '').ok, d
