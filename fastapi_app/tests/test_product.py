"""
产品管理模块测试
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from fastapi_app.schemas.product import ProductCreate, ProductUpdate
from fastapi_app.services import product_service

# ==================== Schema 验证 ====================

class TestProductSchemas:
    """产品 Pydantic Schema 测试"""

    def test_product_create_valid(self):
        data = ProductCreate(name="测试产品", barcode="690123", initial_stock=50)
        assert data.name == "测试产品"
        assert data.barcode == "690123"
        assert data.initial_stock == 50

    def test_product_create_name_required(self):
        with pytest.raises(ValidationError):
            ProductCreate()

    def test_product_create_negative_stock(self):
        with pytest.raises(ValidationError):
            ProductCreate(name="测试", initial_stock=-1)

    def test_product_create_large_stock(self):
        with pytest.raises(ValidationError):
            ProductCreate(name="测试", initial_stock=200000)

    def test_product_update_all_optional(self):
        data = ProductUpdate()
        assert data.name is None
        assert data.barcode is None
        assert data.initial_stock is None

    def test_product_update_partial(self):
        data = ProductUpdate(name="新名称")
        assert data.name == "新名称"
        assert data.barcode is None


# ==================== Service 层测试 ====================

class TestProductService:
    """产品 Service 测试"""

    async def test_get_products_empty(self, mock_db):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await product_service.get_products(mock_db)
        assert result == []

    async def test_create_product_success(self, mock_db):
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.to_dict.return_value = {'id': 1, 'name': '新产品'}

        # 检查唯一性: 返回 None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await product_service.create_product(
            mock_db, name="新产品", barcode="690", image=None, initial_stock=10
        )
        assert result['name'] == '新产品'

    async def test_create_product_duplicate_name(self, mock_db):
        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match="已存在"):
            await product_service.create_product(
                mock_db, name="重复产品", barcode=None, image=None, initial_stock=0
            )

    async def test_update_product_not_found(self, mock_db):
        with patch('fastapi_app.services.product_service.get_product_for_update', new_callable=AsyncMock, return_value=None):
            with pytest.raises(ValueError, match="不存在"):
                await product_service.update_product(mock_db, 999, name="x", barcode=None, image=None, initial_stock=None)

    async def test_update_product_success(self, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "旧名称"
        product.barcode = ""
        product.image = ""
        product.initial_stock = 10
        product.current_stock = 10
        product.to_dict.return_value = {'id': 1, 'name': '新名称'}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with patch('fastapi_app.services.product_service.get_product_for_update', new_callable=AsyncMock, return_value=product):
            result = await product_service.update_product(
                mock_db, 1, name="新名称", barcode=None, image=None, initial_stock=None
            )
        assert result['name'] == '新名称'

    async def test_delete_product_not_found(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(Exception, match="不存在"):
            await product_service.delete_product(mock_db, 999)

    async def test_delete_product_has_orders(self, mock_db):
        product = MagicMock()
        product.name = "测试产品"
        mock_db.get = AsyncMock(return_value=product)
        mock_count_result = MagicMock()
        mock_count_result.one.return_value = (5, 0, 0)
        mock_db.execute = AsyncMock(return_value=mock_count_result)
        with pytest.raises(Exception, match="关联.*订单"):
            await product_service.delete_product(mock_db, 1)

    async def test_delete_product_has_stockins(self, mock_db):
        product = MagicMock()
        product.name = "测试产品"
        mock_db.get = AsyncMock(return_value=product)
        mock_count_result = MagicMock()
        mock_count_result.one.return_value = (0, 5, 0)
        mock_db.execute = AsyncMock(return_value=mock_count_result)
        with pytest.raises(Exception, match="关联.*备货"):
            await product_service.delete_product(mock_db, 1)

    async def test_delete_product_has_stockouts(self, mock_db):
        product = MagicMock()
        product.name = "测试产品"
        mock_db.get = AsyncMock(return_value=product)
        mock_count_result = MagicMock()
        mock_count_result.one.return_value = (0, 0, 5)
        mock_db.execute = AsyncMock(return_value=mock_count_result)
        with pytest.raises(Exception, match="关联.*出货"):
            await product_service.delete_product(mock_db, 1)

    async def test_delete_product_success(self, mock_db):
        product = MagicMock()
        product.name = "测试产品"
        mock_db.get = AsyncMock(return_value=product)
        mock_count_result = MagicMock()
        mock_count_result.one.return_value = (0, 0, 0)
        mock_delete_result = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_delete_result])
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        await product_service.delete_product(mock_db, 1)
        mock_db.delete.assert_called()

    async def test_search_products(self, mock_db):
        p1, p2 = MagicMock(), MagicMock()
        p1.id, p1.name, p1.barcode, p1.current_stock = 1, "A", "111", 10
        p2.id, p2.name, p2.barcode, p2.current_stock = 2, "B", "222", 20
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [p1, p2]
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await product_service.search_products(mock_db, "A")
        assert len(result) == 2

    async def test_get_product_stock_not_found(self, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="不存在"):
            await product_service.get_product_stock(mock_db, 999)

    async def test_get_product_stock_success(self, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "测试"
        product.current_stock = 100
        mock_db.get = AsyncMock(return_value=product)
        result = await product_service.get_product_stock(mock_db, 1)
        assert result['current_stock'] == 100


# ==================== API 端点测试 ====================

class TestProductEndpoints:
    """产品 API 端点测试"""

    async def test_list_products(self, client, mock_db):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        response = await client.get("/api/v1/products/list")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True

    async def test_create_product_success(self, client, mock_db):
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.to_dict.return_value = {'id': 1, 'name': '测试'}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        response = await client.post("/api/v1/products/create", json={
            "name": "测试产品", "barcode": "690", "initial_stock": 10
        })
        assert response.status_code == 200
        assert response.json()['success'] is True

    async def test_create_product_duplicate(self, client, mock_db):
        existing = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute = AsyncMock(return_value=mock_result)
        response = await client.post("/api/v1/products/create", json={
            "name": "重复产品", "initial_stock": 0
        })
        assert response.status_code == 400

    async def test_edit_product_success(self, client, mock_db):
        product = MagicMock()
        product.name = "旧名称"
        product.barcode = ""
        product.image = ""
        product.initial_stock = 0
        product.current_stock = 0
        product.to_dict.return_value = {'id': 1, 'name': '新名称'}
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        with patch('fastapi_app.services.product_service.get_product_for_update', new_callable=AsyncMock, return_value=product):
            response = await client.put("/api/v1/products/edit/1", json={"name": "新名称"})
        assert response.status_code == 200
        assert response.json()['success'] is True

    async def test_edit_product_not_found(self, client, mock_db):
        with patch('fastapi_app.services.product_service.get_product_for_update', new_callable=AsyncMock, return_value=None):
            response = await client.put("/api/v1/products/edit/999", json={"name": "x"})
        assert response.status_code == 400

    async def test_delete_product_success(self, client, mock_db):
        product = MagicMock()
        product.name = "测试产品"
        mock_db.get = AsyncMock(return_value=product)
        mock_count_result = MagicMock()
        mock_count_result.one.return_value = (0, 0, 0)
        mock_delete_result = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_delete_result])
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()
        response = await client.delete("/api/v1/products/delete/1")
        assert response.status_code == 200

    async def test_delete_product_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = await client.delete("/api/v1/products/delete/999")
        assert response.status_code == 400

    async def test_delete_product_has_orders(self, client, mock_db):
        product = MagicMock()
        product.name = "测试产品"
        mock_db.get = AsyncMock(return_value=product)
        mock_count_result = MagicMock()
        mock_count_result.one.return_value = (5, 0, 0)
        mock_db.execute = AsyncMock(return_value=mock_count_result)
        response = await client.delete("/api/v1/products/delete/1")
        assert response.status_code == 400
        assert "订单" in response.json()["detail"]

    async def test_search_products_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        response = await client.get("/api/v1/products/search?q=test")
        assert response.status_code == 200

    async def test_available_stock_endpoint(self, client, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "测试"
        product.current_stock = 100
        mock_db.get = AsyncMock(return_value=product)
        response = await client.get("/api/v1/products/available-stock?product_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data['current_stock'] == 100

    async def test_available_stock_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)
        response = await client.get("/api/v1/products/available-stock?product_id=999")
        assert response.status_code == 400
