"""case_service 单元测试"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_app.services.case_service import search_cases


class TestCaseService:
    @pytest.mark.asyncio
    async def test_search_cases_empty_query(self):
        mock_db = AsyncMock()
        mr = MagicMock()
        p1 = MagicMock(id=1, name='Product A', barcode='123', cases=[])
        p1.cases = [MagicMock(current_stock=10)]
        mr.unique.return_value.scalars.return_value.all.return_value = [p1]
        mock_db.execute = AsyncMock(return_value=mr)
        result = await search_cases(mock_db, query='')
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_cases_with_query(self):
        mock_db = AsyncMock()
        mr = MagicMock()
        p1 = MagicMock(id=1, name='Product A', barcode='123', cases=[])
        p1.cases = [MagicMock(current_stock=10)]
        mr.unique.return_value.scalars.return_value.all.return_value = [p1]
        mock_db.execute = AsyncMock(return_value=mr)
        result = await search_cases(mock_db, query='Product')
        assert len(result) == 1
