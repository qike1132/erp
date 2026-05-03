"""product_search_service 单元测试"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.product_search_service import ProductSearchService


class TestProductSearchService:
    def test_get_model_class(self):
        svc = ProductSearchService()
        assert svc.get_model_class().__name__ == 'Product'

    def test_get_search_fields(self):
        svc = ProductSearchService()
        fields = svc.get_search_fields()
        assert 'name' in fields or 'barcode' in fields

    @pytest.mark.asyncio
    async def test_search_async(self):
        svc = ProductSearchService()
        mock_db = AsyncMock()
        mr = MagicMock()
        m1 = MagicMock(id=1, name='P1', barcode='123')
        mr.scalars.return_value.all.return_value = [m1]
        mock_db.execute = AsyncMock(return_value=mr)
        r = await svc.search_async(mock_db, keyword='123', limit=10)
        assert len(r) == 1
