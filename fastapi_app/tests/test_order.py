"""
订单管理模块测试
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.schemas.order import OrderCreate, OrderUpdate
from fastapi_app.services import order_service
from fastapi_app.services.order_service import PermissionDeniedError
from fastapi_app.shared_models.approval import ApprovalRequest

# ==================== Schema 验证 ====================

class TestOrderSchemas:
    """订单 Pydantic Schema 测试"""

    def test_order_create_valid(self):
        data = OrderCreate(product_id=1, quantity=10, customer="测试客户")
        assert data.product_id == 1
        assert data.quantity == 10
        assert data.customer == "测试客户"
        assert data.note is None

    def test_order_create_invalid_quantity_zero(self):
        with pytest.raises(Exception):
            OrderCreate(product_id=1, quantity=0, customer="客户")

    def test_order_create_invalid_quantity_negative(self):
        with pytest.raises(Exception):
            OrderCreate(product_id=1, quantity=-1, customer="客户")

    def test_order_create_invalid_customer_empty(self):
        with pytest.raises(Exception):
            OrderCreate(product_id=1, quantity=10, customer="")

    def test_order_update_all_optional(self):
        data = OrderUpdate()
        assert data.product_id is None
        assert data.quantity is None
        assert data.customer is None


# ==================== Service 层测试 ====================

class TestOrderService:
    """订单 Service 测试"""

    async def test_get_orders_empty(self, mock_db):
        mock_data_result = MagicMock()
        mock_scalars = MagicMock()
        mock_unique = MagicMock()
        mock_unique.all.return_value = []
        mock_scalars.unique.return_value = mock_unique
        mock_data_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_data_result)
        with patch('fastapi_app.services.order.queries.optimized_count', new_callable=AsyncMock, return_value=0):
            result = await order_service.get_orders(mock_db)
        assert result['items'] == []
        assert result['total'] == 0

    async def test_create_order_product_not_found(self, mock_db):
        with patch('fastapi_app.services.order.commands.get_product_for_update', new_callable=AsyncMock, side_effect=ValueError('产品ID 999 不存在')):
            with pytest.raises(ValueError, match="产品ID 999 不存在"):
                await order_service.create_order(
                    mock_db, product_id=999, quantity=10,
                    customer="客户", note="", current_user=MagicMock()
                )

    async def test_create_order_success(self, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "产品A"
        product.current_stock = 100
        order = MagicMock()
        order.id = 1
        order.to_dict.return_value = {'id': 1, 'order_no': 'PO-001'}

        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch('fastapi_app.services.order.commands.get_product_for_update', new_callable=AsyncMock, return_value=product):
            with patch('fastapi_app.services.order.commands._generate_order_number', new_callable=AsyncMock, return_value="PO-001"):
                # 外发工序自动生成属于副作用（防御性封装，失败不影响主流程），单测中隔离
                with patch('fastapi_app.services.outsource_service.auto_generate_for_order', new_callable=AsyncMock):
                    # 缓存失效与事件发布（Redis/WS）同为副作用，单测中隔离，避免污染事件循环
                    with patch('fastapi_app.services.order.commands.cache_mgr') as mock_cache_mgr, \
                         patch('fastapi_app.services.order.commands._safe_invalidate_purchase_cache', new_callable=AsyncMock), \
                         patch('fastapi_app.services.order._common._safe_publish_event', new_callable=AsyncMock):
                        mock_cache_mgr.invalidate = AsyncMock()
                        result = await order_service.create_order(
                            mock_db, product_id=1, quantity=10,
                            customer="客户", note="", current_user=MagicMock()
                        )
        assert result['order_no'] == 'PO-001'

    async def test_update_order_not_found(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        user = MagicMock()
        with pytest.raises(ValueError, match="不存在"):
            await order_service.update_order(
                mock_db, order_id=999, quantity=10,
                customer="客户", note="", current_user=user
            )

    async def test_update_order_admin_success(self, mock_db):
        order = MagicMock()
        order.id = 1
        order.is_locked = False
        order.is_deleted = False
        order.locked_by_id = None
        order.quantity = 10
        order.customer = "旧客户"
        order.note = "旧备注"
        order.order_no = "PO-001"
        order.order_type = 'regular'
        order.product_id = 1

        product = MagicMock()
        product.id = 1

        user = MagicMock()
        user.is_super = True
        user.username = "admin"
        user.id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = order
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch('fastapi_app.services.order.commands.get_product_for_update', new_callable=AsyncMock, return_value=product):
            result = await order_service.update_order(
                mock_db, order_id=1, quantity=20,
                customer="新客户", note="新备注", current_user=user
            )
        assert result['success'] is True
        assert result['requires_approval'] is False

    async def test_delete_order_not_found(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        user = MagicMock()
        with pytest.raises(ValueError, match="不存在"):
            await order_service.delete_order(mock_db, order_id=999, current_user=user)

    async def test_cancel_approval_not_found(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        user = MagicMock()
        with pytest.raises(ValueError, match="不存在"):
            await order_service.cancel_approval(mock_db, 999, user)

    async def test_cancel_approval_already_processed(self, mock_db):
        approval = MagicMock()
        approval.requester_id = 1
        approval.status = ApprovalRequest.STATUS_APPROVED
        mock_db.get = AsyncMock(return_value=approval)
        user = MagicMock()
        user.id = 1
        user.is_super = False
        with pytest.raises(ValueError, match="无法取消"):
            await order_service.cancel_approval(mock_db, 1, user)

    async def test_cancel_approval_no_permission(self, mock_db):
        approval = MagicMock()
        approval.requester_id = 2
        approval.status = ApprovalRequest.STATUS_PENDING
        mock_db.get = AsyncMock(return_value=approval)
        user = MagicMock()
        user.id = 1
        user.is_super = False
        with pytest.raises(PermissionDeniedError, match="权限"):
            await order_service.cancel_approval(mock_db, 1, user)

    async def test_cancel_approval_success(self, mock_db):
        approval = MagicMock()
        approval.requester_id = 1
        approval.status = ApprovalRequest.STATUS_PENDING
        approval.order_id = 1

        order = MagicMock()
        order.is_locked = True
        order.is_deleted = False

        user = MagicMock()
        user.id = 1
        user.username = "test"
        user.is_super = False

        mock_db.get = AsyncMock(side_effect=[approval, order])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with patch('fastapi_app.services.order.approval_flow._create_approval_log_obj'):
            await order_service.cancel_approval(mock_db, 1, user)

        assert approval.status == ApprovalRequest.STATUS_CANCELLED

    async def test_get_my_approvals_empty(self, mock_db):
        user = MagicMock()
        user.id = 1
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_unique = MagicMock()
        mock_unique.all.return_value = []
        mock_scalars.unique.return_value = mock_unique
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await order_service.get_my_approvals(mock_db, user)
        assert result == []


# ==================== API 端点测试 ====================

class TestOrderEndpoints:
    """订单 API 端点测试"""

    async def test_list_orders(self, client, mock_db):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_unique = MagicMock()
        mock_unique.all.return_value = []
        mock_scalars.unique.return_value = mock_unique
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        response = await client.get("/api/v1/orders/list")
        assert response.status_code == 200
        assert response.json()['success'] is True

    async def test_create_order_success(self, client, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "产品"
        product.current_stock = 100
        order = MagicMock()
        order.id = 1
        order.to_dict.return_value = {'id': 1}

        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch('fastapi_app.services.order.commands.get_product_for_update', new_callable=AsyncMock, return_value=product):
            with patch('fastapi_app.services.order.commands._generate_order_number', new_callable=AsyncMock, return_value="PO-001"):
                # 外发工序自动生成属于副作用（防御性封装，失败不影响主流程），单测中隔离
                with patch('fastapi_app.services.outsource_service.auto_generate_for_order', new_callable=AsyncMock):
                    # 缓存失效与事件发布（Redis/WS）同为副作用，单测中隔离，避免污染事件循环
                    with patch('fastapi_app.services.order.commands.cache_mgr') as mock_cache_mgr, \
                         patch('fastapi_app.services.order.commands._safe_invalidate_purchase_cache', new_callable=AsyncMock), \
                         patch('fastapi_app.services.order._common._safe_publish_event', new_callable=AsyncMock):
                        mock_cache_mgr.invalidate = AsyncMock()
                        response = await client.post("/api/v1/orders/create", json={
                            "product_id": 1, "quantity": 10, "customer": "测试客户"
                        })
        assert response.status_code == 200
        assert response.json()['success'] is True

    async def test_create_order_invalid_data(self, client, mock_db):
        response = await client.post("/api/v1/orders/create", json={
            "product_id": 1, "quantity": 0, "customer": "客户"
        })
        assert response.status_code == 422

    async def test_edit_order_admin(self, client, mock_db):
        order = MagicMock()
        order.id = 1
        order.is_locked = False
        order.is_deleted = False
        order.locked_by_id = None
        order.quantity = 10
        order.customer = "旧客户"
        order.note = ""
        order.order_type = 'regular'
        order.product_id = 1

        product = MagicMock()
        product.id = 1

        user = MagicMock()
        user.is_super = True
        user.id = 1

        mock_db.get = AsyncMock(return_value=order)
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = order
        mock_db.execute = AsyncMock(return_value=mock_execute_result)
        mock_db.commit = AsyncMock()

        with patch('fastapi_app.services.order.commands.get_product_for_update', new_callable=AsyncMock, return_value=product), \
             patch('fastapi_app.services.order._common._safe_publish_event', new_callable=AsyncMock):
            response = await client.put("/api/v1/orders/edit/1", json={
                "quantity": 20, "customer": "新客户"
            })
        assert response.status_code == 200

    async def test_edit_order_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = await client.put("/api/v1/orders/edit/999", json={
            "quantity": 20, "customer": "客户"
        })
        assert response.status_code == 404

    async def test_delete_order_admin(self, client, mock_db):
        order = MagicMock()
        order.id = 1
        order.is_locked = False
        order.is_deleted = False
        order.locked_by_id = None
        order.order_no = "PO-001"
        order.product_id = 1
        order.quantity = 10
        order.status = "待备货"

        product = MagicMock()
        product.id = 1
        product.current_stock = 100

        mock_db.get = AsyncMock(return_value=order)
        mock_db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch('fastapi_app.services.order.commands.get_product_for_update', new_callable=AsyncMock, return_value=product):
            response = await client.delete("/api/v1/orders/delete/1")
        assert response.status_code == 200
        assert response.json()['success'] is True

    async def test_cancel_approval_success(self, client, mock_db):
        approval = MagicMock()
        approval.requester_id = 1
        approval.status = ApprovalRequest.STATUS_PENDING
        approval.order_id = 1

        order_obj = MagicMock()
        order_obj.is_locked = True
        order_obj.is_deleted = False

        mock_db.get = AsyncMock(side_effect=[approval, order_obj])
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        with patch('fastapi_app.services.order.approval_flow._create_approval_log_obj'):
            response = await client.post("/api/v1/orders/cancel-approval/1")
        assert response.status_code == 200
        assert response.json()['success'] is True

    async def test_my_approvals(self, client, mock_db):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_unique = MagicMock()
        mock_unique.all.return_value = []
        mock_scalars.unique.return_value = mock_unique
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        response = await client.get("/api/v1/orders/my-approvals")
        assert response.status_code == 200
        assert response.json()['success'] is True
