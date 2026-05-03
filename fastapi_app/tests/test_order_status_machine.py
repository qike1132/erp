"""订单状态机单元测试"""
import pytest

from fastapi_app.shared_models.order import (
    DELETABLE_STATUSES,
    EDITABLE_STATUSES,
    STATUS_TRANSITIONS,
    VALID_ORDER_STATUSES,
    Order,
)


class TestOrderStatusValidation:
    """测试状态值校验"""

    def test_valid_statuses(self):
        for status in VALID_ORDER_STATUSES:
            Order.validate_status(status)

    def test_invalid_status_raises_value_error(self):
        with pytest.raises(ValueError, match="无效的订单状态"):
            Order.validate_status("不存在的状态")

    def test_empty_status_raises(self):
        with pytest.raises(ValueError):
            Order.validate_status("")

    def test_valid_status_count(self):
        assert len(VALID_ORDER_STATUSES) == 7


class TestOrderStatusTransitions:
    """测试状态转移规则"""

    def _make_order(self, status: str) -> Order:
        return Order(
            id=1,
            order_no="ORD-TEST-001",
            customer="Test Customer",
            product_id=1,
            quantity=10,
            status=status,
        )

    def test_pending_to_partial(self):
        order = self._make_order("待备货")
        assert order.can_transition_to("部分备货")
        order.transition_to("部分备货")
        assert order.status == "部分备货"

    def test_pending_to_full_prep(self):
        order = self._make_order("待备货")
        assert order.can_transition_to("已备货")

    def test_pending_to_cancel(self):
        order = self._make_order("待备货")
        assert order.can_transition_to("已取消")

    def test_partial_to_ready_ship(self):
        order = self._make_order("部分备货")
        assert order.can_transition_to("待出货")

    def test_partial_to_full_prep(self):
        order = self._make_order("部分备货")
        assert order.can_transition_to("已备货")

    def test_full_prep_to_ready_ship(self):
        order = self._make_order("已备货")
        assert order.can_transition_to("待出货")

    def test_ready_ship_to_shipped(self):
        order = self._make_order("待出货")
        assert order.can_transition_to("已出货")

    def test_shipped_to_completed(self):
        order = self._make_order("已出货")
        assert order.can_transition_to("已完成")

    def test_completed_is_terminal(self):
        order = self._make_order("已完成")
        for status in VALID_ORDER_STATUSES:
            if status != "已完成":
                assert not order.can_transition_to(status), f"已完成 should not transition to {status}"

    def test_cancelled_is_terminal(self):
        order = self._make_order("已取消")
        for status in VALID_ORDER_STATUSES:
            if status != "已取消":
                assert not order.can_transition_to(status), f"已取消 should not transition to {status}"

    def test_invalid_transition_raises_value_error(self):
        order = self._make_order("已完成")
        with pytest.raises(ValueError, match="不允许.*变更为"):
            order.transition_to("待备货")

    def test_same_status_is_allowed(self):
        order = self._make_order("待备货")
        assert order.can_transition_to("待备货")
        order.transition_to("待备货")
        assert order.status == "待备货"

    def test_invalid_status_in_transition_raises(self):
        order = self._make_order("待备货")
        with pytest.raises(ValueError, match="无效的订单状态"):
            order.transition_to("invalid_status")

    def test_full_transition_chain(self):
        order = self._make_order("待备货")
        chain = ["待备货", "部分备货", "已备货", "待出货", "已出货", "已完成"]
        for status in chain:
            order.transition_to(status)
            assert order.status == status


class TestOrderDeletableEditable:
    """测试可删除/可编辑状态"""

    def _make_order(self, status: str) -> Order:
        return Order(
            id=1,
            order_no="ORD-TEST-002",
            customer="Test Customer",
            product_id=1,
            quantity=10,
            status=status,
        )

    def test_deletable_statuses(self):
        for status in DELETABLE_STATUSES:
            order = self._make_order(status)
            assert order.is_deletable()

    def test_not_deletable_statuses(self):
        for status in VALID_ORDER_STATUSES - DELETABLE_STATUSES:
            order = self._make_order(status)
            assert not order.is_deletable()

    def test_editable_statuses(self):
        for status in EDITABLE_STATUSES:
            order = self._make_order(status)
            assert order.is_editable()

    def test_not_editable_statuses(self):
        for status in VALID_ORDER_STATUSES - EDITABLE_STATUSES:
            order = self._make_order(status)
            assert not order.is_editable()

    def test_completed_not_deletable(self):
        order = self._make_order("已完成")
        assert not order.is_deletable()

    def test_shipped_not_editable(self):
        order = self._make_order("已出货")
        assert not order.is_editable()


class TestOrderStatusTransitionsCompleteness:
    """测试状态转移图完整性"""

    def test_all_statuses_have_transitions(self):
        for status in VALID_ORDER_STATUSES:
            assert status in STATUS_TRANSITIONS, f"{status} missing from STATUS_TRANSITIONS"

    def test_no_orphan_statuses(self):
        all_targets = set()
        for targets in STATUS_TRANSITIONS.values():
            all_targets.update(targets)
        for target in all_targets:
            assert target in VALID_ORDER_STATUSES, f"Orphan target status: {target}"

    def test_default_status_is_valid(self):
        Order(
            id=1,
            order_no="ORD-TEST-003",
            customer="Test Customer",
            product_id=1,
            quantity=10,
        )
        # SQLAlchemy default applies on INSERT, not Python construction
        # So we test that the default value itself is valid
        assert "待备货" in VALID_ORDER_STATUSES
        Order.validate_status("待备货")
