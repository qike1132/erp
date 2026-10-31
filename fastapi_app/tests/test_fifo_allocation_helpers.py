"""fifo_allocation.py 中提取的 helper 函数 - 单元测试

覆盖 P1-1 重构提取的 helper：
- _build_fifo_plan_id_to_customer（plan_id → customer_name 映射构建）
- _group_fifo_details_by_key（按 (customer, product) 分组明细）
- _query_fifo_stockout_rows（出货记录查询，双分支：product_id / JOIN Product）
"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import fifo_allocation


def _make_detail(plan_id, product_name, product_id=0, detail_id=0):
    """构造 mock PurchasePlanDetail"""
    d = MagicMock()
    d.plan_id = plan_id
    d.product_name = product_name
    d.product_id = product_id
    d.id = detail_id
    return d


# ============================================================================
# _build_fifo_plan_id_to_customer
# ============================================================================
class TestBuildFifoPlanIdToCustomer:
    @pytest.mark.asyncio
    async def test_always_scopes_to_all_customer_plans(self):
        """即使 customer_name_map 已覆盖全部明细，也必须查「客户全部计划」（A-M17）。

        旧实现命中 map 就跳过查询、把作用域收窄到当前明细的 plan_id：
        同一明细经写/列表/详情三个入口会拿到不同的 shipped_qty（跨月计划的历史
        出货被漏算），并已出货量失真。
        """
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        customer_name_map = {1: "客户A"}

        mock_result = MagicMock()
        mock_result.all.return_value = [
            MagicMock(id=1, customer_name="客户A"),
            MagicMock(id=9, customer_name="客户A"),  # 同客户的历史月计划
        ]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await fifo_allocation._build_fifo_plan_id_to_customer(
            db, customer_name_map, [d1], ["客户A"], date(2026, 1, 1),
        )
        assert db.execute.await_count == 1
        assert result == {1: "客户A", 9: "客户A"}

    @pytest.mark.asyncio
    async def test_map_name_overrides_db_value(self):
        """map 里的名字优先（调用方可能带已规范化的展示名）。"""
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        mock_result = MagicMock()
        mock_result.all.return_value = [MagicMock(id=1, customer_name="客户A（旧名）")]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await fifo_allocation._build_fifo_plan_id_to_customer(
            db, {1: "客户A"}, [d1], ["客户A"], date(2026, 1, 1),
        )
        assert result == {1: "客户A"}

    @pytest.mark.asyncio
    async def test_queries_db_when_map_incomplete(self):
        """customer_name_map 缺失 plan_id 时应查询 DB 补全"""
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        d2 = _make_detail(plan_id=2, product_name="P2", detail_id=11)
        customer_name_map = {1: "客户A"}  # 缺 plan_id=2

        mock_result = MagicMock()
        row1 = MagicMock(id=1, customer_name="客户A")
        row2 = MagicMock(id=2, customer_name="客户B")
        mock_result.all.return_value = [row1, row2]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await fifo_allocation._build_fifo_plan_id_to_customer(
            db, customer_name_map, [d1, d2], ["客户A", "客户B"], date(2026, 1, 1),
        )
        assert result == {1: "客户A", 2: "客户B"}
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_queries_db_when_map_is_none(self):
        """customer_name_map 为 None 时应查询 DB"""
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        mock_result = MagicMock()
        row1 = MagicMock(id=1, customer_name="客户A")
        mock_result.all.return_value = [row1]
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await fifo_allocation._build_fifo_plan_id_to_customer(
            db, None, [d1], ["客户A"], date(2026, 1, 1),
        )
        assert result == {1: "客户A"}

    @pytest.mark.asyncio
    async def test_filters_out_falsy_customer_names_from_map(self):
        """customer_name_map 中值为空字符串的 plan_id 不得覆盖 DB 的真空名。"""
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        d2 = _make_detail(plan_id=2, product_name="P2", detail_id=11)
        customer_name_map = {1: "客户A", 2: ""}

        mock_result = MagicMock()
        mock_result.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)

        result = await fifo_allocation._build_fifo_plan_id_to_customer(
            db, customer_name_map, [d1, d2], ["客户A"], date(2026, 1, 1),
        )
        assert result == {1: "客户A"}
        assert 2 not in result


# ============================================================================
# _group_fifo_details_by_key
# ============================================================================
class TestGroupFifoDetailsByKey:
    def test_groups_details_by_customer_product_key(self):
        """应按 (customer, product_name) 元组键分组"""
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        d2 = _make_detail(plan_id=1, product_name="P1", detail_id=11)
        d3 = _make_detail(plan_id=2, product_name="P2", detail_id=12)
        plan_id_to_customer = {1: "客户A", 2: "客户B"}
        keys_needed = {("客户A", "P1"), ("客户B", "P2")}

        result = fifo_allocation._group_fifo_details_by_key(
            [d1, d2, d3], plan_id_to_customer, keys_needed,
        )
        assert len(result[("客户A", "P1")]) == 2
        assert len(result[("客户B", "P2")]) == 1

    def test_skips_details_with_empty_customer_name(self):
        """customer_name 为空时应跳过该明细"""
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        plan_id_to_customer = {1: ""}
        keys_needed = {("", "P1")}

        result = fifo_allocation._group_fifo_details_by_key(
            [d1], plan_id_to_customer, keys_needed,
        )
        assert result == {}

    def test_skips_details_with_empty_product_name(self):
        """product_name 为空时应跳过该明细"""
        d1 = _make_detail(plan_id=1, product_name="", detail_id=10)
        plan_id_to_customer = {1: "客户A"}
        keys_needed = {("客户A", "")}

        result = fifo_allocation._group_fifo_details_by_key(
            [d1], plan_id_to_customer, keys_needed,
        )
        assert result == {}

    def test_skips_details_not_in_keys_needed(self):
        """不在 keys_needed 中的键应被跳过"""
        d1 = _make_detail(plan_id=1, product_name="P1", detail_id=10)
        plan_id_to_customer = {1: "客户A"}
        keys_needed = {("客户B", "P2")}  # 不含 ("客户A", "P1")

        result = fifo_allocation._group_fifo_details_by_key(
            [d1], plan_id_to_customer, keys_needed,
        )
        assert result == {}

    def test_empty_details_returns_empty_dict(self):
        """空明细列表应返回空字典"""
        result = fifo_allocation._group_fifo_details_by_key(
            [], {1: "客户A"}, {("客户A", "P1")},
        )
        assert result == {}

    def test_unknown_plan_id_uses_empty_string_customer(self):
        """plan_id 不在映射中时应使用空字符串 customer，导致跳过"""
        d1 = _make_detail(plan_id=99, product_name="P1", detail_id=10)
        plan_id_to_customer = {1: "客户A"}
        keys_needed = {("", "P1")}

        result = fifo_allocation._group_fifo_details_by_key(
            [d1], plan_id_to_customer, keys_needed,
        )
        # customer_name 为空字符串 → 跳过
        assert result == {}


# ============================================================================
# _query_fifo_stockout_rows
# ============================================================================
class TestQueryFifoStockoutRows:
    @pytest.mark.asyncio
    async def test_uses_product_id_path_when_ids_present(self):
        """product_ids 非空时应走 product_id 路径（2 次查询：stockout + product 映射）"""
        stockout_mock = MagicMock()
        product_row = MagicMock()
        product_row.id = 1
        product_row.name = "P1"
        product_mock = MagicMock()
        product_mock.all.return_value = [product_row]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[stockout_mock, product_mock])

        result, pid_to_name = await fifo_allocation._query_fifo_stockout_rows(
            db, keys_needed={("客户A", "P1")},
            customers=["客户A"], product_ids=[1],
            stockout_date_limit=date(2026, 1, 1),
        )
        assert result is stockout_mock
        assert pid_to_name == {1: "P1"}
        assert db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_uses_join_path_when_no_product_ids(self):
        """product_ids 为空时应走 JOIN Product 降级路径（1 次查询）"""
        stockout_mock = MagicMock()
        db = AsyncMock()
        db.execute = AsyncMock(return_value=stockout_mock)

        result, pid_to_name = await fifo_allocation._query_fifo_stockout_rows(
            db, keys_needed={("客户A", "P1")},
            customers=["客户A"], product_ids=[],
            stockout_date_limit=date(2026, 1, 1),
        )
        assert result is stockout_mock
        assert pid_to_name == {}
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_mixed_batch_queries_dirty_names_and_dedupes_rows(self):
        """Z03-R6：混合批次要对 product_id=0 的产品名补查，并按 id 去重。"""
        main_row = MagicMock(id=1, product_id=1)
        dirty_row = MagicMock(id=2, product_id=0, product_name='脏产品')
        stockout_mock = MagicMock()
        stockout_mock.all.return_value = [main_row]
        product_row = MagicMock(id=1, name='P1')
        product_mock = MagicMock()
        product_mock.all.return_value = [product_row]
        extra_mock = MagicMock()
        # 主查询已命中的行也出现在 JOIN 结果里 → 必须按 id 去重
        extra_mock.all.return_value = [main_row, dirty_row]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[stockout_mock, product_mock, extra_mock])

        result, _ = await fifo_allocation._query_fifo_stockout_rows(
            db, keys_needed={("客户A", "P1"), ("客户A", "脏产品")},
            customers=["客户A"], product_ids=[1],
            stockout_date_limit=date(2026, 1, 1),
            dirty_product_names={'脏产品'},
        )
        assert result.all() == [main_row, dirty_row]
        assert db.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_product_id_path_builds_pid_to_name_map(self):
        """product_id 路径应正确构建 pid_to_name 映射"""
        stockout_mock = MagicMock()
        row1 = MagicMock()
        row1.id = 1
        row1.name = "P1"
        row2 = MagicMock()
        row2.id = 2
        row2.name = "P2"
        product_mock = MagicMock()
        product_mock.all.return_value = [row1, row2]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[stockout_mock, product_mock])

        _, pid_to_name = await fifo_allocation._query_fifo_stockout_rows(
            db, keys_needed={("客户A", "P1"), ("客户A", "P2")},
            customers=["客户A"], product_ids=[1, 2],
            stockout_date_limit=date(2026, 1, 1),
        )
        assert pid_to_name == {1: "P1", 2: "P2"}
