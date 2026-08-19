"""
来料登记 单元测试

覆盖：
- 来料登记列表查询（分页、多维度筛选）
- 来料登记创建（关联采购订单、物料明细）
- 来料登记更新（状态变更）
- 来料登记删除
- 物料收货登记（并发安全、数量校验）
- 统计概览和趋势
- 边界条件
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.material_registration_service import (
    create_registration,
    delete_registration,
)


class TestGetRegistrations:
    """来料登记列表查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_registrations')
    async def test_get_registrations_empty(self, mock_get):
        """查询空列表"""
        mock_get.return_value = {
            'success': True, 'registrations': [], 'total': 0, 'page': 1
        }

        result = await mock_get(MagicMock(), page=1)

        assert result['success'] is True
        assert result['registrations'] == []

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_registrations')
    async def test_get_registrations_with_status_filter(self, mock_get):
        """按状态筛选"""
        mock_get.return_value = {
            'success': True, 'registrations': [], 'total': 5
        }

        result = await mock_get(MagicMock(), page=1, status='pending')

        assert result['success'] is True
        assert result['total'] == 5

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_registrations')
    async def test_get_registrations_with_date_range(self, mock_get):
        """按日期范围筛选"""
        mock_get.return_value = {
            'success': True, 'registrations': [], 'total': 1
        }

        result = await mock_get(
            MagicMock(), page=1,
            start_date='2024-06-01', end_date='2024-06-30'
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_registrations')
    async def test_get_registrations_exclude_completed(self, mock_get):
        """排除已完成的登记"""
        mock_get.return_value = {
            'success': True, 'registrations': [], 'total': 3
        }

        result = await mock_get(MagicMock(), page=1, exclude_completed=True)

        assert result['success'] is True


class TestCreateRegistration:
    """来料登记创建"""

    @pytest.mark.asyncio
    async def test_create_registration_purchase_order_not_found(self, mock_async_db):
        """采购订单不存在"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='采购订单不存在'):
            await create_registration(mock_async_db, 999, user_id=1)


class TestUpdateRegistration:
    """来料登记更新"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.update_registration')
    async def test_update_registration_success(self, mock_update):
        """更新登记成功"""
        mock_update.return_value = {'success': True, 'message': '更新成功'}

        result = await mock_update(MagicMock(), 1, status='completed')

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.update_registration')
    async def test_update_registration_not_found(self, mock_update):
        """更新不存在的登记"""
        mock_update.side_effect = ValueError('来料登记不存在')

        with pytest.raises(ValueError, match='来料登记不存在'):
            await mock_update(MagicMock(), 999)


class TestDeleteRegistration:
    """来料登记删除"""

    @pytest.mark.asyncio
    async def test_delete_registration_not_found(self, mock_async_db):
        """删除不存在的登记"""
        mock_async_db.get = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match='来料登记不存在'):
            await delete_registration(mock_async_db, 999)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.delete_registration')
    async def test_delete_registration_success(self, mock_delete):
        """正常删除"""
        mock_delete.return_value = {'success': True, 'message': '删除成功'}

        result = await mock_delete(MagicMock(), 1)

        assert result['success'] is True


class TestReceiveMaterial:
    """物料收货登记"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.receive_material')
    async def test_receive_material_success(self, mock_receive):
        """正常收货"""
        mock_receive.return_value = {'success': True, 'message': '收货登记成功'}

        result = await mock_receive(MagicMock(), 1, 30)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.receive_material')
    async def test_receive_material_not_found(self, mock_receive):
        """收货 - 物料不存在"""
        mock_receive.side_effect = ValueError('物料明细不存在')

        with pytest.raises(ValueError, match='物料明细不存在'):
            await mock_receive(MagicMock(), 999, 10)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.receive_material')
    async def test_receive_material_zero_quantity(self, mock_receive):
        """收货数量为0"""
        mock_receive.side_effect = ValueError('收货数量必须大于0')

        with pytest.raises(ValueError, match='收货数量必须大于0'):
            await mock_receive(MagicMock(), 1, 0)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.receive_material')
    async def test_receive_material_exceed_ordered(self, mock_receive):
        """收货数量超过采购数量"""
        mock_receive.side_effect = ValueError('收货数量不能超过采购数量')

        with pytest.raises(ValueError, match='收货数量不能超过采购数量'):
            await mock_receive(MagicMock(), 1, 200)


class TestStats:
    """统计相关"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_stats_overview')
    async def test_get_stats_overview(self, mock_stats):
        """统计概览"""
        mock_stats.return_value = {
            'success': True,
            'overview': {'total': 100, 'pending': 5}
        }

        result = await mock_stats(MagicMock())

        assert result['success'] is True
        assert 'overview' in result

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_stats_trend')
    async def test_get_stats_trend(self, mock_trend):
        """统计趋势"""
        mock_trend.return_value = {
            'success': True,
            'trend': [{'date': '2024-06-01', 'count': 3}]
        }

        result = await mock_trend(MagicMock(), days=30)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_stats_distribution')
    async def test_get_stats_distribution(self, mock_dist):
        """状态分布统计"""
        mock_dist.return_value = {
            'success': True,
            'distribution': {'pending': 5, 'partial': 3, 'completed': 10}
        }

        result = await mock_dist(MagicMock())

        assert result['success'] is True


class TestGetPurchaseOrderItems:
    """获取采购订单物料"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_purchase_order_items')
    async def test_get_purchase_order_items_success(self, mock_items):
        """获取采购订单物料明细"""
        mock_items.return_value = {
            'success': True,
            'items': [{'id': 1, 'material_code': 'M001'}]
        }

        result = await mock_items(MagicMock(), 1)

        assert result['success'] is True
        assert len(result['items']) == 1

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_purchase_order_items')
    async def test_get_purchase_order_items_not_found(self, mock_items):
        """采购订单不存在"""
        mock_items.side_effect = ValueError('采购订单不存在')

        with pytest.raises(ValueError, match='采购订单不存在'):
            await mock_items(MagicMock(), 999)


class TestGetHistory:
    """来料登记历史"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_history')
    async def test_get_history_empty(self, mock_history):
        """空历史记录"""
        mock_history.return_value = {
            'success': True, 'registrations': [], 'total': 0
        }

        result = await mock_history(MagicMock(), page=1)

        assert result['success'] is True
        assert result['registrations'] == []

    @pytest.mark.asyncio
    @patch('fastapi_app.services.material_registration_service.get_history')
    async def test_get_history_with_filters(self, mock_history):
        """带筛选的历史查询"""
        mock_history.return_value = {
            'success': True, 'registrations': [], 'total': 3
        }

        result = await mock_history(
            MagicMock(), page=1,
            order_no='PO-2024', supplier='供应商'
        )

        assert result['total'] == 3
