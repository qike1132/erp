"""production_plan_service 单元测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.services.production_plan_service import get_plans, get_plan_by_id, _normalize_plan_date


class TestProductionPlanService:
    @pytest.mark.asyncio
    async def test_get_plans(self):
        mock_db = AsyncMock()
        mr = MagicMock()
        mr.scalars.return_value.all.return_value = [
            MagicMock(id=1, plan_no='PP-001', status='pending'),
            MagicMock(id=2, plan_no='PP-002', status='in_progress')
        ]
        mock_db.execute = AsyncMock(return_value=mr)
        plans = await get_plans(mock_db, year=2024, month=1)
        assert len(plans) == 2

    @pytest.mark.asyncio
    async def test_get_plan_by_id(self):
        mock_db = AsyncMock()
        mr = MagicMock()
        mr.scalar_one_or_none.return_value = MagicMock(id=1, plan_no='PP-001')
        mock_db.execute = AsyncMock(return_value=mr)
        plan = await get_plan_by_id(mock_db, plan_id=1)
        assert plan.id == 1

    def test_normalize_plan_date(self):
        from datetime import date
        result = _normalize_plan_date('2024-04-15')
        assert result == date(2024, 4, 15)

    def test_normalize_plan_date_invalid(self):
        with pytest.raises(ValueError):
            _normalize_plan_date('invalid')
