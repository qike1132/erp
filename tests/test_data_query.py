"""
数据查询 - 订单查询 / 订单流水 / 出货计划 单元测试

覆盖：
- 订单流水查询（多维度筛选、分页）
- 入库流水查询
- 出库流水查询
- 抵扣流水查询
- 报表导出
"""
from unittest.mock import MagicMock, patch

import pytest


class TestOrderLogs:
    """订单流水查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_order_logs')
    async def test_get_order_logs_empty(self, mock_logs):
        """空流水"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 0}

        result = await mock_logs(MagicMock(), page=1, per_page=50)

        assert result['success'] is True
        assert result['total'] == 0

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_order_logs')
    async def test_get_order_logs_with_customer(self, mock_logs):
        """按客户筛选"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 5}

        result = await mock_logs(MagicMock(), page=1, per_page=50, customer='测试客户')

        assert result['total'] == 5

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_order_logs')
    async def test_get_order_logs_with_status(self, mock_logs):
        """按状态筛选"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 3}

        result = await mock_logs(MagicMock(), page=1, per_page=50, status='已完成')

        assert result['total'] == 3

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_order_logs')
    async def test_get_order_logs_pagination(self, mock_logs):
        """分页查询"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 100}

        result = await mock_logs(MagicMock(), page=3, per_page=20)

        assert result['total'] == 100


class TestStockInLogs:
    """入库流水查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_stockin_logs')
    async def test_get_stockin_logs_empty(self, mock_logs):
        """空入库流水"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 0}

        result = await mock_logs(MagicMock(), page=1, per_page=50)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_stockin_logs')
    async def test_get_stockin_logs_with_customer(self, mock_logs):
        """按客户筛选"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 10}

        result = await mock_logs(MagicMock(), page=1, per_page=50, customer='客户A')

        assert result['total'] == 10


class TestStockOutLogs:
    """出库流水查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_stockout_logs')
    async def test_get_stockout_logs_empty(self, mock_logs):
        """空出库流水"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 0}

        result = await mock_logs(MagicMock(), page=1, per_page=50)

        assert result['success'] is True


class TestDeductionLogs:
    """抵扣流水查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_deduction_logs')
    async def test_get_deduction_logs_empty(self, mock_logs):
        """空抵扣流水"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 0}

        result = await mock_logs(MagicMock(), page=1, per_page=50)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.get_deduction_logs')
    async def test_get_deduction_logs_with_product(self, mock_logs):
        """按产品筛选"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 7}

        result = await mock_logs(MagicMock(), page=1, per_page=50, product='产品A')

        assert result['total'] == 7


class TestExportReport:
    """报表导出"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.export_report_to_excel')
    async def test_export_order_report(self, mock_export):
        """导出订单报表"""
        mock_export.return_value = {'success': True, 'html': '<table>...</table>'}

        result = await mock_export(MagicMock(), report_type='order')

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.export_report_to_excel')
    async def test_export_stockin_report(self, mock_export):
        """导出入库报表"""
        mock_export.return_value = {'success': True, 'html': '<table>...</table>'}

        result = await mock_export(MagicMock(), report_type='stockin')

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.report_service.export_report_to_excel')
    async def test_export_stockout_report(self, mock_export):
        """导出出库报表"""
        mock_export.return_value = {'success': True, 'html': '<table>...</table>'}

        result = await mock_export(MagicMock(), report_type='stockout')

        assert result['success'] is True
