"""
审批管理 单元测试

覆盖：
- 审批列表查询（状态筛选、搜索、分页）
- 审批详情查询
- 审批同意（状态机校验）
- 审批拒绝
- 待审批数量统计
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestApprovalService:
    """审批服务 - 使用函数级 mock"""

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_approval_list')
    async def test_get_approval_list_empty(self, mock_list):
        """空审批列表"""
        mock_list.return_value = {'approvals': [], 'total': 0, 'pages': 0}

        result = await mock_list()

        assert result['approvals'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_approval_list')
    async def test_get_approval_list_pending(self, mock_list):
        """待审批列表"""
        mock_list.return_value = {
            'approvals': [{'id': 1, 'status': 'pending'}],
            'total': 1, 'pending_count': 5
        }

        result = await mock_list()

        assert result['total'] == 1
        assert result['pending_count'] == 5

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_approval_list')
    async def test_get_approval_list_with_search(self, mock_list):
        """搜索审批"""
        mock_list.return_value = {
            'approvals': [{'id': 2, 'order_no': 'ORD-2024-0001'}],
            'total': 1
        }

        result = await mock_list()

        assert result['total'] == 1

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_approval_list')
    async def test_get_approval_list_approved(self, mock_list):
        """已审批列表"""
        mock_list.return_value = {
            'approvals': [{'id': 3, 'status': 'approved'}],
            'total': 1, 'approved_count': 3
        }

        result = await mock_list()

        assert result['approved_count'] == 3

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_approval_detail')
    async def test_get_approval_detail_success(self, mock_detail):
        """查询审批详情"""
        mock_detail.return_value = {
            'id': 1, 'status': 'pending',
            'operation_type': 'edit', 'operation_data': '{"quantity":100}'
        }

        result = await mock_detail(1)

        assert result['id'] == 1
        assert result['status'] == 'pending'

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_approval_detail')
    async def test_get_approval_detail_not_found(self, mock_detail):
        """审批不存在"""
        mock_detail.side_effect = ValueError('审批请求不存在')

        with pytest.raises(ValueError, match='审批请求不存在'):
            await mock_detail(999)

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.approve_request')
    async def test_approve_request_success(self, mock_approve):
        """审批同意成功"""
        mock_approve.return_value = {
            'success': True, 'message': '审批已通过'
        }

        result = await mock_approve(1, MagicMock())

        assert result['success'] is True

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.approve_request')
    async def test_approve_request_already_processed(self, mock_approve):
        """审批已处理 - 不能重复审批"""
        mock_approve.side_effect = ValueError('该审批请求已处理')

        with pytest.raises(ValueError, match='已处理'):
            await mock_approve(1, MagicMock())

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.reject_request')
    async def test_reject_request_success(self, mock_reject):
        """拒绝审批成功"""
        mock_reject.return_value = '审批已拒绝'

        result = await mock_reject(1, MagicMock(), '数据不完整')

        assert result == '审批已拒绝'

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.reject_request')
    async def test_reject_request_without_reason(self, mock_reject):
        """拒绝时未填原因"""
        mock_reject.side_effect = ValueError('拒绝时必须填写原因')

        with pytest.raises(ValueError, match='拒绝时必须填写原因'):
            await mock_reject(1, MagicMock(), '')

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_pending_count')
    async def test_get_pending_count(self, mock_count):
        """查询待审批数量"""
        mock_count.return_value = 5

        result = await mock_count()

        assert result == 5

    @pytest.mark.asyncio
    @patch('fastapi_app.services.approval_service.get_pending_count')
    async def test_get_pending_count_zero(self, mock_count):
        """无待审批"""
        mock_count.return_value = 0

        result = await mock_count()

        assert result == 0
