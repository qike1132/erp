"""
数据查询 / 报表统计 单元测试

覆盖：
- 订单查询（多维度筛选、分页）
- 订单流水
- 入库流水
- 出库流水
- 报表统计汇总
- 日期范围解析
- SQL 标识符安全校验
- 聚合函数方言选择
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date, datetime

from fastapi_app.services.report_service import (
    _quote_identifier,
    _string_agg,
    _get_dialect_name,
    _query_logs_generic,
    query_order_logs,
    query_order_flow,
    query_stockin_logs,
    query_stockout_logs,
    query_inventory_summary,
)


class TestSQLHelpers:
    """SQL 安全辅助函数"""

    def test_quote_identifier_valid(self):
        """合法标识符"""
        # mock dialect as postgresql
        with patch('fastapi_app.services.report_service._get_dialect_name', return_value='postgresql'):
            result = _quote_identifier('order')
            assert '"order"' == result

    def test_quote_identifier_invalid(self):
        """非法标识符"""
        with pytest.raises(ValueError, match='非法SQL标识符'):
            _quote_identifier('users_table')  # 不在白名单中

    def test_string_agg_valid_expr(self):
        """合法聚合表达式"""
        with patch('fastapi_app.services.report_service._get_dialect_name', return_value='postgresql'):
            result = _string_agg('o.order_no', ', ')
            assert 'STRING_AGG' in result
            assert 'o.order_no' in result

    def test_string_agg_invalid_expr(self):
        """非法表达式"""
        with pytest.raises(ValueError, match='非法SQL聚合表达式'):
            _string_agg('o.password', ', ')

    def test_string_agg_invalid_separator(self):
        """非法分隔符"""
        with pytest.raises(ValueError, match='非法SQL聚合分隔符'):
            _string_agg('o.order_no', '--')

    def test_string_agg_mysql_dialect(self):
        """MySQL 方言"""
        with patch('fastapi_app.services.report_service._get_dialect_name', return_value='mysql'):
            result = _string_agg('o.order_no', ', ')
            assert 'GROUP_CONCAT' in result


class TestQueryOrderLogs:
    """订单查询"""

    @pytest.mark.asyncio
    async def test_query_order_logs_empty(self, mock_async_db):
        """空订单日志"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_order_logs(mock_async_db, page=1, per_page=20)

        assert result['success'] is True
        assert result['logs'] == []

    @pytest.mark.asyncio
    async def test_query_order_logs_with_filters(self, mock_async_db):
        """带筛选条件"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_order_logs(
            mock_async_db, page=1, per_page=20,
            customer='测试客户', product_id=1
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_query_order_logs_pagination(self, mock_async_db):
        """分页查询"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_order_logs(
            mock_async_db, page=3, per_page=20
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_query_order_logs_with_date_range(self, mock_async_db):
        """日期范围筛选"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_order_logs(
            mock_async_db, page=1, per_page=20,
            start_date='2024-01-01', end_date='2024-12-31'
        )

        assert result['success'] is True


class TestQueryOrderFlow:
    """订单流水查询"""

    @pytest.mark.asyncio
    async def test_query_order_flow_empty(self, mock_async_db):
        """空订单流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_order_flow(mock_async_db, page=1, per_page=20)

        assert result['success'] is True
        assert result['logs'] == []

    @pytest.mark.asyncio
    async def test_query_order_flow_with_product(self, mock_async_db):
        """按产品查询流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_order_flow(
            mock_async_db, page=1, per_page=20, product_id=1
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_query_order_flow_with_status(self, mock_async_db):
        """按状态查询流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_order_flow(
            mock_async_db, page=1, per_page=20, status='已备货'
        )

        assert result['success'] is True


class TestQueryStockInLogs:
    """入库流水查询"""

    @pytest.mark.asyncio
    async def test_query_stockin_logs_empty(self, mock_async_db):
        """空入库流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_stockin_logs(mock_async_db, page=1, per_page=20)

        assert result['success'] is True
        assert result['logs'] == []

    @pytest.mark.asyncio
    async def test_query_stockin_logs_with_customer(self, mock_async_db):
        """按客户查询入库流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_stockin_logs(
            mock_async_db, page=1, per_page=20, customer='测试客户'
        )

        assert result['success'] is True


class TestQueryStockOutLogs:
    """出库流水查询"""

    @pytest.mark.asyncio
    async def test_query_stockout_logs_empty(self, mock_async_db):
        """空出库流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_stockout_logs(mock_async_db, page=1, per_page=20)

        assert result['success'] is True
        assert result['logs'] == []

    @pytest.mark.asyncio
    async def test_query_stockout_logs_with_customer(self, mock_async_db):
        """按客户查询出库流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_stockout_logs(
            mock_async_db, page=1, per_page=20, customer='测试客户'
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_query_stockout_logs_pagination(self, mock_async_db):
        """分页查询出库流水"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_stockout_logs(
            mock_async_db, page=2, per_page=30
        )

        assert result['success'] is True


class TestQueryInventorySummary:
    """库存汇总报表"""

    @pytest.mark.asyncio
    async def test_query_inventory_summary_empty(self, mock_async_db):
        """空库存汇总"""
        mock_async_db.execute = AsyncMock()
        mock_async_db.execute.return_value.fetchall.return_value = []

        result = await query_inventory_summary(mock_async_db)

        assert result['success'] is True

    @pytest.mark.asyncio
    async def test_query_inventory_summary_with_data(self, mock_async_db):
        """有数据汇总"""
        mock_async_db.execute = AsyncMock()

        row = MagicMock()
        row.product_name = '产品A'
        row.barcode = 'BAR001'
        row.initial_stock = 100
        row.current_stock = 150
        row.total_in = 200
        row.total_out = 150
        row.order_quantity = 100

        mock_async_db.execute.return_value.fetchall.return_value = [row]

        result = await query_inventory_summary(mock_async_db)

        assert result['success'] is True
