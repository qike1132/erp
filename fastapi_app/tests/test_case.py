"""皮套管理模块测试"""
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCaseModels:
    def test_case_import(self):
        from fastapi_app.shared_models.case import Case
        assert Case.__tablename__ == 'case'

    def test_case_movement_import(self):
        from fastapi_app.shared_models.case_movement import CaseMovement
        assert CaseMovement.__tablename__ == 'case_movement'

    def test_case_has_part_fields(self):
        from fastapi_app.shared_models.case import Case
        assert hasattr(Case, 'parent_id')
        assert hasattr(Case, 'qty_per_set')
        assert hasattr(Case, 'unit')

    def test_movement_directions(self):
        from fastapi_app.shared_models import DIRECTION_IN, DIRECTION_OUT
        assert (DIRECTION_IN, DIRECTION_OUT) == ('in', 'out')


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
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        assert await search_cases(mock_db, "test") == []

    @pytest.mark.asyncio
    async def test_get_case_items_empty(self, mock_db):
        from fastapi_app.services.case_service import get_case_items
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        result = await get_case_items(mock_db)
        assert result['items'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_get_case_movements_empty(self, mock_db):
        from fastapi_app.services.case_service import get_case_movements
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.unique.return_value = mock_data
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        result = await get_case_movements(mock_db)
        assert result['movements'] == []

    @pytest.mark.asyncio
    async def test_get_case_inventory_empty(self, mock_db):
        from fastapi_app.services.case_service import get_case_inventory
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_roots = MagicMock()
        mock_roots.scalars.return_value.all.return_value = []
        mock_stats = MagicMock()
        mock_stats.one.return_value = (0, 0)
        mock_sum = MagicMock()
        mock_sum.scalar.return_value = 0
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_roots, mock_stats, mock_sum, mock_sum])

        result = await get_case_inventory(mock_db)
        assert result['inventory'] == []
        assert result['total'] == 0

    @pytest.mark.asyncio
    async def test_delete_case_item_not_found(self, mock_db):
        from fastapi_app.services.case_service import delete_case_item
        mock_db.get = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="皮套不存在"):
            await delete_case_item(mock_db, 999)


class TestCaseEndpoints:
    @pytest.mark.asyncio
    async def test_search(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/cases/search?q=test")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_items(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        response = await client.get("/api/v1/cases/items")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_inventory(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_roots = MagicMock()
        mock_roots.scalars.return_value.all.return_value = []
        mock_stats = MagicMock()
        mock_stats.one.return_value = (0, 0)
        mock_sum = MagicMock()
        mock_sum.scalar.return_value = 0
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_roots, mock_stats, mock_sum, mock_sum])

        response = await client.get("/api/v1/cases/inventory")
        assert response.status_code == 200
        assert response.json()['inventory'] == []

    @pytest.mark.asyncio
    async def test_movements(self, client, mock_db):
        mock_count = MagicMock()
        mock_count.scalar.return_value = 0
        mock_data = MagicMock()
        mock_data.unique.return_value = mock_data
        mock_data.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(side_effect=[mock_count, mock_data])

        response = await client.get("/api/v1/cases/movements")
        assert response.status_code == 200
