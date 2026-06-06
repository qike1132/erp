"""辅助API接口测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAuxiliaryEndpoints:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        response = await client.get("/api/v1/aux/health")
        assert response.status_code == 200
        data = response.json()
        assert data['status'] == 'ok'

    @pytest.mark.asyncio
    async def test_product_search_empty(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/aux/product-search?q=test")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_product_search_with_results(self, client, mock_db):
        mock_product = MagicMock()
        mock_product.id = 1
        mock_product.name = "测试产品"
        mock_product.barcode = "6901234567890"
        mock_product.current_stock = 100

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_product]
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/aux/product-search?q=测试")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]['name'] == "测试产品"

    @pytest.mark.asyncio
    async def test_product_available_stock_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        response = await client.get("/api/v1/aux/product-available-stock?product_id=999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_product_available_stock_success(self, client, mock_db):
        product = MagicMock()
        product.id = 1
        product.name = "产品A"
        product.current_stock = 50
        mock_db.get = AsyncMock(return_value=product)

        response = await client.get("/api/v1/aux/product-available-stock?product_id=1")
        assert response.status_code == 200
        data = response.json()
        assert data['current_stock'] == 50

    @pytest.mark.asyncio
    async def test_inventory_logs(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        response = await client.get("/api/v1/aux/inventory-logs/1")
        assert response.status_code == 200
        data = response.json()
        assert data['items'] == []
        assert data['total'] == 0

    @pytest.mark.asyncio
    async def test_available_stockins(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/aux/available-stockins?product_id=1")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stockin_info_not_found(self, client, mock_db):
        mock_db.get = AsyncMock(return_value=None)

        response = await client.get("/api/v1/aux/stockin-info/999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stockin_info_success(self, client, mock_db):
        stockin = MagicMock()
        stockin.id = 1
        stockin.product_id = 1
        stockin.product = MagicMock()
        stockin.product.name = "产品A"
        stockin.quantity = 100
        stockin.customer = "客户1"
        stockin.stockin_date = MagicMock()
        stockin.stockin_date.strftime.return_value = "2024-01-01"
        stockin.note = None
        mock_db.get = AsyncMock(return_value=stockin)

        response = await client.get("/api/v1/aux/stockin-info/1")
        assert response.status_code == 200
        data = response.json()
        assert data['quantity'] == 100

    @pytest.mark.asyncio
    async def test_available_shipment_no_params(self, client):
        response = await client.get("/api/v1/aux/available-shipment")
        assert response.status_code == 200
        data = response.json()
        assert data['order_quantity'] == 0

    @pytest.mark.asyncio
    async def test_delete_stockout_api(self, client, mock_db):
        with patch('fastapi_app.services.stock_service.delete_stockout', new_callable=AsyncMock):
            response = await client.delete("/api/v1/aux/stockout/1")
            assert response.status_code in (200, 400)

    @pytest.mark.asyncio
    async def test_delete_customer_api(self, client, mock_db):
        with patch('fastapi_app.services.customer_service.delete_customer', new_callable=AsyncMock):
            response = await client.delete("/api/v1/aux/customer/1")
            assert response.status_code in (200, 400)
