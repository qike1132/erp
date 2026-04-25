"""finance_service 单元测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi_app.services.finance_service import get_customer_summary, get_daily_amount, get_daily_amount_chart


class TestFinanceService:
    @staticmethod
    def _result(*, scalar=None, fetchone=None, fetchall=None):
        result = MagicMock()
        result.scalar.return_value = scalar
        result.fetchone.return_value = fetchone
        result.fetchall.return_value = fetchall or []
        return result

    @pytest.mark.asyncio
    async def test_get_customer_summary_empty(self):
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[
            self._result(scalar=0),
            self._result(fetchall=[]),
            self._result(fetchone=MagicMock(total_quantity=0, total_amount=0)),
        ])
        result = await get_customer_summary(mock_db)
        assert 'success' in result
        assert result['success'] is True
        assert result['stats']['total_count'] == 0

    @pytest.mark.asyncio
    async def test_get_customer_summary_with_data(self):
        mock_db = AsyncMock()
        mock_row = MagicMock(customer='Customer A', total_quantity=1000, total_amount=5000, stockout_count=5)
        mock_db.execute = AsyncMock(side_effect=[
            self._result(scalar=1),
            self._result(fetchall=[mock_row]),
            self._result(fetchone=MagicMock(total_quantity=1000, total_amount=5000)),
        ])
        result = await get_customer_summary(mock_db)
        assert 'success' in result
        assert result['success'] is True
        assert result['logs'][0]['customer'] == 'Customer A'
        assert result['stats']['total_amount'] == 5000.0

    @pytest.mark.asyncio
    async def test_get_daily_amount_with_data(self):
        mock_db = AsyncMock()
        daily_row = MagicMock(
            stockout_date_only=MagicMock(strftime=MagicMock(return_value='2026-04-23')),
            total_quantity=120,
            total_amount=3600,
            stockout_count=3,
        )
        customer_row_a = MagicMock(stockout_date_only=daily_row.stockout_date_only, customer_name='客户A')
        customer_row_b = MagicMock(stockout_date_only=daily_row.stockout_date_only, customer_name='客户B')
        mock_db.execute = AsyncMock(side_effect=[
            self._result(scalar=1),
            self._result(fetchall=[daily_row]),
            self._result(fetchall=[customer_row_a, customer_row_b]),
            self._result(fetchone=MagicMock(total_quantity=120, total_amount=3600)),
        ])

        result = await get_daily_amount(mock_db)

        assert result['success'] is True
        assert result['logs'][0]['date'] == '2026-04-23'
        assert result['logs'][0]['customer_names'] == '客户A、客户B'
        assert result['stats']['total_quantity'] == 120

    @pytest.mark.asyncio
    async def test_get_daily_amount_chart_with_data(self):
        mock_db = AsyncMock()
        chart_row = MagicMock(
            stockout_date_only=MagicMock(strftime=MagicMock(return_value='2026-04-23')),
            total_quantity=88,
            total_amount=1888,
        )
        mock_db.execute = AsyncMock(return_value=self._result(fetchall=[chart_row]))

        result = await get_daily_amount_chart(mock_db)

        assert result['success'] is True
        assert result['chart']['dates'] == ['2026-04-23']
        assert result['chart']['quantities'] == [88]
        assert result['chart']['amounts'] == [1888.0]
