"""生产计划模块端点测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestProductionSummaryEndpoints:

    @pytest.mark.asyncio
    async def test_list_craft_works_success(self, client, mock_db):
        mock_service_result = {
            'data': [
                {
                    'id': 1,
                    'worker_name': '张三',
                    'quantity': 50,
                    'work_date': '2026-04-15',
                    'remark': '',
                    'create_time': '2026-04-15 10:00',
                    'created_by': 'admin',
                }
            ],
            'daily_summary': {
                '2026-04-15': {'craft_qty': 50, 'case_out_qty': 30}
            },
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.get_craft_works = AsyncMock(return_value=mock_service_result)
            response = await client.get(
                "/api/v1/production-summary/craft/list",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1
        assert len(data['data']) == 1
        assert data['data'][0]['worker_name'] == '张三'

    @pytest.mark.asyncio
    async def test_create_craft_work_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.create_craft_work = AsyncMock(return_value=MagicMock())
            response = await client.post(
                "/api/v1/production-summary/craft/create",
                json={
                    "worker_name": "张三",
                    "quantity": 50,
                    "work_date": "2026-04-15",
                    "remark": "",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '创建成功' in data['message']

    @pytest.mark.asyncio
    async def test_create_craft_work_validation_error(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.create_craft_work = AsyncMock(side_effect=ValueError("日期格式不正确"))
            response = await client.post(
                "/api/v1/production-summary/craft/create",
                json={
                    "worker_name": "张三",
                    "quantity": 50,
                    "work_date": "invalid-date",
                },
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_craft_work_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.update_craft_work = AsyncMock(return_value=None)
            response = await client.put(
                "/api/v1/production-summary/craft/edit/1",
                json={
                    "quantity": 80,
                    "remark": "更新数量",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '更新成功' in data['message']

    @pytest.mark.asyncio
    async def test_edit_craft_work_not_found(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.update_craft_work = AsyncMock(side_effect=ValueError("记录不存在"))
            response = await client.put(
                "/api/v1/production-summary/craft/edit/999",
                json={"quantity": 80},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_craft_work_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.delete_craft_work = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/production-summary/craft/delete/1")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '删除成功' in data['message']

    @pytest.mark.asyncio
    async def test_list_packaging_records_success(self, client, mock_db):
        mock_service_result = {
            'data': [
                {
                    'id': 1,
                    'customer': '测试客户',
                    'product_name': '测试产品A',
                    'barcode': '6901234567890',
                    'quantity': 30,
                    'pack_date': '2026-04-15',
                    'remark': '',
                }
            ],
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.get_packaging_records = AsyncMock(return_value=mock_service_result)
            response = await client.get(
                "/api/v1/production-summary/packaging/list",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1
        assert data['data'][0]['customer'] == '测试客户'

    @pytest.mark.asyncio
    async def test_create_packaging_record_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.create_packaging_record = AsyncMock(return_value=MagicMock())
            response = await client.post(
                "/api/v1/production-summary/packaging/create",
                json={
                    "customer": "测试客户",
                    "product_name": "测试产品A",
                    "barcode": "6901234567890",
                    "quantity": 30,
                    "pack_date": "2026-04-15",
                    "remark": "",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '创建成功' in data['message']

    @pytest.mark.asyncio
    async def test_edit_packaging_record_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.update_packaging_record = AsyncMock(return_value=None)
            response = await client.put(
                "/api/v1/production-summary/packaging/edit/1",
                json={"quantity": 50},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '更新成功' in data['message']

    @pytest.mark.asyncio
    async def test_delete_packaging_record_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.delete_packaging_record = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/production-summary/packaging/delete/1")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '删除成功' in data['message']

    @pytest.mark.asyncio
    async def test_production_summary_success(self, client, mock_db):
        mock_summary_result = {
            'data': [
                {
                    'date': '2026-04-15',
                    'case_out_qty': 30,
                    'craft_qty': 50,
                    'packaging_qty': 40,
                }
            ],
            'monthly_summary': {
                'total_case_out': 900,
                'total_craft': 1000,
                'total_packaging': 800,
            },
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.production_summary.production_summary_service') as mock_svc:
            mock_svc.get_production_summary = AsyncMock(return_value=mock_summary_result)
            response = await client.get(
                "/api/v1/production-summary/summary",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1
