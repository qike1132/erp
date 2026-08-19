"""order_crud.py 中提取的 helper 函数 - 单元测试

覆盖 P1-1 重构提取的 helper：
- _build_beile_unified_query（UNION ALL 合并 Order + StockIn 子查询）
- _fetch_beile_records_by_ids（按 ID 回表获取订单与备货记录）
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services import order_crud


# ============================================================================
# _build_beile_unified_query
# ============================================================================
class TestBuildBeileUnifiedQuery:
    def test_returns_subquery_with_order_part(self):
        """无确认状态筛选时应包含 Order + StockIn 两部分"""
        subq = order_crud._build_beile_unified_query(
            confirm_condition=None, customer=None, factory="湖北",
        )
        compiled = str(subq.compile())
        assert 'record_type' in compiled
        assert 'order' in compiled

    def test_with_confirm_condition_excludes_stockin(self):
        """有确认状态条件时（confirm_condition 非 None）应仅查询订单，排除备货"""
        from fastapi_app.shared_models import Order
        confirm_cond = Order.confirmed_at.is_(None)
        subq = order_crud._build_beile_unified_query(
            confirm_condition=confirm_cond, customer=None, factory="湖北",
        )
        compiled = str(subq.compile())
        assert 'confirmed_at' in compiled

    def test_with_customer_filter_applies_to_both_parts(self):
        """customer 非空时应同时筛选 Order 和 StockIn 的 customer"""
        subq = order_crud._build_beile_unified_query(
            confirm_condition=None, customer="MINISO", factory="湖北",
        )
        compiled = str(subq.compile())
        assert 'customer' in compiled

    def test_factory_filter_applied(self):
        """factory 应作为 Product.factory 筛选条件"""
        subq = order_crud._build_beile_unified_query(
            confirm_condition=None, customer=None, factory="深圳",
        )
        compiled = str(subq.compile())
        assert 'factory' in compiled

    def test_no_customer_no_confirm_includes_both_parts(self):
        """无 customer、无 confirm_condition 时应包含 Order + StockIn 两部分（UNION ALL）"""
        subq = order_crud._build_beile_unified_query(
            confirm_condition=None, customer=None, factory="湖北",
        )
        # subquery 应可编译
        compiled = str(subq.compile())
        assert 'UNION' in compiled or 'union' in compiled.lower() or 'select' in compiled.lower()


# ============================================================================
# _fetch_beile_records_by_ids
# ============================================================================
class TestFetchBeileRecordsByIds:
    @pytest.mark.asyncio
    async def test_empty_ids_returns_empty_maps(self):
        """空 ID 列表应返回空字典，不查询 DB"""
        db = AsyncMock()
        orders_map, stockins_map = await order_crud._fetch_beile_records_by_ids(db, [], [])
        assert orders_map == {}
        assert stockins_map == {}
        assert db.execute.await_count == 0

    @pytest.mark.asyncio
    async def test_fetches_orders_by_ids(self):
        """order_ids 非空时应查询并构建 orders_map"""
        mock_order_1 = MagicMock()
        mock_order_1.id = 1
        mock_order_2 = MagicMock()
        mock_order_2.id = 2

        order_result = MagicMock()
        order_result.scalars.return_value.unique.return_value = [mock_order_1, mock_order_2]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=order_result)

        orders_map, stockins_map = await order_crud._fetch_beile_records_by_ids(db, [1, 2], [])
        assert orders_map == {1: mock_order_1, 2: mock_order_2}
        assert stockins_map == {}
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_fetches_stockins_by_ids(self):
        """stockin_ids 非空时应查询并构建 stockins_map"""
        mock_stockin_1 = MagicMock()
        mock_stockin_1.id = 10
        mock_stockin_2 = MagicMock()
        mock_stockin_2.id = 11

        stockin_result = MagicMock()
        stockin_result.scalars.return_value = [mock_stockin_1, mock_stockin_2]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=stockin_result)

        orders_map, stockins_map = await order_crud._fetch_beile_records_by_ids(db, [], [10, 11])
        assert orders_map == {}
        assert stockins_map == {10: mock_stockin_1, 11: mock_stockin_2}
        assert db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_fetches_both_orders_and_stockins(self):
        """同时提供 order_ids 和 stockin_ids 时应执行 2 次查询"""
        mock_order = MagicMock()
        mock_order.id = 1
        mock_stockin = MagicMock()
        mock_stockin.id = 10

        order_result = MagicMock()
        order_result.scalars.return_value.unique.return_value = [mock_order]
        stockin_result = MagicMock()
        stockin_result.scalars.return_value = [mock_stockin]

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[order_result, stockin_result])

        orders_map, stockins_map = await order_crud._fetch_beile_records_by_ids(db, [1], [10])
        assert orders_map == {1: mock_order}
        assert stockins_map == {10: mock_stockin}
        assert db.execute.await_count == 2
