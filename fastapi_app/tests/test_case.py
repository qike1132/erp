"""皮套管理模块测试"""
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCaseModels:
    def test_case_import(self):
        from fastapi_app.shared_models.case import Case
        assert Case.__tablename__ == 'case'

    def test_case_stock_in_import(self):
        from fastapi_app.shared_models.case_stock_in import CaseStockIn
        assert CaseStockIn.__tablename__ == 'case_stock_in'

    def test_case_stock_out_import(self):
        from fastapi_app.shared_models.case_stock_out import CaseStockOut
        assert CaseStockOut.__tablename__ == 'case_stock_out'

    def test_case_inventory_log_import(self):
        from fastapi_app.shared_models.case_inventory_log import CaseInventoryLog
        assert CaseInventoryLog.__tablename__ == 'case_inventory_log'


class TestCaseService:
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

    @pytest.mark.asyncio
    async def test_search_cases_empty(self, mock_db):
        from fastapi_app.services.case_service import search_cases
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await search_cases(mock_db, "test")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_case_stockins_empty(self, mock_db):
        from fastapi_app.services.case_service import get_case_stockins
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.unique.return_value = mock_data
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        result = await get_case_stockins(mock_db)
        assert result['stockins'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_get_case_stockouts_empty(self, mock_db):
        from fastapi_app.services.case_service import get_case_stockout_list
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.unique.return_value = mock_data
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        result = await get_case_stockout_list(mock_db)
        assert result['stockouts'] == []

    @pytest.mark.asyncio
    async def test_get_inventory_summary_empty(self, mock_db):
        from fastapi_app.services.case_service import get_case_inventory_summary
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.all.return_value = []
        mock_stats = MagicMock()
        mock_stats.one.return_value = (0, 0)
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data, mock_stats])

        result = await get_case_inventory_summary(mock_db)
        assert result['inventory'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_get_inventory_logs_empty(self, mock_db):
        from fastapi_app.services.case_service import get_case_inventory_logs
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        result = await get_case_inventory_logs(mock_db, 1)
        assert result['logs'] == []

    @pytest.mark.asyncio
    async def test_delete_case_product_not_found(self, mock_db):
        from fastapi_app.services.case_service import delete_case_product
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="皮套不存在"):
            await delete_case_product(mock_db, 999)

    @pytest.mark.asyncio
    async def test_delete_case_product_nonzero_stock(self, mock_db):
        from fastapi_app.services.case_service import delete_case_product
        case = MagicMock()
        case.current_stock = 10
        mock_db.get = AsyncMock(return_value=case)
        with pytest.raises(ValueError, match="库存为0"):
            await delete_case_product(mock_db, 1)


class TestCaseEndpoints:
    @pytest.mark.asyncio
    async def test_search(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.unique.return_value = mock_result
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/cases/search?q=test")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_in_list(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.unique.return_value = mock_data
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        response = await client.get("/api/v1/cases/in/list")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_out_list(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.unique.return_value = mock_data
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        response = await client.get("/api/v1/cases/out/list")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_inventory_summary(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.all.return_value = []
        mock_stats = MagicMock()
        mock_stats.one.return_value = (0, 0)
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data, mock_stats])

        response = await client.get("/api/v1/cases/inventory-summary")
        assert response.status_code == 200
        data = response.json()
        assert data['inventory'] == []

    @pytest.mark.asyncio
    async def test_inventory_logs(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        response = await client.get("/api/v1/cases/inventory-logs/1")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_case_product(self, client, mock_db):
        case = MagicMock()
        case.current_stock = 0
        mock_db.get = AsyncMock(return_value=case)
        # 模拟引用检查返回 0（无关联入库/出库/流水记录）
        mock_ref_result = MagicMock()
        mock_ref_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_ref_result)

        response = await client.delete("/api/v1/cases/product/1")
        assert response.status_code == 200
