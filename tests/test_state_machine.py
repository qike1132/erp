"""审批状态机单元测试"""
import pytest
from fastapi_app.core.state_machine import (
    ApprovalAction,
    ApprovalState,
    can_transition,
    get_allowed_actions,
    is_terminal,
    transition,
)


class TestStateMachine:
    def test_init_to_pending(self):
        assert can_transition(None, ApprovalAction.SUBMIT)
        assert transition(None, ApprovalAction.SUBMIT) == ApprovalState.PENDING
        assert transition('init', ApprovalAction.SUBMIT) == ApprovalState.PENDING

    def test_cancelled_to_pending_resubmit(self):
        assert can_transition(ApprovalState.CANCELLED, ApprovalAction.SUBMIT)
        assert transition(ApprovalState.CANCELLED, ApprovalAction.SUBMIT) == ApprovalState.PENDING

    def test_rejected_to_pending_resubmit(self):
        assert can_transition(ApprovalState.REJECTED, ApprovalAction.SUBMIT)
        assert transition(ApprovalState.REJECTED, ApprovalAction.SUBMIT) == ApprovalState.PENDING

    def test_pending_to_approved(self):
        assert can_transition(ApprovalState.PENDING, ApprovalAction.APPROVE)
        assert transition(ApprovalState.PENDING, ApprovalAction.APPROVE) == ApprovalState.APPROVED

    def test_pending_to_rejected(self):
        assert can_transition(ApprovalState.PENDING, ApprovalAction.REJECT)
        assert transition(ApprovalState.PENDING, ApprovalAction.REJECT) == ApprovalState.REJECTED

    def test_pending_to_cancelled(self):
        assert can_transition(ApprovalState.PENDING, ApprovalAction.CANCEL)
        assert transition(ApprovalState.PENDING, ApprovalAction.CANCEL) == ApprovalState.CANCELLED

    def test_approved_is_terminal(self):
        assert is_terminal(ApprovalState.APPROVED)

    def test_approved_cannot_retransition(self):
        assert not can_transition(ApprovalState.APPROVED, ApprovalAction.APPROVE)
        assert not can_transition(ApprovalState.APPROVED, ApprovalAction.REJECT)
        assert not can_transition(ApprovalState.APPROVED, ApprovalAction.CANCEL)
        assert not can_transition(ApprovalState.APPROVED, ApprovalAction.SUBMIT)

    def test_rejected_cannot_cancel(self):
        assert not can_transition(ApprovalState.REJECTED, ApprovalAction.CANCEL)

    def test_cancelled_cannot_approve(self):
        assert not can_transition(ApprovalState.CANCELLED, ApprovalAction.APPROVE)
        assert not can_transition(ApprovalState.CANCELLED, ApprovalAction.REJECT)

    def test_illegal_transition_raises(self):
        with pytest.raises(ValueError, match='非法审批状态转换'):
            transition(ApprovalState.APPROVED, ApprovalAction.CANCEL)

    def test_get_allowed_actions_from_pending(self):
        allowed = get_allowed_actions(ApprovalState.PENDING)
        assert ApprovalAction.APPROVE in allowed
        assert ApprovalAction.REJECT in allowed
        assert ApprovalAction.CANCEL in allowed
        assert ApprovalAction.SUBMIT not in allowed

    def test_get_allowed_actions_from_rejected(self):
        allowed = get_allowed_actions(ApprovalState.REJECTED)
        assert ApprovalAction.SUBMIT in allowed
        assert ApprovalAction.APPROVE not in allowed

    def test_get_allowed_actions_from_approved(self):
        allowed = get_allowed_actions(ApprovalState.APPROVED)
        assert allowed == []
