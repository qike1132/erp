"""状态机单元测试（通用引擎 + staging 转移表）

审批域状态机已随审批系统下线移除（2026-11-28）；本文件改为守护
StateMachine 引擎契约与 staging 转移表（fastapi_app/tests/test_state_machine.py
为同一引擎的姊妹用例，两侧共用断言口径）。
"""
import pytest

from fastapi_app.core.state_machine import (
    StagingAction,
    StagingStatus,
    StateMachine,
    staging_machine,
)


class TestStateMachineEngine:
    """通用 StateMachine 引擎契约（以 staging_machine 为实例验证）。"""

    def test_pending_to_approved(self):
        assert staging_machine.can_transition(StagingStatus.PENDING, StagingAction.APPROVE)
        assert staging_machine.transition(
            StagingStatus.PENDING, StagingAction.APPROVE) == StagingStatus.APPROVED

    def test_pending_to_rejected(self):
        assert staging_machine.can_transition(StagingStatus.PENDING, StagingAction.REJECT)
        assert staging_machine.transition(
            StagingStatus.PENDING, StagingAction.REJECT) == StagingStatus.REJECTED

    def test_terminal_states(self):
        assert staging_machine.is_terminal(StagingStatus.APPROVED)
        assert staging_machine.is_terminal(StagingStatus.REJECTED)
        assert not staging_machine.is_terminal(StagingStatus.PENDING)

    def test_terminal_cannot_retransition(self):
        assert not staging_machine.can_transition(StagingStatus.APPROVED, StagingAction.APPROVE)
        assert not staging_machine.can_transition(StagingStatus.APPROVED, StagingAction.REJECT)

    def test_illegal_transition_raises(self):
        with pytest.raises(ValueError, match='非法\\[staging\\]状态转换'):
            staging_machine.transition(StagingStatus.APPROVED, StagingAction.APPROVE)

    def test_get_allowed_actions_from_pending(self):
        allowed = staging_machine.get_allowed_actions(StagingStatus.PENDING)
        assert StagingAction.APPROVE in allowed
        assert StagingAction.REJECT in allowed

    def test_get_allowed_actions_from_terminal(self):
        assert staging_machine.get_allowed_actions(StagingStatus.APPROVED) == []

    def test_none_status_falls_back_to_init(self):
        machine = StateMachine('empty', {'init': {'go': 'done'}})
        assert machine.can_transition(None, 'go')
        assert machine.transition(None, 'go') == 'done'
