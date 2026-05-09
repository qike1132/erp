"""订单状态派生计算单元测试"""
import pytest
from datetime import datetime

from fastapi_app.shared_models.order import (
    VALID_ORDER_STATUSES,
    Order,
    compute_status_from_stockouts,
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

    def test_default_status_is_valid(self):
        assert "待备货" in VALID_ORDER_STATUSES
        Order.validate_status("待备货")


class TestComputeStatusFromStockouts:
    """测试派生状态计算函数"""

    def _make_order(self, quantity: int = 10, batch_completed_at=None) -> Order:
        return Order(
            id=1,
            order_no="ORD-TEST-001",
            customer="Test Customer",
            product_id=1,
            quantity=quantity,
            status=None,
            batch_completed_at=batch_completed_at,
        )

    # --- 基础状态：无备货无出货 ---

    def test_no_stockouts_returns_pending(self):
        order = self._make_order()
        assert compute_status_from_stockouts(order, 0, 0) == '待备货'

    # --- 备货状态 ---

    def test_partial_deduction_returns_partial(self):
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 5, 0) == '部分备货'

    def test_full_deduction_returns_full_prep(self):
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 10, 0) == '已备货'

    def test_deduction_exceeds_quantity_returns_full_prep(self):
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 15, 0) == '已备货'

    # --- 出货状态 ---

    def test_partial_shipment_returns_ready_ship(self):
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 0, 5) == '待出货'

    def test_full_shipment_returns_shipped(self):
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 0, 10) == '已出货'

    def test_shipment_exceeds_quantity_returns_shipped(self):
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 0, 15) == '已出货'

    # --- 出货优先于备货 ---

    def test_shipment_takes_priority_over_deduction(self):
        """有出货记录时，出货状态优先于备货状态"""
        order = self._make_order(quantity=10)
        # 5件备货 + 3件出货 = 待出货（出货未满）
        assert compute_status_from_stockouts(order, 5, 3) == '待出货'
        # 5件备货 + 10件出货 = 已出货（出货已满）
        assert compute_status_from_stockouts(order, 5, 10) == '已出货'

    # --- 批次完成 ---

    def test_batch_completed_takes_highest_priority(self):
        """batch_completed_at 有值时，无论备货/出货量如何，均为批次已完成"""
        order = self._make_order(batch_completed_at=datetime.now())
        assert compute_status_from_stockouts(order, 0, 0) == '批次已完成'
        assert compute_status_from_stockouts(order, 5, 0) == '批次已完成'
        assert compute_status_from_stockouts(order, 0, 10) == '批次已完成'

    # --- 边界值 ---

    def test_zero_deduction_and_shipment(self):
        order = self._make_order(quantity=1)
        assert compute_status_from_stockouts(order, 0, 0) == '待备货'

    def test_single_item_full_deduction(self):
        order = self._make_order(quantity=1)
        assert compute_status_from_stockouts(order, 1, 0) == '已备货'

    def test_single_item_full_shipment(self):
        order = self._make_order(quantity=1)
        assert compute_status_from_stockouts(order, 0, 1) == '已出货'

    # --- 退货场景（净量减少） ---

    def test_return_reverts_shipped_to_ready_ship(self):
        """已出货后退部分货，净出货量 < 订单量 → 待出货"""
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 0, 6) == '待出货'

    def test_return_reverts_to_pending(self):
        """全部退货，净出货量 = 0，净备货量 = 0 → 待备货"""
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 0, 0) == '待备货'

    def test_partial_return_with_deduction(self):
        """退完出货后仍有备货 → 已备货"""
        order = self._make_order(quantity=10)
        assert compute_status_from_stockouts(order, 10, 0) == '已备货'
