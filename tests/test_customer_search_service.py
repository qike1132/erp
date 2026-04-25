"""customer_search_service 单元测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.customer_search_service import CustomerSearchService, customer_search_service


class TestCustomerSearchService:
    def test_get_model_class(self):
        svc = CustomerSearchService()
        assert svc.get_model_class().__name__ == 'Customer'

    def test_get_search_fields(self):
        svc = CustomerSearchService()
        fields = svc.get_search_fields()
        assert len(fields) > 0

    @pytest.mark.asyncio
    async def test_search_async(self):
        svc = CustomerSearchService()
        mock_db = AsyncMock()
        mr = MagicMock()
        m1 = MagicMock(id=1, name='C1', contact='contact1', phone='123')
        mr.scalars.return_value.all.return_value = [m1]
        mock_db.execute = AsyncMock(return_value=mr)
        r = await svc.search_async(mock_db, keyword='c', limit=10)
        assert len(r) == 1

    @pytest.mark.asyncio
    async def test_search_active_customers(self):
        svc = CustomerSearchService()
        mock_db = AsyncMock()
        mr = MagicMock()
        m1 = MagicMock(id=1, name='C1', contact='contact1', phone='123')
        mr.scalars.return_value.all.return_value = [m1]
        mock_db.execute = AsyncMock(return_value=mr)
        r = await svc.search_active_customers(mock_db, keyword='c', limit=10)
        assert len(r) == 1
