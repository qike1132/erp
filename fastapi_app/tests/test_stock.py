"""
库存管理模块测试
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.schemas.stock import StockInCreate, StockInUpdate, StockOutCreate
from fastapi_app.services import stock_service

# ==================== Schema 验证 ====================

class TestStockSchemas:
    """库存 Pydantic Schema 测试"""

    def test_stockin_create_valid(self):
        data = StockInCreate(
            product_id=1, quantity=10, customer="客户",
            stockin_date="2026-01-15"
        )
        assert data.product_id == 1
        assert data.quantity == 10

    def test_stockin_create_invalid_quantity(self):
        with pytest.raises(Exception):
            StockInCreate(product_id=1, quantity=0, customer="客户", stockin_date="2026-01-15")

    def test_stockin_update_all_optional(self):
        data = StockInUpdate()
        assert data.quantity is None
        assert data.customer is None

    def test_stockout_create_valid(self):
        data = StockOutCreate(
            product_id=1, quantity=10, customer="客户",
            stockout_date="2026-01-15"
        )
        assert data.product_id == 1

    def test_stockout_create_invalid_quantity(self):
        with pytest.raises(Exception):
            StockOutCreate(product_id=1, quantity=-5, customer="客户", stockout_date="2026-01-15")


# ==================== Service 层测试 ====================

class TestStockInService:
    """入库 Service 测试"""

    async def test_get_stockins_empty(self, mock_db):
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_data_result = MagicMock()
        mock_data_scalars = MagicMock()
        mock_data_unique = MagicMock()
        mock_data_unique.all.return_value = []
        mock_data_scalars.unique.return_value = mock_data_unique
        mock_data_result.scalars.return_value = mock_data_scalars
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])
        result = await stock_service.get_stockins(mock_db)
        assert result['items'] == []
        assert result['total'] == 0

    async def test_create_stockin_product_not_found(self, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        with patch('fastapi_app.services.stock_service.create_stockin_core', new_callable=AsyncMock, side_effect=ValueError('产品ID 999 不存在')):
            with pytest.raises(ValueError, match="产品ID 999 不存在"):
                await stock_service.create_stockin(
                    mock_db, product_id=999, quantity=10,
                    customer="客户", stockin_date_str="2026-01-15", note=""
                )

    async def test_create_stockin_success(self, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "产品A"
        product.current_stock = 100

        stockin = MagicMock()
        stockin.id = 1
        stockin.stockin_no = "BH-001"

        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)

        with patch('fastapi_app.services.stock_service.create_stockin_core', new_callable=AsyncMock, return_value=stockin):
            with patch('fastapi_app.services.stock_service.publish_stock_event', new_callable=AsyncMock):
                result = await stock_service.create_stockin(
                    mock_db, product_id=1, quantity=10,
                    customer="客户", stockin_date_str="2026-01-15", note=""
                )
        assert 'stockin_no' in result

    async def test_update_stockin_not_found(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match="不存在"):
            await stock_service.update_stockin(
                mock_db, stockin_id=999, quantity=10,
                customer="客户", stockin_date_str="2026-01-15", note=""
            )

    async def test_delete_stockin_not_found(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match="不存在"):
            await stock_service.delete_stockin(mock_db, 999)

    async def test_delete_stockin_has_stockouts(self, mock_db):
        stockin = MagicMock()
        stockin.id = 1
        stockin.stockin_no = "BH-001"
        stockin.quantity = 10
        stockin.stockin_stockouts = [MagicMock(quantity=5)]
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stockin
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match="已有出库关联"):
            await stock_service.delete_stockin(mock_db, 1)

    async def test_delete_stockin_success(self, mock_db):
        stockin = MagicMock()
        stockin.id = 1
        stockin.stockin_no = "BH-001"
        stockin.quantity = 10
        stockin.product_id = 1
        stockin.stockin_stockouts = []

        product = MagicMock()
        product.id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stockin
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        with patch('fastapi_app.services.stock_service.delete_stockin_core', new_callable=AsyncMock, return_value=None) as mock_delete:
            await stock_service.delete_stockin(mock_db, 1)
        mock_delete.assert_awaited_once()


class TestStockOutService:
    """出库 Service 测试"""

    async def test_get_stockouts_empty(self, mock_db):
        mock_count_result = MagicMock()
        mock_count_result.scalar.return_value = 0
        mock_data_result = MagicMock()
        mock_data_scalars = MagicMock()
        mock_data_unique = MagicMock()
        mock_data_unique.all.return_value = []
        mock_data_scalars.unique.return_value = mock_data_unique
        mock_data_result.scalars.return_value = mock_data_scalars
        mock_db.execute = AsyncMock(side_effect=[mock_count_result, mock_data_result])
        result = await stock_service.get_stockouts(mock_db)
        assert result['items'] == []
        assert result['total'] == 0

    async def test_create_stockout_product_not_found(self, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        with patch('fastapi_app.services.stock_service.create_stockout_core', new_callable=AsyncMock, side_effect=ValueError('产品ID 999 不存在')):
            with pytest.raises(ValueError, match="产品ID 999 不存在"):
                await stock_service.create_stockout(
                    mock_db, product_id=999, quantity=10,
                    customer="客户", stockout_date_str="2026-01-15", note=""
                )

    async def test_create_stockout_insufficient_stock(self, mock_db):
        product = MagicMock()
        product.id = 1
        product.current_stock = 5
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        with patch('fastapi_app.services.stock_service.create_stockout_core', new_callable=AsyncMock, side_effect=ValueError('库存不足')):
            with pytest.raises(ValueError, match="库存不足"):
                await stock_service.create_stockout(
                    mock_db, product_id=1, quantity=10,
                    customer="客户", stockout_date_str="2026-01-15", note=""
                )

    async def test_update_stockout_not_found(self, mock_db):
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match="不存在"):
            await stock_service.update_stockout(
                mock_db, stockout_id=999, new_quantity=10,
                customer="客户", stockout_date_str="2026-01-15", note=""
            )

    async def test_update_stockout_is_deduction(self, mock_db):
        pid_result = MagicMock()
        pid_result.one_or_none.return_value = (1,)
        stockout = MagicMock()
        stockout.id = 1
        stockout.stockin_id = 5
        stockout_result = MagicMock()
        stockout_result.scalar_one_or_none.return_value = stockout
        mock_db.execute = AsyncMock(side_effect=[pid_result, stockout_result])
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        with patch('fastapi_app.services.stock_service.get_product_for_update', new_callable=AsyncMock) as mock_get_product:
            mock_get_product.return_value = MagicMock()
            with pytest.raises(ValueError, match="订单抵扣"):
                await stock_service.update_stockout(
                    mock_db, stockout_id=1, new_quantity=10,
                    customer="客户", stockout_date_str="2026-01-15", note=""
                )

    async def test_delete_stockout_not_found(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        with pytest.raises(ValueError, match="不存在"):
            await stock_service.delete_stockout(mock_db, 999)

    async def test_delete_stockout_is_deduction(self, mock_db):
        stockout = MagicMock()
        stockout.id = 1
        stockout.stockin_id = 5
        stockout.stockout_no = "SO-001"
        stockout.quantity = 10
        stockout.product_id = 1
        stockout.customer = "客户"
        stockout_result = MagicMock()
        stockout_result.scalar_one_or_none.return_value = stockout
        product_name_result = MagicMock()
        product_name_result.one_or_none.return_value = ("产品A",)
        mock_db.execute = AsyncMock(side_effect=[stockout_result, product_name_result])
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        with pytest.raises(ValueError, match="订单抵扣"):
            await stock_service.delete_stockout(mock_db, 1)

    async def test_delete_stockout_success(self, mock_db):
        stockout = MagicMock()
        stockout.id = 1
        stockout.stockout_no = "SO-001"
        stockout.quantity = 10
        stockout.product_id = 1
        stockout.stockin_id = None
        stockout.customer = ""
        stockout.stockout_date = None

        stockout_result = MagicMock()
        stockout_result.scalar_one_or_none.return_value = stockout
        product_name_result = MagicMock()
        product_name_result.one_or_none.return_value = None

        mock_db.execute = AsyncMock(side_effect=[stockout_result, product_name_result])
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        with patch('fastapi_app.services.stock_service.delete_stockout_core', new_callable=AsyncMock, return_value=None) as mock_delete:
            await stock_service.delete_stockout(mock_db, 1)
        mock_delete.assert_awaited_once()


class TestInventoryService:
    """库存查看 Service 测试"""

    async def test_get_inventory_empty(self, mock_db):
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_unique = MagicMock()
        mock_unique.all.return_value = []
        mock_scalars.unique.return_value = mock_unique
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)
        result = await stock_service.get_inventory(mock_db)
        assert result['inventory_data'] == []
        assert result['total_stock'] == 0


# ==================== API 端点测试 ====================

class TestStockInEndpoints:
    """入库 API 端点测试"""

    async def test_list_stockins(self, client, mock_db):
        mock_result = MagicMock()
        mock_unique = MagicMock()
        mock_unique.all.return_value = []
        mock_result.scalars.return_value = mock_result
        mock_result.unique.return_value = mock_result
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_result])
        response = await client.get("/api/v1/stock/in/list")
        assert response.status_code == 200
        assert response.json()['success'] is True

    @patch('fastapi_app.api.v1.endpoints.stock.require_permission', return_value=MagicMock())
    async def test_create_stockin_success(self, mock_perm, client, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "产品"
        product.current_stock = 100
        stockin = MagicMock()
        stockin.id = 1
        stockin.stockin_no = "BH-001"
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        with patch('fastapi_app.services.stock_service.create_stockin_core', new_callable=AsyncMock, return_value=stockin):
            with patch('fastapi_app.services.stock_service.publish_stock_event', new_callable=AsyncMock):
                response = await client.post("/api/v1/stock/in/create", json={
                    "product_id": 1, "quantity": 10,
                    "customer": "客户", "stockin_date": "2026-01-15"
                })
        assert response.status_code == 200
        assert response.json()['success'] is True

    @patch('fastapi_app.api.v1.endpoints.stock.require_permission', return_value=MagicMock())
    async def test_create_stockin_product_not_found(self, mock_perm, client, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        with patch('fastapi_app.services.stock_service.create_stockin_core', new_callable=AsyncMock, side_effect=ValueError('产品ID 999 不存在')):
            response = await client.post("/api/v1/stock/in/create", json={
                "product_id": 999, "quantity": 10,
                "customer": "客户", "stockin_date": "2026-01-15"
            })
        assert response.status_code == 400

    async def test_create_stockin_invalid_date(self, client, mock_db):
        response = await client.post("/api/v1/stock/in/create", json={
            "product_id": 1, "quantity": 10,
            "customer": "客户", "stockin_date": "invalid-date"
        })
        assert response.status_code == 422

    @patch('fastapi_app.api.v1.endpoints.stock.require_permission', return_value=MagicMock())
    async def test_delete_stockin_success(self, mock_perm, client, mock_db):
        stockin = MagicMock()
        stockin.id = 1
        stockin.stockin_no = "BH-001"
        stockin.quantity = 10
        stockin.product_id = 1
        stockin.stockin_stockouts = []
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = stockin
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        with patch('fastapi_app.services.stock_service.delete_stockin_core', new_callable=AsyncMock, return_value=None):
            response = await client.delete("/api/v1/stock/in/delete/1")
        assert response.status_code == 200

    async def test_delete_stockin_not_found(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        response = await client.delete("/api/v1/stock/in/delete/999")
        assert response.status_code == 400


class TestStockOutEndpoints:
    """出库 API 端点测试"""

    async def test_list_stockouts(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_result
        mock_result.unique.return_value = mock_result
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_result])
        response = await client.get("/api/v1/stock/out/list")
        assert response.status_code == 200
        assert response.json()['success'] is True

    @patch('fastapi_app.api.v1.endpoints.stock.require_permission', return_value=MagicMock())
    async def test_create_stockout_insufficient_stock(self, mock_perm, client, mock_db):
        product = MagicMock()
        product.id = 1
        product.current_stock = 5
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_db.get = AsyncMock(return_value=product)
        with patch('fastapi_app.services.stock_service.create_stockout_core', new_callable=AsyncMock, side_effect=ValueError('库存不足')):
            response = await client.post("/api/v1/stock/out/create", json={
                "product_id": 1, "quantity": 10,
                "customer": "客户", "stockout_date": "2026-01-15"
            })
        assert response.status_code == 400

    @patch('fastapi_app.api.v1.endpoints.stock.require_permission', return_value=MagicMock())
    async def test_create_stockout_product_not_found(self, mock_perm, client, mock_db):
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        with patch('fastapi_app.services.stock_service.create_stockout_core', new_callable=AsyncMock, side_effect=ValueError('产品ID 999 不存在')):
            response = await client.post("/api/v1/stock/out/create", json={
                "product_id": 999, "quantity": 10,
                "customer": "客户", "stockout_date": "2026-01-15"
            })
        assert response.status_code == 400

    async def test_delete_stockout_is_deduction(self, client, mock_db):
        stockout = MagicMock()
        stockout.id = 1
        stockout.stockin_id = 5
        stockout.stockout_no = "SO-001"
        stockout.quantity = 10
        stockout.product_id = 1
        stockout.customer = "客户"
        stockout_result = MagicMock()
        stockout_result.scalar_one_or_none.return_value = stockout
        product_name_result = MagicMock()
        product_name_result.one_or_none.return_value = ("产品A",)
        mock_db.execute = AsyncMock(side_effect=[stockout_result, product_name_result])
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        response = await client.delete("/api/v1/stock/out/delete/1")
        assert response.status_code == 400

    async def test_delete_stockout_not_found(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        response = await client.delete("/api/v1/stock/out/delete/999")
        assert response.status_code == 400


class TestInventoryEndpoints:
    """库存查看 API 端点测试"""

    async def test_inventory(self, client, mock_db):
        with patch('fastapi_app.services.stock_service.get_inventory_paginated', new_callable=AsyncMock, return_value={
            'inventory_data': [], 'total_order_qty': 0, 'total_stockin_qty': 0,
            'total_stock': 0, 'total_available_stock': 0, 'all_countries': [], 'all_customers': [],
            'total_items': 0, 'page': 1, 'per_page': 50,
        }):
            response = await client.get("/api/v1/stock/inventory")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total_stock'] == 0

    async def test_inventory_with_filters(self, client, mock_db):
        with patch('fastapi_app.services.stock_service.get_inventory_paginated', new_callable=AsyncMock, return_value={
            'inventory_data': [], 'total_order_qty': 0, 'total_stockin_qty': 0,
            'total_stock': 0, 'total_available_stock': 0, 'all_countries': [], 'all_customers': [],
            'total_items': 0, 'page': 1, 'per_page': 50,
        }):
            response = await client.get("/api/v1/stock/inventory?customer=测试客户&product=测试产品")
        assert response.status_code == 200
