"""写入口的部门范围校验"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.deps import resolve_production_write_scope
from fastapi_app.main import app


def _write_scope_override(scope):
    app.dependency_overrides[resolve_production_write_scope] = lambda: scope


def _record(department):
    record = MagicMock()
    record.id = 7
    record.department = department
    return record


class TestCreateRecordScope:
    async def test_in_scope_department_is_accepted(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                '/api/v1/daily-production/records',
                json={
                    'department': 'filling', 'product_name': '白兔公仔',
                    'barcode': '690', 'unit_price': 7, 'quantity': 10,
                    'production_date': '2026-09-29', 'remark': '',
                },
            )
        assert response.status_code == 200

    async def test_out_of_scope_department_is_rejected_403(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                '/api/v1/daily-production/records',
                json={
                    'department': 'packaging', 'product_name': '白兔公仔',
                    'barcode': '690', 'unit_price': 7, 'quantity': 10,
                    'production_date': '2026-09-29', 'remark': '',
                },
            )
            mock_svc.create_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_unscoped_user_can_write_any_department(self, client):
        _write_scope_override(None)
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.create_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                '/api/v1/daily-production/records',
                json={
                    'department': 'packaging', 'product_name': '白兔公仔',
                    'barcode': '690', 'unit_price': 7, 'quantity': 10,
                    'production_date': '2026-09-29', 'remark': '',
                },
            )
        assert response.status_code == 200


class TestUpdateRecordScope:
    async def test_records_own_department_governs_authorization(self, client):
        # 记录属于 packaging，用户只有 filling → 403
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('packaging'))
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/7',
                json={'quantity': 20},
            )
            mock_svc.update_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_moving_record_into_out_of_scope_department_is_rejected(self, client):
        # 记录属于 filling（可写），但请求把部门改成 packaging → 403
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('filling'))
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/7',
                json={'department': 'packaging'},
            )
            mock_svc.update_record.assert_not_awaited()
        assert response.status_code == 403

    async def test_in_scope_update_succeeds(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=_record('filling'))
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/7',
                json={'quantity': 20},
            )
        assert response.status_code == 200

    async def test_missing_record_returns_404(self, client):
        _write_scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_record = AsyncMock(return_value=None)
            mock_svc.update_record = AsyncMock(return_value=MagicMock())
            response = await client.put(
                '/api/v1/daily-production/records/999',
                json={'quantity': 20},
            )
        assert response.status_code == 404
