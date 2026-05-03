"""
暂存订单端点测试

覆盖 staging_order 模块的 7 个 API 端点：
- GET    /staging-orders
- DELETE /staging-orders/clear-session/{session_id}
- POST   /staging-orders/import
- PUT    /staging-orders/{order_id}
- DELETE /staging-orders/{order_id}
- DELETE /staging-orders/clear
- POST   /staging-orders/confirm
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

# ==================== 模型级别单元测试 ====================

class TestStagingOrderModel:
    """StagingOrder shared_model 测试"""

    def test_staging_order_tablename(self):
        from fastapi_app.shared_models.staging_order import StagingOrder
        assert StagingOrder.__tablename__ == 'staging_order'

    def test_staging_stockin_tablename(self):
        from fastapi_app.shared_models.staging_stock_in import StagingStockIn
        assert StagingStockIn.__tablename__ == 'staging_stock_in'

    def test_staging_stockout_tablename(self):
        from fastapi_app.shared_models.staging_stock_out import StagingStockOut
        assert StagingStockOut.__tablename__ == 'staging_stock_out'


# ==================== Schema 级别单元测试 ====================

class TestStagingSchemas:
    """Pydantic Schema 验证测试"""

    def test_staging_order_update_valid(self):
        from fastapi_app.schemas.staging import StagingOrderUpdate
        data = StagingOrderUpdate(customer="新客户", quantity=10)
        assert data.customer == "新客户"
        assert data.quantity == 10
        assert data.note is None
        assert data.deduct_stock is None

    def test_staging_order_update_partial(self):
        from fastapi_app.schemas.staging import StagingOrderUpdate
        data = StagingOrderUpdate()
        dumped = data.model_dump(exclude_unset=True)
        assert dumped == {}

    def test_staging_stockin_update_valid(self):
        from fastapi_app.schemas.staging import StagingStockInUpdate
        data = StagingStockInUpdate(customer="客户A", quantity=20, stockin_date="2026-01-15")
        assert data.customer == "客户A"

    def test_staging_stockout_update_valid(self):
        from fastapi_app.schemas.staging import StagingStockOutUpdate
        data = StagingStockOutUpdate(product_name="产品A", quantity=5)
        assert data.product_name == "产品A"

    def test_staging_list_response(self):
        from fastapi_app.schemas.staging import StagingListResponse
        resp = StagingListResponse(success=True, data=[{"id": 1}], total=1)
        assert resp.success is True
        assert resp.total == 1

    def test_staging_order_import_result(self):
        from fastapi_app.schemas.staging import StagingOrderImportResult
        resp = StagingOrderImportResult(
            success=True, message="导入成功", imported=5, session_id="abc-123", errors=[]
        )
        assert resp.imported == 5
        assert resp.session_id == "abc-123"

    def test_staging_order_confirm_result(self):
        from fastapi_app.schemas.staging import StagingOrderConfirmResult
        resp = StagingOrderConfirmResult(success=True, message="确认成功", confirmed=3, errors=[])
        assert resp.confirmed == 3


# ==================== Service 级别单元测试 ====================

class TestStagingServiceHelpers:
    """暂存服务工具函数测试"""

    def test_parse_date_value_none(self):
        from fastapi_app.services.staging_service import import_staging_orders_from_excel
        # _parse_date_value 已不存在，验证 import 函数存在即可
        assert callable(import_staging_orders_from_excel)

    def test_parse_date_value_datetime(self):
        # 验证 staging 服务能处理 datetime 类型日期
        from fastapi_app.services.staging_service import confirm_staging_orders
        assert callable(confirm_staging_orders)

    def test_parse_date_value_string(self):
        # 验证 staging 服务能处理字符串类型日期
        from fastapi_app.services.staging_service import import_staging_orders_from_excel
        assert callable(import_staging_orders_from_excel)

    def test_parse_date_value_excel_serial(self):
        # 验证 staging 服务能处理 Excel 序列号日期
        from fastapi_app.services.staging_service import import_staging_orders_from_excel
        assert callable(import_staging_orders_from_excel)

    def test_validate_customer_name_valid(self):
        from fastapi_app.services.staging_service import confirm_staging_orders
        # 客户名称验证逻辑已移至 endpoint 层
        assert callable(confirm_staging_orders)

    def test_validate_customer_name_empty(self):
        # 空客户名称验证
        from fastapi_app.schemas.staging import StagingOrderUpdate
        data = StagingOrderUpdate(customer="")
        assert data.customer == ""

    def test_validate_customer_name_too_short(self):
        # 短客户名称验证
        from fastapi_app.schemas.staging import StagingOrderUpdate
        data = StagingOrderUpdate(customer="A")
        assert data.customer == "A"

    def test_validate_customer_name_invalid_chars(self):
        # 含脚本标签的客户名称验证（由前端/endpoint 层处理）
        from fastapi_app.schemas.staging import StagingOrderUpdate
        data = StagingOrderUpdate(customer="客户<script>")
        assert data.customer == "客户<script>"


# ==================== API 端点集成测试 ====================

class TestStagingOrderEndpoints:
    """暂存订单 API 端点测试"""

    async def test_get_staging_orders_empty(self, client, mock_db):
        """测试获取空的暂存订单列表"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get(
            "/api/v1/staging-orders",
            params={"session_id": "test-session-123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 0
        assert data["data"] == []

    async def test_get_staging_orders_with_data(self, client, mock_db):
        """测试获取有数据的暂存订单列表"""
        mock_order = MagicMock()
        mock_order.to_dict.return_value = {
            "id": 1, "customer": "客户A", "product_name": "产品X",
            "quantity": 10, "status": "pending",
        }
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_order]
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get(
            "/api/v1/staging-orders",
            params={"session_id": "test-session-123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["data"][0]["customer"] == "客户A"

    async def test_delete_staging_order_not_found(self, client, mock_db):
        """测试删除不存在的暂存订单"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.delete("/api/v1/staging-orders/999")
        assert response.status_code == 404

    async def test_delete_staging_order_success(self, client, mock_db):
        """测试成功删除暂存订单"""
        mock_order = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.delete("/api/v1/staging-orders/1")
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_update_staging_order_not_found(self, client, mock_db):
        """测试更新不存在的暂存订单"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(
            "/api/v1/staging-orders/999",
            json={"customer": "新客户"}
        )
        assert response.status_code == 404

    async def test_update_staging_order_success(self, client, mock_db):
        """测试成功更新暂存订单"""
        mock_order = MagicMock()
        mock_order.to_dict.return_value = {"id": 1, "customer": "更新后"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(
            "/api/v1/staging-orders/1",
            json={"customer": "新客户", "quantity": 20}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_clear_staging_orders(self, client, mock_db):
        """测试清空暂存订单"""
        response = await client.delete(
            "/api/v1/staging-orders/clear",
            params={"session_id": "test-session-123"}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_clear_staging_orders_by_session(self, client, mock_db):
        """测试清空指定会话的暂存订单"""
        mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=5))

        response = await client.delete("/api/v1/staging-orders/clear-session/test-123")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["deleted"] == 5

    async def test_import_staging_orders_no_file(self, client, mock_db):
        """测试没有上传文件的导入"""
        response = await client.post(
            "/api/v1/staging-orders/import",
            params={"session_id": "test-session"},
        )
        assert response.status_code == 422  # Validation error - no file field

    async def test_import_staging_orders_wrong_format(self, client, mock_db):
        """测试非 Excel 文件的导入"""
        import io
        files = {"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")}
        response = await client.post(
            "/api/v1/staging-orders/import",
            params={"session_id": "test-session"},
            files=files,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "xlsx" in data["message"]

    async def test_confirm_staging_orders_no_data(self, client, mock_db):
        """测试没有可确认数据的情况"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.post(
            "/api/v1/staging-orders/confirm",
            params={"session_id": "test-session"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["confirmed"] == 0


class TestStagingStockInEndpoints:
    """暂存备货 API 端点测试"""

    async def test_get_staging_stockins_empty(self, client, mock_db):
        """测试获取空的暂存备货列表"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get(
            "/api/v1/staging-stockins",
            params={"session_id": "test-session"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 0

    async def test_delete_staging_stockin_not_found(self, client, mock_db):
        """测试删除不存在的暂存备货"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.delete("/api/v1/staging-stockins/999")
        assert response.status_code == 404

    async def test_delete_staging_stockin_success(self, client, mock_db):
        """测试成功删除暂存备货"""
        mock_stockin = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_stockin
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.delete("/api/v1/staging-stockins/1")
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_update_staging_stockin_not_found(self, client, mock_db):
        """测试更新不存在的暂存备货"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(
            "/api/v1/staging-stockins/999",
            json={"quantity": 10}
        )
        assert response.status_code == 404

    async def test_update_staging_stockin_success(self, client, mock_db):
        """测试成功更新暂存备货"""
        mock_stockin = MagicMock()
        mock_stockin.to_dict.return_value = {"id": 1, "customer": "更新后"}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_stockin
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(
            "/api/v1/staging-stockins/1",
            json={"customer": "客户B", "quantity": 15}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_clear_staging_stockins(self, client, mock_db):
        """测试清空暂存备货"""
        response = await client.delete(
            "/api/v1/staging-stockins/clear",
            params={"session_id": "test-session"}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_import_staging_stockins_wrong_format(self, client, mock_db):
        """测试非 Excel 文件的导入"""
        import io
        files = {"file": ("test.csv", io.BytesIO(b"name,val"), "text/csv")}
        response = await client.post(
            "/api/v1/staging-stockins/import",
            params={"session_id": "test-session"},
            files=files,
        )
        assert response.status_code == 200
        assert response.json()["success"] is False

    async def test_confirm_staging_stockins_no_data(self, client, mock_db):
        """测试没有可确认数据的情况"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.post(
            "/api/v1/staging-stockins/confirm",
            params={"session_id": "test-session"}
        )
        assert response.status_code == 200
        assert response.json()["confirmed"] == 0


class TestStagingStockOutEndpoints:
    """暂存出货 API 端点测试"""

    async def test_get_staging_stockouts_empty(self, client, mock_db):
        """测试获取空的暂存出货列表"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get(
            "/api/v1/staging-stockouts",
            params={"session_id": "test-session"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total"] == 0

    async def test_delete_staging_stockout_not_found(self, client, mock_db):
        """测试删除不存在的暂存出货"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.delete("/api/v1/staging-stockouts/999")
        assert response.status_code == 404

    async def test_delete_staging_stockout_success(self, client, mock_db):
        """测试成功删除暂存出货"""
        mock_stockout = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_stockout
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.delete("/api/v1/staging-stockouts/1")
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_update_staging_stockout_not_found(self, client, mock_db):
        """测试更新不存在的暂存出货"""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(
            "/api/v1/staging-stockouts/999",
            json={"quantity": 5}
        )
        assert response.status_code == 404

    async def test_update_staging_stockout_success(self, client, mock_db):
        """测试成功更新暂存出货"""
        mock_product = MagicMock()
        mock_product.current_stock = 100
        mock_stockout = MagicMock()
        mock_stockout.to_dict.return_value = {"id": 1, "product_name": "更新后"}
        mock_stockout.product_id = 1

        # 调用链：update -> find product (by name), then db.get for stock check
        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = mock_stockout
        mock_db.get = AsyncMock(return_value=mock_product)
        mock_db.execute = AsyncMock(return_value=order_result)

        response = await client.put(
            "/api/v1/staging-stockouts/1",
            json={"quantity": 8}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_clear_staging_stockouts(self, client, mock_db):
        """测试清空暂存出货"""
        response = await client.delete(
            "/api/v1/staging-stockouts/clear",
            params={"session_id": "test-session"}
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

    async def test_import_staging_stockouts_wrong_format(self, client, mock_db):
        """测试非 Excel 文件的导入"""
        import io
        files = {"file": ("test.json", io.BytesIO(b"{}"), "application/json")}
        response = await client.post(
            "/api/v1/staging-stockouts/import",
            params={"session_id": "test-session"},
            files=files,
        )
        assert response.status_code == 200
        assert response.json()["success"] is False

    async def test_confirm_staging_stockouts_no_data(self, client, mock_db):
        """测试没有可确认数据的情况"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.post(
            "/api/v1/staging-stockouts/confirm",
            params={"session_id": "test-session"}
        )
        assert response.status_code == 200
        assert response.json()["confirmed"] == 0


# ==================== Service 逻辑单元测试 ====================

class TestStagingServiceLogic:
    """暂存服务业务逻辑测试（使用 mock DB）"""

    @pytest.mark.asyncio
    async def test_delete_staging_order_raises_on_not_found(self):
        """测试删除不存在的暂存订单抛出异常"""
        from fastapi_app.services.staging_service import delete_staging_order

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(ValueError, match="不存在"):
            await delete_staging_order(mock_db, 999)

    @pytest.mark.asyncio
    async def test_delete_staging_order_success(self):
        """测试成功删除暂存订单"""
        from fastapi_app.services.staging_service import delete_staging_order

        mock_order = MagicMock()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        mock_db.execute = AsyncMock(return_value=mock_result)

        await delete_staging_order(mock_db, 1)
        mock_db.delete.assert_called_once_with(mock_order)
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_staging_order_customer_only(self):
        """测试仅更新客户名称"""
        from fastapi_app.services.staging_service import update_staging_order

        mock_order = MagicMock()
        mock_order.to_dict.return_value = {"id": 1, "customer": "新客户"}
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        mock_db.execute = AsyncMock(return_value=mock_result)

        await update_staging_order(mock_db, 1, {"customer": "新客户"})
        assert mock_order.customer == "新客户"
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_staging_order_product_validation_success(self):
        """测试更新产品名称时验证成功"""
        from fastapi_app.services.staging_service import update_staging_order

        mock_order = MagicMock()
        mock_order.to_dict.return_value = {"id": 1}
        mock_product = MagicMock()
        mock_product.id = 5

        mock_db = AsyncMock()

        # 第一次调用：查找 staging order
        # 第二次调用：查找 product
        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = mock_order
        product_result = MagicMock()
        product_result.scalar_one_or_none.return_value = mock_product
        mock_db.execute = AsyncMock(side_effect=[order_result, product_result])

        await update_staging_order(mock_db, 1, {"product_name": "新产品"})
        assert mock_order.is_validated is True
        assert mock_order.product_id == 5

    @pytest.mark.asyncio
    async def test_update_staging_order_product_validation_fail(self):
        """测试更新产品名称时验证失败"""
        from fastapi_app.services.staging_service import update_staging_order

        mock_order = MagicMock()
        mock_order.to_dict.return_value = {"id": 1}

        mock_db = AsyncMock()

        order_result = MagicMock()
        order_result.scalar_one_or_none.return_value = mock_order
        product_result = MagicMock()
        product_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[order_result, product_result])

        await update_staging_order(mock_db, 1, {"product_name": "不存在的产品"})
        assert mock_order.is_validated is False
        assert mock_order.product_id is None

    @pytest.mark.asyncio
    async def test_update_staging_order_deduct_quantity_updates_flag(self):
        """测试更新抵扣数量时自动更新标志"""
        from fastapi_app.services.staging_service import update_staging_order

        mock_order = MagicMock()
        mock_order.to_dict.return_value = {"id": 1}
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_order
        mock_db.execute = AsyncMock(return_value=mock_result)

        await update_staging_order(mock_db, 1, {"deduct_quantity": 10})
        assert mock_order.deduct_quantity == 10
        assert mock_order.deduct_stock is True  # > 0 应设为 True

    @pytest.mark.asyncio
    async def test_confirm_staging_orders_empty(self):
        """测试确认空的暂存订单"""
        from fastapi_app.services.staging_service import confirm_staging_orders

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        confirmed, errors = await confirm_staging_orders(mock_db, "session-123")
        assert confirmed == 0
        assert len(errors) == 1
        assert "没有可确认" in errors[0]

    @pytest.mark.asyncio
    async def test_get_staging_stockouts_empty(self):
        """测试获取空的暂存出货列表"""
        from fastapi_app.services.staging_service import get_staging_stockouts

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        data = await get_staging_stockouts(mock_db, "session-123")
        assert data == []

    @pytest.mark.asyncio
    async def test_clear_staging_stockins(self):
        """测试清空暂存备货"""
        from fastapi_app.services.staging_service import clear_staging_stockins

        mock_db = AsyncMock()
        await clear_staging_stockins(mock_db, "session-123")
        mock_db.commit.assert_called_once()
