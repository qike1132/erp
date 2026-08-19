"""排产计划管理端点测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestProductionPlanEndpoints:

    @pytest.mark.asyncio
    async def test_list_plans_success(self, client, mock_db):
        mock_service_result = {
            'plans': [
                {
                    'id': 1,
                    'customer_name': '测试客户',
                    'product_name': '测试产品A',
                    'barcode': '6901234567890',
                    'quantity': 100,
                    'inventory_qty': 50,
                    'shipped_qty': 20,
                    'remaining_qty': 80,
                    'diff': -30,
                    'stock_status': 'normal',
                    'shipment_status': 'pending',
                    'plan_date': '2026-04-15',
                    'status': 'pending',
                    'remark': '',
                    'upload_batch': None,
                    'create_time': '2026-04-01 10:00',
                    'update_time': None,
                    'created_by': 'admin',
                }
            ],
            'monthly_summary': {
                'total_plan_qty': 100,
                'total_inventory_qty': 50,
                'total_shipped_qty': 20,
                'total_remaining_qty': 80,
                'total_diff': -30,
                'warning_count': 0,
                'customer_summary': {},
            },
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.get_plans_with_inventory = AsyncMock(return_value=mock_service_result)
            response = await client.get(
                "/api/v1/production-plans/list",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1
        assert len(data['plans']) == 1
        assert data['plans'][0]['customer_name'] == '测试客户'

    @pytest.mark.asyncio
    async def test_create_plan_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.create_plan = AsyncMock(return_value=MagicMock())
            response = await client.post(
                "/api/v1/production-plans/create",
                json={
                    "customer_name": "测试客户",
                    "product_name": "测试产品A",
                    "barcode": "6901234567890",
                    "quantity": 100,
                    "plan_date": "2026-04-15",
                    "remark": "",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '创建成功' in data['message']

    @pytest.mark.asyncio
    async def test_create_plan_validation_error(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.create_plan = AsyncMock(side_effect=ValueError("69码不存在"))
            response = await client.post(
                "/api/v1/production-plans/create",
                json={
                    "customer_name": "测试客户",
                    "product_name": "测试产品A",
                    "barcode": "0000000000",
                    "quantity": 100,
                    "plan_date": "2026-04-15",
                },
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_plan_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.update_plan = AsyncMock(return_value=None)
            response = await client.put(
                "/api/v1/production-plans/edit/1",
                json={
                    "quantity": 200,
                    "remark": "更新数量",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '更新成功' in data['message']

    @pytest.mark.asyncio
    async def test_edit_plan_not_found(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.update_plan = AsyncMock(side_effect=ValueError("计划不存在"))
            response = await client.put(
                "/api/v1/production-plans/edit/999",
                json={"quantity": 200},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_plan_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.delete_plan = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/production-plans/delete/1")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '删除成功' in data['message']

    @pytest.mark.asyncio
    async def test_delete_plan_not_found(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.delete_plan = AsyncMock(side_effect=ValueError("计划不存在"))
            response = await client.delete("/api/v1/production-plans/delete/999")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_timeline_success(self, client, mock_db):
        mock_timeline_data = {
            'year': 2026,
            'month': 4,
            'days_in_month': 30,
            'timeline': [
                {'date': '2026-04-15', 'day': 15, 'plans': [], 'total_plan_qty': 100, 'has_warning': False},
            ],
            'customers': ['测试客户'],
        }
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.get_timeline = AsyncMock(return_value=mock_timeline_data)
            response = await client.get(
                "/api/v1/production-plans/timeline",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['year'] == 2026
        assert data['month'] == 4
        assert any(d['date'] == '2026-04-15' for d in data['timeline'])

    @pytest.mark.asyncio
    async def test_customer_summary_success(self, client, mock_db):
        mock_summary = {
            'total_plan_qty': 100,
            'total_inventory_qty': 50,
            'total_shipped_qty': 20,
            'total_remaining_qty': 80,
            'total_diff': -30,
            'warning_count': 0,
            'customer_summary': {
                '测试客户': {
                    'plan_qty': 100,
                    'inventory_qty': 50,
                    'shipped_qty': 20,
                    'remaining_qty': 80,
                    'warning_count': 0,
                }
            },
        }
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.get_customer_summary = AsyncMock(return_value=mock_summary)
            response = await client.get(
                "/api/v1/production-plans/customer-summary",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert '测试客户' in data['customer_summary']
        assert data['total_plan_qty'] == 100

    @pytest.mark.asyncio
    async def test_validate_barcode_found(self, client, mock_db):
        mock_validation = {
            'valid': True,
            'product_name': '测试产品A',
            'message': '产品已找到',
        }
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.validate_barcode = AsyncMock(return_value=mock_validation)
            response = await client.get(
                "/api/v1/production-plans/validate-barcode",
                params={"q": "6901234567890"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['valid'] is True
        assert data['product_name'] == '测试产品A'

    @pytest.mark.asyncio
    async def test_staging_list_success(self, client, mock_db):
        mock_records = [
            {'id': 1, 'customer_name': '暂存客户', 'product_name': '产品B', 'quantity': 50}
        ]
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.get_staging_list = AsyncMock(return_value=mock_records)
            response = await client.get("/api/v1/production-plans/staging/list")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1

    @pytest.mark.asyncio
    async def test_staging_clear_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_plan.production_plan_service') as mock_svc:
            mock_svc.clear_staging = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/production-plans/staging/clear")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '清空' in data['message']
