"""趋势接口：跨月区间、缺失日期补 0、区间长度上限、区间反向"""
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fastapi_app.services.daily_production_service import (
    MAX_TREND_DAYS,
    get_trend,
)


def _mock_db_returning(rows):
    result = MagicMock()
    result.all.return_value = rows
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


class TestGetTrendService:
    async def test_fills_missing_days_with_zero(self):
        db = _mock_db_returning([
            (date(2026, 9, 1), 'filling', 100),
            (date(2026, 9, 1), 'handcraft', 50),
            (date(2026, 9, 3), 'packaging', 7),
        ])

        out = await get_trend(db, start_date='2026-09-01', end_date='2026-09-03')

        assert len(out['days']) == 3
        assert out['days'][0] == {
            'date': '2026-09-01', 'filling': 100, 'handcraft': 50, 'packaging': 0, 'total': 150,
        }
        assert out['days'][1] == {
            'date': '2026-09-02', 'filling': 0, 'handcraft': 0, 'packaging': 0, 'total': 0,
        }
        assert out['days'][2]['total'] == 7
        assert out['days'][2]['packaging'] == 7

    async def test_reports_unscoped_departments_as_zero_and_lists_only_scope(self):
        db = _mock_db_returning([(date(2026, 9, 1), 'filling', 100)])

        out = await get_trend(
            db, start_date='2026-09-01', end_date='2026-09-01', departments={'filling'},
        )

        assert out['departments'] == ['filling']
        assert out['days'][0]['filling'] == 100
        assert out['days'][0]['handcraft'] == 0
        assert out['days'][0]['total'] == 100

    async def test_reversed_range_raises_value_error(self):
        db = _mock_db_returning([])
        with pytest.raises(ValueError, match='不能早于'):
            await get_trend(db, start_date='2026-09-10', end_date='2026-09-01')

    async def test_range_longer_than_cap_raises_value_error(self):
        db = _mock_db_returning([])
        with pytest.raises(ValueError, match=str(MAX_TREND_DAYS)):
            await get_trend(db, start_date='2026-01-01', end_date='2026-12-31')

    async def test_cap_counts_days_inclusively(self):
        # 92 天必须通过（边界包含），93 天必须拒绝
        db = _mock_db_returning([])
        out = await get_trend(db, start_date='2026-01-01', end_date='2026-04-02')
        assert len(out['days']) == 92
        with pytest.raises(ValueError):
            await get_trend(db, start_date='2026-01-01', end_date='2026-04-03')


class TestTrendEndpoint:
    async def test_endpoint_returns_days(self, client):
        payload = {
            'start_date': '2026-09-01',
            'end_date': '2026-09-02',
            'departments': ['filling', 'handcraft', 'packaging'],
            'days': [
                {'date': '2026-09-01', 'filling': 1, 'handcraft': 0, 'packaging': 0, 'total': 1},
                {'date': '2026-09-02', 'filling': 0, 'handcraft': 0, 'packaging': 0, 'total': 0},
            ],
        }
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_trend = AsyncMock(return_value=payload)
            response = await client.get(
                '/api/v1/daily-production/trend',
                params={'start_date': '2026-09-01', 'end_date': '2026-09-02'},
            )
        assert response.status_code == 200
        body = response.json()
        assert body['success'] is True
        assert len(body['days']) == 2

    async def test_endpoint_maps_value_error_to_400(self, client):
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_trend = AsyncMock(side_effect=ValueError('查询区间不能超过 92 天'))
            response = await client.get(
                '/api/v1/daily-production/trend',
                params={'start_date': '2026-01-01', 'end_date': '2026-12-31'},
            )
        assert response.status_code == 400
