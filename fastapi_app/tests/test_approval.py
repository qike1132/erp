"""审批管理模块测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.shared_models.approval import ApprovalLog, ApprovalRequest


class TestApprovalSchemas:
    def test_approval_action_request(self):
        from fastapi_app.schemas.approval import ApprovalActionRequest
        data = ApprovalActionRequest(reason="不符合要求")
        assert data.reason == "不符合要求"

    def test_approval_action_request_optional(self):
        from fastapi_app.schemas.approval import ApprovalActionRequest
        data = ApprovalActionRequest()
        assert data.reason is None

    def test_approval_action_request_max_length(self):
        from fastapi_app.schemas.approval import ApprovalActionRequest
        data = ApprovalActionRequest(reason="a" * 500)
        assert len(data.reason) == 500

    def test_approval_list_response(self):
        from fastapi_app.schemas.approval import ApprovalListResponse
        resp = ApprovalListResponse(data=[], pending_count=5)
        assert resp.pending_count == 5

    def test_approval_item_schema(self):
        from fastapi_app.schemas.approval import ApprovalItemSchema
        item = ApprovalItemSchema(
            id=1, order_id=10, order_no="ORD-001",
            requester_id=2, requester_name="user1",
            operation_type="edit", operation_type_display="编辑",
            status="pending", status_display="待审批",
        )
        assert item.id == 1
        assert item.operation_type == "edit"


class TestApprovalModelConstants:
    def test_operation_type_constants(self):
        assert ApprovalRequest.OPERATION_EDIT == 'edit'
        assert ApprovalRequest.OPERATION_DELETE == 'delete'

    def test_status_constants(self):
        assert ApprovalRequest.STATUS_PENDING == 'pending'
        assert ApprovalRequest.STATUS_APPROVED == 'approved'
        assert ApprovalRequest.STATUS_REJECTED == 'rejected'
        assert ApprovalRequest.STATUS_CANCELLED == 'cancelled'

    def test_action_constants(self):
        assert ApprovalLog.ACTION_CREATE == 'create'
        assert ApprovalLog.ACTION_APPROVE == 'approve'
        assert ApprovalLog.ACTION_REJECT == 'reject'
        assert ApprovalLog.ACTION_CANCEL == 'cancel'
        assert ApprovalLog.ACTION_EXECUTE == 'execute'


class TestApprovalService:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.delete = AsyncMock()
        db.add = MagicMock()
        db.execute = AsyncMock()
        db.get = AsyncMock()
        return db

    @pytest.fixture
    def mock_approval(self):
        a = MagicMock()
        a.id = 1
        a.status = ApprovalRequest.STATUS_PENDING
        a.operation_type = ApprovalRequest.OPERATION_EDIT
        a.operation_type_display = '编辑'
        a.operation_data = '{"quantity": 100}'
        a.requester_id = 2
        a.order_id = 1
        a.approver_id = None
        a.approval_time = None
        a.rejection_reason = None
        a.logs = []
        a.order = None
        a.to_dict = MagicMock(return_value={'id': 1, 'status': 'pending'})
        return a

    @pytest.fixture
    def mock_current_user(self):
        user = MagicMock()
        user.id = 1
        user.username = "admin"
        user.is_super = True
        return user

    @pytest.mark.asyncio
    async def test_get_pending_count(self, mock_db):
        from fastapi_app.services.approval_service import get_pending_count
        mock_result = MagicMock()
        mock_result.scalar.return_value = 5
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await get_pending_count(mock_db)
        assert count == 5

    @pytest.mark.asyncio
    async def test_approve_self_raises(self, mock_db, mock_approval, mock_current_user):
        from fastapi_app.services.approval_service import approve_request
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_approval
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_approval.requester_id = 1

        with pytest.raises(ValueError, match="不能审批自己"):
            await approve_request(mock_db, 1, mock_current_user)

    @pytest.mark.asyncio
    async def test_reject_success(self, mock_db, mock_approval, mock_current_user):
        from fastapi_app.services.approval_service import reject_request
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_approval
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.get = AsyncMock(return_value=None)
        mock_approval.requester_id = 2

        result = await reject_request(mock_db, 1, mock_current_user, "不符合要求")
        assert mock_db.add.called
        assert "拒绝" in result

    @pytest.mark.asyncio
    async def test_approve_nonexistent_raises(self, mock_db, mock_current_user):
        from fastapi_app.services.approval_service import approve_request
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="审批请求不存在"):
            await approve_request(mock_db, 999, mock_current_user)

    @pytest.mark.asyncio
    async def test_approve_already_processed_raises(self, mock_db, mock_approval, mock_current_user):
        from fastapi_app.services.approval_service import approve_request
        mock_approval.status = ApprovalRequest.STATUS_APPROVED
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_approval
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="审批请求状态异常"):
            await approve_request(mock_db, 1, mock_current_user)

    @pytest.mark.asyncio
    async def test_validate_not_self_approval(self, mock_approval, mock_current_user):
        from fastapi_app.services.approval_service import _validate_not_self_approval
        mock_approval.requester_id = 1

        with pytest.raises(ValueError, match="不能审批自己"):
            _validate_not_self_approval(mock_approval, mock_current_user)

    @pytest.mark.asyncio
    async def test_validate_not_self_approval_passes(self, mock_approval, mock_current_user):
        from fastapi_app.services.approval_service import _validate_not_self_approval
        mock_approval.requester_id = 2
        _validate_not_self_approval(mock_approval, mock_current_user)

    @pytest.mark.asyncio
    async def test_approve_edit_dispatches_handler(self, mock_db, mock_approval, mock_current_user):
        """回归：approve_request 必须真正穿过 _OPERATION_HANDLERS 派发（B1）。

        历史：三个 approve_request 用例都在前置校验（自审批/不存在/状态）处 raise，
        从未走到 handler 派发行；ff67a6cd 把调用点改成 4 参后 _handle_edit_approval
        仍是 3 参，编辑审批点同意即 TypeError → 500，测试全绿。
        本用例 requester_id != approver_id、状态 pending，确保派发路径被执行。
        """
        import json as _json

        from fastapi_app.services import approval_service
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_approval
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_approval.requester_id = 2
        mock_approval.status = ApprovalRequest.STATUS_PENDING
        mock_approval.operation_type = ApprovalRequest.OPERATION_EDIT
        mock_approval.operation_data = _json.dumps({'quantity': 100, 'customer': '客户A'})
        mock_order = MagicMock()
        mock_order.id = 1
        mock_order.order_no = 'ORD-001'
        mock_order.is_deleted = False
        mock_order.quantity = 50
        mock_order.customer = '客户B'
        mock_order.product_id = 1
        mock_order.note = '旧备注'
        mock_db.get = AsyncMock(return_value=mock_order)
        # P1-03：approve 现在先预锁产品、再 select(Order).with_for_update()；
        # 桩让该查询返回同一个 mock_order（生产中是身份映射的同一实例）。
        mock_result.scalar_one.return_value = mock_order

        # handler 内部依赖（预锁产品、明细同步、状态重算、审批日志）全部打桩
        with patch.object(approval_service, 'get_product_for_update', new=AsyncMock()) as m_lock, \
             patch.object(approval_service, 'sync_single_item_quantity', new=AsyncMock()) as m_sync, \
             patch.object(approval_service, 'compute_order_status_from_db',
                          new=AsyncMock(return_value='partially_deducted')) as m_status, \
             patch.object(approval_service, '_create_approval_log', new=AsyncMock()):
            result = await approval_service.approve_request(mock_db, 1, mock_current_user)

        # 数量已按 operation_data 应用，明细同步与状态重算被调用
        assert mock_order.quantity == 100
        assert mock_order.customer == '客户A'
        assert m_lock.await_count == 1
        assert m_sync.await_count == 1
        assert m_status.await_count == 1
        assert mock_approval.status == ApprovalRequest.STATUS_APPROVED
        assert "已同意" in result['message']

    @pytest.mark.asyncio
    async def test_operation_handlers_signature_contract(self):
        """守卫：注册表内所有 handler 必须可按派发点的 4 参形态 bind（B1 根因）。"""
        import inspect

        from fastapi_app.services.approval_service import _OPERATION_HANDLERS
        for operation, handler in _OPERATION_HANDLERS.items():
            sig = inspect.signature(handler)
            try:
                sig.bind('db', 'approval', 'order', 'user')
            except TypeError as e:
                pytest.fail(f'{operation} 的 handler {handler.__name__} 无法按 4 参派发: {e}')


class TestApprovalEndpoints:
    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::ResourceWarning")
    async def test_pending_count(self, client, mock_db):
        """已知 teardown 竞态：asyncpg 连接池在 atexit 清理时 event loop 已关闭。
        测试本身逻辑正确（单跑必过），全套跑时受前序测试遗留的池连接影响。
        批次3 已将 conftest 的 redis/audit/engine patch 全部对齐到新路径，救活 16 个测试；
        此 error 为 Windows + asyncpg + pytest-asyncio 三方固有限制，标记跳过以保持 CI 信号干净。
        """
        mock_result = MagicMock()
        mock_result.scalar.return_value = 3
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/approvals/pending-count")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 3

    @pytest.mark.asyncio
    async def test_approval_list(self, client, mock_db):
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_stats_result = MagicMock()
        mock_stats_result.all.return_value = []
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_result, mock_stats_result])

        response = await client.get("/api/v1/approvals/list")
        assert response.status_code == 200
