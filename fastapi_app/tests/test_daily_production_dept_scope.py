"""读接口的部门范围收窄：受限用户只看得到范围内部门"""
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_app.core.deps import resolve_production_view_scope
from fastapi_app.main import app


def _scope_override(scope):
    app.dependency_overrides[resolve_production_view_scope] = lambda: scope


class TestDailySummaryScope:
    async def test_scoped_user_passes_departments_to_service(self, client):
        _scope_override({'filling'})
        payload = {
            'date': '2026-09-29',
            'departments': [
                {'department': 'filling', 'department_label': '充棉部',
                 'total_quantity': 10, 'total_value': 70.0, 'sku_count': 1},
            ],
            'overall_quantity': 10,
            'overall_value': 70.0,
            'overall_sku_count': 1,
        }
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_daily_summary = AsyncMock(return_value=payload)
            response = await client.get(
                '/api/v1/daily-production/daily-summary', params={'date': '2026-09-29'},
            )
            called_kwargs = mock_svc.get_daily_summary.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'filling'}

    async def test_unscoped_user_passes_none(self, client):
        _scope_override(None)
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_daily_summary = AsyncMock(return_value={
                'date': '2026-09-29', 'departments': [],
                'overall_quantity': 0, 'overall_value': 0.0, 'overall_sku_count': 0,
            })
            await client.get(
                '/api/v1/daily-production/daily-summary', params={'date': '2026-09-29'},
            )
            called_kwargs = mock_svc.get_daily_summary.await_args.kwargs

        assert called_kwargs['departments'] is None


class TestMonthlySummaryScope:
    async def test_scoped_user_passes_departments_to_service(self, client):
        _scope_override({'handcraft'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_monthly_summary = AsyncMock(return_value={
                'year': 2026, 'month': 9, 'daily_data': [], 'monthly_departments': [],
                'monthly_total_quantity': 0, 'monthly_total_value': 0,
            })
            await client.get(
                '/api/v1/daily-production/monthly-summary',
                params={'year': 2026, 'month': 9},
            )
            called_kwargs = mock_svc.get_monthly_summary.await_args.kwargs

        assert called_kwargs['departments'] == {'handcraft'}


class TestRecordsAndExportScope:
    async def test_out_of_scope_department_is_ignored_not_403(self, client):
        # Review Focus #5：前端状态残留不应让整页报错
        _scope_override({'filling'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_records = AsyncMock(return_value={
                'data': [], 'total': 0, 'page': 1, 'per_page': 50, 'pages': 0, 'stats': None,
            })
            response = await client.get(
                '/api/v1/daily-production/records',
                params={'year': 2026, 'month': 9, 'department': 'packaging'},
            )
            called_kwargs = mock_svc.get_records.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'filling'}

    async def test_invalid_department_for_unscoped_user_does_not_500(self, client):
        _scope_override(None)
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.get_records = AsyncMock(return_value={
                'data': [], 'total': 0, 'page': 1, 'per_page': 50, 'pages': 0, 'stats': None,
            })
            response = await client.get(
                '/api/v1/daily-production/records',
                params={'year': 2026, 'month': 9, 'department': 'Filling'},
            )
            called_kwargs = mock_svc.get_records.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'Filling'}

    async def test_export_receives_narrowed_departments(self, client):
        _scope_override({'packaging'})
        with patch(
            'fastapi_app.api.v1.endpoints.daily_production.daily_production_service'
        ) as mock_svc:
            mock_svc.export_records = AsyncMock(return_value=b'xlsx-bytes')
            response = await client.get(
                '/api/v1/daily-production/export',
                params={'start_date': '2026-09-01', 'end_date': '2026-09-30', 'department': 'filling'},
            )
            called_kwargs = mock_svc.export_records.await_args.kwargs

        assert response.status_code == 200
        assert called_kwargs['departments'] == {'packaging'}

    async def test_missing_scope_dependency_still_403_for_no_permission_user(self, client, mock_current_user):
        # 走真实依赖（不覆盖），has_permission 全 False → 403
        app.dependency_overrides.pop(resolve_production_view_scope, None)
        mock_current_user.has_permission = MagicMock(return_value=False)
        mock_current_user.is_super = False
        response = await client.get(
            '/api/v1/daily-production/daily-summary', params={'date': '2026-09-29'},
        )
        assert response.status_code == 403
