"""审批管理模块测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestApprovalSchemas:
    def test_approval_action_request(self):
        from fastapi_app.schemas.approval import ApprovalActionRequest
        data = ApprovalActionRequest(reason="不符合要求")
        assert data.reason == "不符合要求"

    def test_approval_action_request_optional(self):
        from fastapi_app.schemas.approval import ApprovalActionRequest
        data = ApprovalActionRequest()
        assert data.reason is None

    def test_approval_list_response(self):
        from fastapi_app.schemas.approval import ApprovalListResponse
        resp = ApprovalListResponse(data=[], pending_count=5)
        assert resp.pending_count == 5


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
        a.status = 'pending'
        a.operation_type = 'edit'
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
        mock_db.get = AsyncMock(return_value=mock_approval)
        mock_approval.requester_id = 1  # same as current user

        with pytest.raises(ValueError, match="不能审批自己"):
            await approve_request(mock_db, 1, mock_current_user)

    @pytest.mark.asyncio
    async def test_reject_success(self, mock_db, mock_approval, mock_current_user):
        from fastapi_app.services.approval_service import reject_request
        mock_db.get = AsyncMock(return_value=mock_approval)
        mock_approval.requester_id = 2

        result = await reject_request(mock_db, 1, mock_current_user, "不符合要求")
        assert mock_db.add.called
        assert "拒绝" in result


class TestApprovalEndpoints:
    @pytest.mark.asyncio
    async def test_pending_count(self, client, mock_db):
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
