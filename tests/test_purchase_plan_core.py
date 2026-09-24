"""采购计划核心算法单元测试

覆盖三个纯函数（无数据库依赖）：
    - allocate_fifo: FIFO 出货分配算法
    - _recalc_plan_status: 计划状态推算
    - _calc_stock_status: 库存状态判定
"""
from unittest.mock import MagicMock

from fastapi_app.services.fifo_allocation import allocate_fifo
from fastapi_app.services.purchase_plan_queries import _calc_stock_status
from fastapi_app.services.purchase_plan_shipment import _recalc_plan_status


def _make_detail(detail_id: int, quantity: int, plan_date=None, plan_id: int = 1, product_name: str = 'P1'):
    """创建 mock PurchasePlanDetail"""
    d = MagicMock()
    d.id = detail_id
    d.plan_id = plan_id
    d.quantity = quantity
    d.product_name = product_name
    d.plan_date = plan_date
    d.product_id = 1
    return d


# ============================================================
# allocate_fifo
# ============================================================

class TestAllocateFifo:
    """FIFO 分配算法单元测试"""

    def test_empty_details(self):
        """空明细列表 → 空分配"""
        assert allocate_fifo([], {}, {}) == {}

    def test_no_shipped(self):
        """无出货数据 → 全零分配"""
        details = [_make_detail(1, 10), _make_detail(2, 20)]
        result = allocate_fifo(details, {}, {})
        assert result == {1: 0, 2: 0}

    def test_single_product_partial_fill(self):
        """单一产品，出货量 < 首批计划量 → 仅填满第一批"""
        d1 = _make_detail(1, 10, plan_date='2026-01-01')
        d2 = _make_detail(2, 20, plan_date='2026-01-15')
        details_by_key = {('客户A', 'P1'): [d1, d2]}
        shipped_by_key = {('客户A', 'P1'): 8}
        result = allocate_fifo([d1, d2], details_by_key, shipped_by_key)
        assert result[1] == 8  # 第一批填 8
        assert result[2] == 0  # 第二批未分配到

    def test_single_product_exact_fill(self):
        """出货量恰好等于首批计划量"""
        d1 = _make_detail(1, 10)
        d2 = _make_detail(2, 20)
        details_by_key = {('客户A', 'P1'): [d1, d2]}
        shipped_by_key = {('客户A', 'P1'): 10}
        result = allocate_fifo([d1, d2], details_by_key, shipped_by_key)
        assert result[1] == 10
        assert result[2] == 0

    def test_single_product_fill_first_then_partial(self):
        """出货量跨越多批 → 第一批填满，第二批部分填"""
        d1 = _make_detail(1, 10)
        d2 = _make_detail(2, 20)
        d3 = _make_detail(3, 15)
        details_by_key = {('客户A', 'P1'): [d1, d2, d3]}
        shipped_by_key = {('客户A', 'P1'): 35}
        result = allocate_fifo([d1, d2, d3], details_by_key, shipped_by_key)
        assert result[1] == 10   # 第一批全部
        assert result[2] == 20   # 第二批全部
        assert result[3] == 5    # 第三批剩余 5

    def test_single_product_overfill(self):
        """出货量超过总计划量 → 全部分配完（剩余溢出丢弃）"""
        d1 = _make_detail(1, 10)
        d2 = _make_detail(2, 20)
        details_by_key = {('客户A', 'P1'): [d1, d2]}
        shipped_by_key = {('客户A', 'P1'): 100}
        result = allocate_fifo([d1, d2], details_by_key, shipped_by_key)
        assert result[1] == 10   # 第一批全部分配
        assert result[2] == 20   # 第二批全部分配

    def test_multiple_customers_products(self):
        """多客户 + 多产品 → 各自独立分配"""
        d1 = _make_detail(1, 10, plan_id=1, product_name='P1')
        d2 = _make_detail(2, 20, plan_id=1, product_name='P2')
        d3 = _make_detail(3, 30, plan_id=2, product_name='P1')
        details_by_key = {
            ('客户A', 'P1'): [d1],
            ('客户A', 'P2'): [d2],
            ('客户B', 'P1'): [d3],
        }
        shipped_by_key = {
            ('客户A', 'P1'): 5,
            ('客户A', 'P2'): 20,
            ('客户B', 'P1'): 0,
        }
        result = allocate_fifo([d1, d2, d3], details_by_key, shipped_by_key)
        assert result[1] == 5   # 客户A-P1: 5/10
        assert result[2] == 20  # 客户A-P2: 20/20
        assert result[3] == 0   # 客户B-P1: 0/30

    def test_plan_details_not_in_key_get_zero(self):
        """plan_details 中存在但不在 details_by_key 中的明细 → 分配 0"""
        d1 = _make_detail(1, 10)
        d2 = _make_detail(2, 20)
        details_by_key = {('客户A', 'P1'): [d1]}
        shipped_by_key = {('客户A', 'P1'): 5}
        # d2 不在 details_by_key 中
        result = allocate_fifo([d1, d2], details_by_key, shipped_by_key)
        assert result[1] == 5
        assert result[2] == 0  # 补零

    def test_zero_quantity_details(self):
        """数量为 0 的明细 → 分配 0"""
        d1 = _make_detail(1, 0)
        details_by_key = {('客户A', 'P1'): [d1]}
        shipped_by_key = {('客户A', 'P1'): 10}
        result = allocate_fifo([d1], details_by_key, shipped_by_key)
        assert result[1] == 0


