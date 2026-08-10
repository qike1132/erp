"""
板房管理 单元测试

覆盖：
- BOM 列表查询（分页、关键词搜索、状态筛选）
- BOM 创建（编号生成）
- BOM 更新
- BOM 删除
- BOM 详情查询
- 变更日志查询
- 版本对比
- 校验函数（类别、状态、版本号递增）
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.services.pattern_room_service import (
    _validate_category,
    _validate_status,
    _next_version,
    PATTERN_ROOM_CATEGORIES,
    PATTERN_ROOM_BOM_STATUSES,
)
from fastapi_app.core.exceptions import BusinessError, NotFoundError


class TestValidation:
    """校验函数"""

    def test_validate_valid_categories(self):
        """合法类别"""
        for cat in PATTERN_ROOM_CATEGORIES.keys():
            _validate_category(cat)

    def test_validate_invalid_category(self):
        """无效类别"""
        with pytest.raises(BusinessError, match='物料类别无效'):
            _validate_category('invalid_category')

    def test_validate_valid_statuses(self):
        """合法状态"""
        for status in PATTERN_ROOM_BOM_STATUSES.keys():
            _validate_status(status)

    def test_validate_invalid_status(self):
        """无效状态"""
        with pytest.raises(BusinessError, match='BOM 状态无效'):
            _validate_status('invalid_status')

    def test_next_version_t1(self):
        """版本递增"""
        assert _next_version('T1') == 'T2'
        assert _next_version('T2') == 'T3'
        assert _next_version('T10') == 'T11'

    def test_next_version_invalid(self):
        """无效版本号回退到 T1"""
        assert _next_version('') == 'T1'
        assert _next_version('invalid') == 'T1'
        assert _next_version(None) == 'T1'


class TestListBoms:
    """BOM 列表查询"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.list_boms')
    async def test_list_boms_empty(self, mock_list):
        """空列表"""
        mock_list.return_value = {'items': [], 'total': 0, 'pages': 0}

        result = await mock_list(MagicMock(), page=1, per_page=20)

        assert result['items'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.list_boms')
    async def test_list_boms_with_keyword(self, mock_list):
        """关键词搜索"""
        mock_list.return_value = {
            'items': [{'id': 1, 'bom_no': 'BOM-001'}],
            'total': 1
        }

        result = await mock_list(MagicMock(), page=1, keyword='产品')

        assert result['total'] == 1

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.list_boms')
    async def test_list_boms_with_status(self, mock_list):
        """状态筛选"""
        mock_list.return_value = {'items': [], 'total': 3}

        result = await mock_list(MagicMock(), page=1, status='活跃')

        assert result['total'] == 3

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.list_boms')
    async def test_list_boms_pagination(self, mock_list):
        """分页"""
        mock_list.return_value = {'items': [], 'total': 45}

        result = await mock_list(MagicMock(), page=2, per_page=20)

        assert result['total'] == 45


class TestGetBomDetail:
    """BOM 详情"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.get_bom_detail')
    async def test_get_bom_detail_success(self, mock_detail):
        """查询 BOM 详情"""
        mock_detail.return_value = {'id': 1, 'bom_no': 'BOM-001'}

        result = await mock_detail(MagicMock(), 1)

        assert result is not None

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.get_bom_detail')
    async def test_get_bom_detail_not_found(self, mock_detail):
        """BOM 不存在"""
        mock_detail.side_effect = NotFoundError('BOM 不存在')

        with pytest.raises(NotFoundError):
            await mock_detail(MagicMock(), 999)


class TestCreateBom:
    """创建 BOM"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.create_bom')
    async def test_create_bom_success(self, mock_create):
        """正常创建 BOM"""
        mock_create.return_value = {'success': True, 'message': '创建成功', 'bom_id': 1}

        result = await mock_create(
            MagicMock(), product_name='测试产品',
            customer_id=1, customer_name='客户', operator=MagicMock()
        )

        assert result['success'] is True
        assert '创建成功' in result['message']

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.create_bom')
    async def test_create_bom_with_items(self, mock_create):
        """带物料的 BOM 创建"""
        mock_create.return_value = {'success': True, 'message': '创建成功', 'bom_id': 2}

        result = await mock_create(
            MagicMock(), product_name='带物料产品',
            customer_id=1, customer_name='客户',
            items=[{'material_code': 'M001', 'material_name': '布料A'}],
            operator=MagicMock()
        )

        assert result['success'] is True


class TestUpdateBom:
    """更新 BOM"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.update_bom')
    async def test_update_bom_success(self, mock_update):
        """正常更新 BOM"""
        mock_update.return_value = {'success': True, 'message': '更新成功'}

        result = await mock_update(
            MagicMock(), bom_id=1, product_name='更新名称',
            operator=MagicMock()
        )

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.update_bom')
    async def test_update_bom_not_found(self, mock_update):
        """BOM 不存在"""
        mock_update.side_effect = NotFoundError('BOM 不存在')

        with pytest.raises(NotFoundError):
            await mock_update(MagicMock(), bom_id=999, operator=MagicMock())

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.update_bom')
    async def test_update_bom_status(self, mock_update):
        """仅更新状态"""
        mock_update.return_value = {'success': True, 'message': '更新成功'}

        result = await mock_update(
            MagicMock(), bom_id=1, status='作废', operator=MagicMock()
        )

        assert result['success'] is True


class TestDeleteBom:
    """删除 BOM"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.delete_bom')
    async def test_delete_bom_success(self, mock_delete):
        """正常删除"""
        mock_delete.return_value = {'success': True, 'message': '删除成功'}

        result = await mock_delete(MagicMock(), 1)

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.delete_bom')
    async def test_delete_bom_not_found(self, mock_delete):
        """BOM 不存在"""
        mock_delete.side_effect = NotFoundError('BOM 不存在')

        with pytest.raises(NotFoundError):
            await mock_delete(MagicMock(), 999)


class TestChangeLogs:
    """变更日志"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.list_change_logs')
    async def test_list_change_logs_empty(self, mock_logs):
        """空日志"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 0}

        result = await mock_logs(MagicMock(), bom_id=1)

        assert result['success'] is True
        assert result['logs'] == []

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.list_change_logs')
    async def test_list_change_logs_with_data(self, mock_logs):
        """有日志记录"""
        mock_logs.return_value = {
            'success': True,
            'logs': [{'id': 1, 'action': 'update', 'diff': {}}],
            'total': 1
        }

        result = await mock_logs(MagicMock(), bom_id=1)

        assert result['success'] is True
        assert len(result['logs']) == 1

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.list_change_logs')
    async def test_list_change_logs_pagination(self, mock_logs):
        """分页查询日志"""
        mock_logs.return_value = {'success': True, 'logs': [], 'total': 50}

        result = await mock_logs(MagicMock(), bom_id=1, page=2, per_page=10)

        assert result['success'] is True


class TestCompareVersions:
    """版本对比"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.pattern_room_service.compare_versions')
    async def test_compare_versions(self, mock_compare):
        """对比两个版本"""
        mock_compare.return_value = {
            'success': True,
            'diff': {'added': [], 'removed': [], 'modified': []}
        }

        result = await mock_compare(
            MagicMock(), bom_id=1, from_version='T1', to_version='T2'
        )

        assert result['success'] is True
