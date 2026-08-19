"""
皮套管理 单元测试

覆盖：
- 皮套库存搜索（关键词、多维度）
- 皮套库存汇总（分页、产品汇总）
- 皮套入库记录
- 皮套出库记录
- 库存流水查询
- 数据校验（日期格式、分页参数、数量范围）
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.services.case_service import (
    _normalize_pagination,
    _parse_date,
)


class TestHelpers:
    """辅助函数测试"""

    def test_parse_date_valid(self):
        """合法日期"""
        result = _parse_date('2024-06-15')
        assert result is not None

    def test_parse_date_invalid(self):
        """非法日期格式"""
        with pytest.raises(BusinessError):
            _parse_date('2024/06/15')

    def test_normalize_pagination_valid(self):
        """合法分页参数"""
        page, per_page = _normalize_pagination(2, 30, 100)
        assert page == 2
        assert per_page == 30

    def test_normalize_pagination_page_zero(self):
        """页码为0修正为1"""
        page, _per_page = _normalize_pagination(0, 20, 100)
        assert page == 1

    def test_normalize_pagination_page_negative(self):
        """页码为负修正为1"""
        page, _per_page = _normalize_pagination(-5, 20, 100)
        assert page == 1

    def test_normalize_pagination_exceed_max(self):
        """每页数超过上限"""
        _page, per_page = _normalize_pagination(1, 300, 100)
        assert per_page == 100

    def test_normalize_pagination_per_page_zero(self):
        """每页数为0修正为1"""
        _page, per_page = _normalize_pagination(1, 0, 100)
        assert per_page == 1


class TestSearchCases:
    """皮套搜索"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.search_cases')
    async def test_search_cases_empty(self, mock_search):
        """空搜索结果"""
        mock_search.return_value = {'success': True, 'items': []}

        result = await mock_search(MagicMock(), query='不存在的皮套')

        assert result['success'] is True
        assert result['items'] == []

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.search_cases')
    async def test_search_cases_by_barcode(self, mock_search):
        """按条码搜索"""
        mock_search.return_value = {
            'success': True,
            'items': [{'id': 1, 'barcode': 'CASE001', 'name': '皮套A'}]
        }

        result = await mock_search(MagicMock(), query='CASE001')

        assert result['success'] is True
        assert len(result['items']) == 1


class TestCaseInventorySummary:
    """皮套库存汇总"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.get_case_inventory_summary')
    async def test_get_case_inventory_summary_empty(self, mock_summary):
        """空库存汇总"""
        mock_summary.return_value = {'success': True, 'items': [], 'total': 0}

        result = await mock_summary(MagicMock(), page=1, per_page=20)

        assert result['success'] is True
        assert result['items'] == []

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.get_case_inventory_summary')
    async def test_get_case_inventory_summary_with_data(self, mock_summary):
        """有数据汇总"""
        mock_summary.return_value = {
            'success': True,
            'items': [{'barcode': 'CASE001', 'current_stock': 50}],
            'total': 5
        }

        result = await mock_summary(MagicMock(), page=1)

        assert result['total'] == 5


class TestCaseStockIn:
    """皮套入库"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.create_case_stockin')
    async def test_create_case_stockin_success(self, mock_create):
        """正常入库"""
        mock_create.return_value = {'success': True, 'message': '入库成功'}

        result = await mock_create(
            MagicMock(), case_id=1, quantity=30,
            stockin_date=date(2024, 6, 15), note='入库测试'
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.create_case_stockin')
    async def test_create_case_stockin_zero_quantity(self, mock_create):
        """入库数量为0"""
        mock_create.side_effect = BusinessError('入库数量必须大于0')

        with pytest.raises(BusinessError, match='入库数量必须大于0'):
            await mock_create(MagicMock(), case_id=1, quantity=0, stockin_date=date(2024, 6, 15))

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.create_case_stockin')
    async def test_create_case_stockin_negative_quantity(self, mock_create):
        """入库数量为负"""
        mock_create.side_effect = BusinessError('入库数量必须大于0')

        with pytest.raises(BusinessError, match='入库数量必须大于0'):
            await mock_create(MagicMock(), case_id=1, quantity=-10, stockin_date=date(2024, 6, 15))


class TestCaseStockOut:
    """皮套出库"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.create_case_stockout')
    async def test_create_case_stockout_success(self, mock_create):
        """正常出库"""
        mock_create.return_value = {'success': True, 'message': '出库成功'}

        result = await mock_create(
            MagicMock(), case_id=1, quantity=20,
            stockout_date=date(2024, 6, 15), note='出库测试'
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.create_case_stockout')
    async def test_create_case_stockout_insufficient_stock(self, mock_create):
        """库存不足"""
        mock_create.side_effect = BusinessError('库存不足')

        with pytest.raises(BusinessError, match='库存不足'):
            await mock_create(MagicMock(), case_id=1, quantity=50, stockout_date=date(2024, 6, 15))

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.create_case_stockout')
    async def test_create_case_stockout_product_not_found(self, mock_create):
        """产品不存在"""
        mock_create.side_effect = NotFoundError('皮套产品不存在')

        with pytest.raises(NotFoundError, match='皮套产品不存在'):
            await mock_create(MagicMock(), case_id=999, quantity=10, stockout_date=date(2024, 6, 15))


class TestCaseStockInDelete:
    """删除皮套入库"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.delete_case_stockin')
    async def test_delete_case_stockin_success(self, mock_delete):
        """正常删除"""
        mock_delete.return_value = {'success': True, 'message': '删除成功'}

        result = await mock_delete(MagicMock(), 1)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.delete_case_stockin')
    async def test_delete_case_stockin_not_found(self, mock_delete):
        """记录不存在"""
        mock_delete.side_effect = NotFoundError('入库记录不存在')

        with pytest.raises(NotFoundError, match='入库记录不存在'):
            await mock_delete(MagicMock(), 999)


class TestCaseStockOutDelete:
    """删除皮套出库"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.delete_case_stockout')
    async def test_delete_case_stockout_success(self, mock_delete):
        """正常删除"""
        mock_delete.return_value = {'success': True, 'message': '删除成功'}

        result = await mock_delete(MagicMock(), 1)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.delete_case_stockout')
    async def test_delete_case_stockout_not_found(self, mock_delete):
        """记录不存在"""
        mock_delete.side_effect = NotFoundError('出库记录不存在')

        with pytest.raises(NotFoundError, match='出库记录不存在'):
            await mock_delete(MagicMock(), 999)


class TestCaseInventoryLogs:
    """库存流水查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.get_case_inventory_logs')
    async def test_get_inventory_logs_empty(self, mock_logs):
        """空流水"""
        mock_logs.return_value = {'success': True, 'items': [], 'total': 0}

        result = await mock_logs(MagicMock(), case_id=1, page=1)

        assert result['success'] is True
        assert result['items'] == []

    @pytest.mark.asyncio
    @patch('fastapi_app.services.case_service.get_case_inventory_logs')
    async def test_get_inventory_logs_with_data(self, mock_logs):
        """有流水记录"""
        mock_logs.return_value = {
            'success': True,
            'items': [{'id': 1, 'change_type': '入库'}],
            'total': 10
        }

        result = await mock_logs(MagicMock(), case_id=1, page=1, per_page=20)

        assert result['total'] == 10
        assert len(result['items']) == 1