# ============================================================
# _recalc_plan_status
# ============================================================

class TestRecalcPlanStatus:
    """计划状态推算单元测试"""

    def test_pending_unchanged(self):
        """pending 状态保持不变"""
        details = [_make_detail(1, 10)]
        assert _recalc_plan_status(details, {}, 'pending') == 'pending'

    def test_cancelled_unchanged(self):
        """cancelled 状态保持不变"""
        details = [_make_detail(1, 10)]
        assert _recalc_plan_status(details, {}, 'cancelled') == 'cancelled'

    def test_empty_details_returns_confirmed(self):
        """无明细 → confirmed"""
        assert _recalc_plan_status([], {}, 'confirmed') == 'confirmed'

    def test_all_shipped_returns_completed(self):
        """全部出货完成 → completed"""
        d1 = _make_detail(1, 10)
        d2 = _make_detail(2, 20)
        shipped_map = {1: 10, 2: 20}
        assert _recalc_plan_status([d1, d2], shipped_map, 'confirmed') == 'completed'

    def test_partial_shipped_returns_confirmed(self):
        """部分出货 → confirmed"""
        d1 = _make_detail(1, 10)
        d2 = _make_detail(2, 20)
        shipped_map = {1: 10, 2: 5}  # d2 只出了 5/20
        assert _recalc_plan_status([d1, d2], shipped_map, 'confirmed') == 'confirmed'

    def test_none_shipped_returns_confirmed(self):
        """全部未出货 → confirmed"""
        d1 = _make_detail(1, 10)
        d2 = _make_detail(2, 20)
        shipped_map = {1: 0, 2: 0}
        assert _recalc_plan_status([d1, d2], shipped_map, 'confirmed') == 'confirmed'

    def test_single_detail_partial_returns_confirmed(self):
        """单条明细未出完 → confirmed"""
        d = _make_detail(1, 10)
        shipped_map = {1: 7}
        assert _recalc_plan_status([d], shipped_map, 'confirmed') == 'confirmed'

    def test_single_detail_completed(self):
        """单条明细出完 → completed"""
        d = _make_detail(1, 10)
        shipped_map = {1: 10}
        assert _recalc_plan_status([d], shipped_map, 'confirmed') == 'completed'

    def test_default_status_is_confirmed(self):
        """默认 current_status='confirmed'"""
        d = _make_detail(1, 10)
        shipped_map = {1: 10}
        assert _recalc_plan_status([d], shipped_map) == 'completed'


# ============================================================
# _calc_stock_status
# ============================================================

class TestCalcStockStatus:
    """库存状态判定单元测试"""

    def test_zero_inventory(self):
        """库存 = 0 → no_stock"""
        assert _calc_stock_status(10, 0) == 'no_stock'

    def test_negative_inventory(self):
        """库存为负 → no_stock"""
        assert _calc_stock_status(10, -5) == 'no_stock'

    def test_sufficient(self):
        """库存 >= 计划量 → sufficient"""
        assert _calc_stock_status(10, 15) == 'sufficient'
        assert _calc_stock_status(10, 10) == 'sufficient'

    def test_shortage(self):
        """0 < 库存 < 计划量 → shortage"""
        assert _calc_stock_status(10, 5) == 'shortage'
        assert _calc_stock_status(10, 1) == 'shortage'

    def test_no_plan_zero_inventory(self):
        """计划量 = 0, 库存 = 0 → no_stock"""
        assert _calc_stock_status(0, 0) == 'no_stock'

    def test_no_plan_with_inventory(self):
        """计划量 = 0, 库存 > 0 → sufficient"""
        assert _calc_stock_status(0, 10) == 'sufficient'

    def test_large_numbers(self):
        """大数量边界"""
        assert _calc_stock_status(999999, 999999) == 'sufficient'
        assert _calc_stock_status(999999, 999998) == 'shortage'
        assert _calc_stock_status(999999, 0) == 'no_stock'
