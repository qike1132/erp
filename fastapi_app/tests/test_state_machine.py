"""状态机引擎与各域状态机单测（批次1，2026-08-22）

覆盖：
- 审批域原 API 行为完全不变（回归保护，34 处调用方零改动的前提）
- 通用 StateMachine 引擎（转移/终态/非法转移）
- staging 状态机（pending → approved/rejected，终态不可再转移）
- PurchaseOrderStatus 常量值与 DB 字面量一致
"""
import pytest

from fastapi_app.core import state_machine as sm


class TestApprovalApiUnchanged:
    """审批域模块级 API 回归：泛化改造必须零行为变化"""

    def test_get_allowed_actions_pending(self):
        assert set(sm.get_allowed_actions('pending')) == {'approve', 'reject', 'cancel'}

    def test_get_allowed_actions_init(self):
        assert set(sm.get_allowed_actions(None)) == {'submit'}
        assert set(sm.get_allowed_actions('init')) == {'submit'}

    def test_can_transition(self):
        assert sm.can_transition('pending', 'approve')
        assert sm.can_transition('rejected', 'submit')
        assert not sm.can_transition('approved', 'approve')

    def test_transition_returns_new_state(self):
        assert sm.transition('pending', 'approve') == 'approved'
        assert sm.transition(None, 'submit') == 'pending'

    def test_transition_invalid_raises(self):
        with pytest.raises(ValueError, match='非法审批状态转换'):
            sm.transition('approved', 'approve')

    def test_is_terminal(self):
        assert sm.is_terminal('approved')
        assert not sm.is_terminal('pending')
        assert not sm.is_terminal('cancelled')


class TestGenericStateMachine:
    def test_staging_approve(self):
        assert sm.staging_machine.transition('pending', sm.StagingAction.APPROVE) == sm.StagingStatus.APPROVED

    def test_staging_reject(self):
        assert sm.staging_machine.transition('pending', sm.StagingAction.REJECT) == sm.StagingStatus.REJECTED

    def test_staging_terminal_states_frozen(self):
        for action in (sm.StagingAction.APPROVE, sm.StagingAction.REJECT):
            for terminal in (sm.StagingStatus.APPROVED, sm.StagingStatus.REJECTED):
                assert not sm.staging_machine.can_transition(terminal, action)
                with pytest.raises(ValueError, match='staging'):
                    sm.staging_machine.transition(terminal, action)

    def test_staging_unknown_status_has_no_actions(self):
        assert sm.staging_machine.get_allowed_actions(None) == []
        assert sm.staging_machine.get_allowed_actions('unknown') == []

    def test_machine_is_terminal(self):
        assert sm.staging_machine.is_terminal(sm.StagingStatus.APPROVED)
        assert not sm.staging_machine.is_terminal(sm.StagingStatus.PENDING)

    def test_constants_match_db_literals(self):
        assert (sm.StagingStatus.PENDING, sm.StagingStatus.APPROVED, sm.StagingStatus.REJECTED) \
            == ('pending', 'approved', 'rejected')


class TestOutsourceOrderViewStatus:
    def test_values(self):
        from fastapi_app.services.outsource._common import OutsourceOrderViewStatus
        assert OutsourceOrderViewStatus.PENDING == 'pending'
        assert OutsourceOrderViewStatus.IN_PROGRESS == 'in_progress'
        assert OutsourceOrderViewStatus.COMPLETED == 'completed'


class TestPurchaseOrderStatus:
    def test_values_match_db_literals(self):
        from fastapi_app.shared_models import PurchaseOrderStatus
        assert PurchaseOrderStatus.PENDING == 'pending'
        assert PurchaseOrderStatus.COMPLETED == 'completed'
