"""采购计划管理端点测试"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestPurchasePlanEndpoints:

    @pytest.mark.asyncio
    async def test_list_plans_success(self, client, mock_db):
        mock_service_result = {
            'plans': [
                {
                    'id': 1,
                    'plan_no': 'PP-20260415-0001',
                    'plan_month': '2026-04',
                    'customer_id': 1,
                    'customer_name': '测试客户',
                    'status': 'pending',
                    'remark': '',
                    'upload_batch': '',
                    'created_by': 'admin',
                    'create_time': '2026-04-15 10:00',
                    'update_time': '',
                    'detail_count': 2,
                    'total_quantity': 200,
                    'total_shipped': 50,
                    'total_remaining': 150,
                }
            ],
            'total': 1,
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_plan_list = AsyncMock(return_value=mock_service_result)
            response = await client.get(
                "/api/v1/plans/list",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['total'] == 1
        assert len(data['plans']) == 1
        assert data['plans'][0]['plan_no'] == 'PP-20260415-0001'

    @pytest.mark.asyncio
    async def test_plan_detail_success(self, client, mock_db):
        mock_detail = {
            'plan': {
                'id': 1,
                'plan_no': 'PP-20260415-0001',
                'plan_month': '2026-04',
                'customer_id': 1,
                'customer_name': '测试客户',
                'status': 'pending',
            },
            'details': [
                {
                    'id': 1,
                    'plan_id': 1,
                    'product_id': 1,
                    'product_name': '测试产品A',
                    'barcode': '6901234567890',
                    'plan_date': '2026-04-15',
                    'quantity': 100,
                    'shipped_qty': 20,
                    'remaining_qty': 80,
                    'remark': '',
                    'inventory_qty': 50,
                    'stock_status': 'sufficient',
                    'shipment_status': 'pending',
                }
            ],
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_plan_detail = AsyncMock(return_value=mock_detail)
            response = await client.get("/api/v1/plans/detail/1")
        assert response.status_code == 200
        data = response.json()
        assert data['plan']['plan_no'] == 'PP-20260415-0001'
        assert len(data['details']) == 1

    @pytest.mark.asyncio
    async def test_plan_detail_not_found(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_plan_detail = AsyncMock(side_effect=ValueError("计划不存在"))
            response = await client.get("/api/v1/plans/detail/999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_plan_success(self, client, mock_db):
        mock_create_result = {
            'id': 1,
            'plan_no': 'PP-20260415-0001',
            'plan_month': '2026-04',
            'customer_name': '测试客户',
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.create_plan = AsyncMock(return_value=mock_create_result)
            response = await client.post(
                "/api/v1/plans/create",
                json={
                    "customer_id": 1,
                    "customer_name": "测试客户",
                    "plan_month": "2026-04",
                    "details": [
                        {
                            "product_id": 1,
                            "product_name": "测试产品A",
                            "barcode": "6901234567890",
                            "quantity": 100,
                            "plan_date": "2026-04-15",
                            "remark": "",
                        }
                    ],
                    "remark": "",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert 'data' in data

    @pytest.mark.asyncio
    async def test_create_plan_validation_error(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.create_plan = AsyncMock(side_effect=ValueError("客户不存在"))
            response = await client.post(
                "/api/v1/plans/create",
                json={
                    "customer_id": 999,
                    "customer_name": "不存在客户",
                    "plan_month": "2026-04",
                    "details": [
                        {
                            "product_id": 1,
                            "product_name": "测试产品A",
                            "barcode": "6901234567890",
                            "quantity": 100,
                            "plan_date": "2026-04-15",
                            "remark": "",
                        }
                    ],
                    "remark": "",
                },
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_edit_plan_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.update_plan = AsyncMock(return_value=None)
            response = await client.put(
                "/api/v1/plans/edit/1",
                json={
                    "status": "confirmed",
                    "remark": "确认计划",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '更新成功' in data['message']

    @pytest.mark.asyncio
    async def test_edit_plan_not_found(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.update_plan = AsyncMock(side_effect=ValueError("计划不存在"))
            response = await client.put(
                "/api/v1/plans/edit/999",
                json={"status": "confirmed"},
            )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_plan_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.delete_plan = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/plans/delete/1")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '删除成功' in data['message']

    @pytest.mark.asyncio
    async def test_delete_plan_not_found(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.delete_plan = AsyncMock(side_effect=ValueError("计划不存在"))
            response = await client.delete("/api/v1/plans/delete/999")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_update_detail_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.update_detail = AsyncMock(return_value=None)
            response = await client.put(
                "/api/v1/plans/details/1",
                json={"quantity": 200, "remark": "更新数量"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '明细更新成功' in data['message']

    @pytest.mark.asyncio
    async def test_delete_detail_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.delete_detail = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/plans/details/1")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '明细删除成功' in data['message']

    @pytest.mark.asyncio
    async def test_customer_summary_success(self, client, mock_db):
        mock_summary = {
            'customers': [
                {
                    'customer_id': 1,
                    'customer_name': '测试客户',
                    'plan_qty': 200,
                    'inventory_qty': 100,
                    'shipped_qty': 50,
                    'remaining_qty': 150,
                    'warning_count': 0,
                }
            ],
            'total_plan_qty': 200,
            'total_inventory_qty': 100,
            'total_shipped_qty': 50,
            'total_remaining_qty': 150,
            'warning_count': 0,
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_customer_summary = AsyncMock(return_value=mock_summary)
            response = await client.get(
                "/api/v1/plans/customer-summary",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data['customers']) == 1
        assert data['customers'][0]['customer_name'] == '测试客户'

    @pytest.mark.asyncio
    async def test_inventory_compare_success(self, client, mock_db):
        mock_compare = {
            'details': [
                {
                    'detail_id': 1,
                    'product_id': 1,
                    'product_name': '测试产品A',
                    'barcode': '6901234567890',
                    'customer_name': '测试客户',
                    'plan_qty': 100,
                    'inventory_qty': 50,
                    'diff': -50,
                    'stock_status': 'insufficient',
                }
            ],
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_inventory_compare = AsyncMock(return_value=mock_compare)
            response = await client.get(
                "/api/v1/plans/inventory-compare",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data['details']) == 1

    @pytest.mark.asyncio
    async def test_shipment_progress_success(self, client, mock_db):
        mock_progress = {
            'details': [
                {
                    'detail_id': 1,
                    'product_name': '测试产品A',
                    'barcode': '6901234567890',
                    'plan_qty': 100,
                    'shipped_qty': 50,
                    'remaining_qty': 50,
                    'percent': 50.0,
                    'shipment_status': 'in_progress',
                }
            ],
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_shipment_progress = AsyncMock(return_value=mock_progress)
            response = await client.get(
                "/api/v1/plans/shipment/progress",
                params={"plan_id": 1},
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data['details']) == 1
        assert data['details'][0]['percent'] == 50.0

    @pytest.mark.asyncio
    async def test_shipment_progress_not_found(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_shipment_progress = AsyncMock(side_effect=ValueError("计划不存在"))
            response = await client.get(
                "/api/v1/plans/shipment/progress",
                params={"plan_id": 999},
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_staging_list_success(self, client, mock_db):
        mock_records = [
            {'id': 1, 'customer_name': '暂存客户', 'product_name': '产品B', 'quantity': 50}
        ]
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_staging_list = AsyncMock(return_value=mock_records)
            response = await client.get("/api/v1/plans/staging/list")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert data['total'] == 1

    @pytest.mark.asyncio
    async def test_staging_clear_success(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.clear_staging = AsyncMock(return_value=None)
            response = await client.delete("/api/v1/plans/staging/clear")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
        assert '清空' in data['message']

    @pytest.mark.asyncio
    async def test_validate_barcode_found(self, client, mock_db):
        mock_validation = {
            'valid': True,
            'product_name': '测试产品A',
            'product_id': 1,
            'message': '产品已找到',
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.validate_barcode = AsyncMock(return_value=mock_validation)
            response = await client.get(
                "/api/v1/plans/validate-barcode",
                params={"q": "6901234567890"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['valid'] is True
        assert data['product_name'] == '测试产品A'

    @pytest.mark.asyncio
    async def test_monthly_calendar_success(self, client, mock_db):
        mock_calendar = {
            'year': 2026,
            'month': 4,
            'days_in_month': 30,
            'plans_by_date': {
                '2026-04-15': [{'customer_name': '测试客户', 'quantity': 100}]
            },
            'customers': [{'id': 1, 'name': '测试客户'}],
        }
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_monthly_calendar = AsyncMock(return_value=mock_calendar)
            response = await client.get(
                "/api/v1/plans/monthly",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['days_in_month'] == 30

    @pytest.mark.asyncio
    async def test_monthly_aggregated_success(self, client, mock_db):
        mock_aggregated = {
            'year': 2026,
            'month': 4,
            'days_in_month': 30,
            'rows': [
                {
                    'date': '2026-04-15',
                    'dayNum': 15,
                    'weekday': '周三',
                    '_dayNum': 15,
                    'totalQty': 200,
                    'customerCount': 1,
                    'customers': [{'customer_id': 1, 'customer_name': '测试客户', 'quantity': 200}],
                    '_pct': 0.0,
                }
            ],
            'sku_summary': [
                {'product_id': 1, 'product_name': '测试产品A', 'barcode': '6901234567890', 'total_qty': 200, 'produced_qty': 50}
            ],
            'sku_date_index': {'1': ['2026-04-15']},
            'customers': [{'customer_id': 1, 'customer_name': '测试客户', 'plan_qty': 200, 'produced_qty': 50, 'remaining_qty': 150}],
            'customer_totals': {'1': 200},
            'fifo_degraded': False,
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_monthly_aggregated = AsyncMock(return_value=mock_aggregated)
            response = await client.get(
                "/api/v1/plans/monthly-aggregated",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['days_in_month'] == 30
        assert len(data['rows']) == 1
        assert data['rows'][0]['totalQty'] == 200
        assert len(data['sku_summary']) == 1
        assert len(data['customers']) == 1

    @pytest.mark.asyncio
    async def test_monthly_aggregated_with_customer_filter(self, client, mock_db):
        mock_aggregated = {
            'year': 2026,
            'month': 4,
            'days_in_month': 30,
            'rows': [],
            'sku_summary': [],
            'sku_date_index': {},
            'customers': [],
            'customer_totals': {},
            'fifo_degraded': False,
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_monthly_aggregated = AsyncMock(return_value=mock_aggregated)
            response = await client.get(
                "/api/v1/plans/monthly-aggregated",
                params={"year": 2026, "month": 4, "customer_id": 1},
            )
        assert response.status_code == 200
        assert mock_svc.get_monthly_aggregated.call_args[0][3] == 1

    @pytest.mark.asyncio
    async def test_monthly_aggregated_error(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_monthly_aggregated = AsyncMock(side_effect=RuntimeError("DB error"))
            response = await client.get(
                "/api/v1/plans/monthly-aggregated",
                params={"year": 2026, "month": 4},
            )
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_day_details_success(self, client, mock_db):
        mock_day_details = {
            'date': '2026-04-15',
            'weekday': '周三',
            'plans': [
                {
                    'detail_id': 1,
                    'product_id': 1,
                    'product_name': '测试产品A',
                    'barcode': '6901234567890',
                    'customer_id': 1,
                    'customer_name': '测试客户',
                    'quantity': 100,
                    'produced_qty': 20,
                    'remaining_qty': 80,
                    'remark': '',
                }
            ],
            'by_customer': {'测试客户': [{'detail_id': 1, 'product_name': '测试产品A', 'quantity': 100}]},
            'produced_pct': 20.0,
            'fifo_degraded': False,
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_day_details = AsyncMock(return_value=mock_day_details)
            response = await client.get(
                "/api/v1/plans/day-details",
                params={"year": 2026, "month": 4, "day": 15},
            )
        assert response.status_code == 200
        data = response.json()
        assert data['date'] == '2026-04-15'
        assert len(data['plans']) == 1
        assert data['plans'][0]['product_name'] == '测试产品A'
        assert len(data['by_customer']) == 1
        assert data['produced_pct'] == 20.0

    @pytest.mark.asyncio
    async def test_day_details_with_customer_filter(self, client, mock_db):
        mock_day_details = {
            'date': '2026-04-15',
            'weekday': '周三',
            'plans': [],
            'by_customer': {},
            'produced_pct': 0.0,
            'fifo_degraded': False,
        }
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_day_details = AsyncMock(return_value=mock_day_details)
            response = await client.get(
                "/api/v1/plans/day-details",
                params={"year": 2026, "month": 4, "day": 15, "customer_id": 2},
            )
        assert response.status_code == 200
        assert mock_svc.get_day_details.call_args[0][4] == 2

    @pytest.mark.asyncio
    async def test_day_details_error(self, client, mock_db):
        with patch('fastapi_app.api.v1.endpoints.purchase_plan.purchase_plan_service') as mock_svc:
            mock_svc.get_day_details = AsyncMock(side_effect=RuntimeError("DB error"))
            response = await client.get(
                "/api/v1/plans/day-details",
                params={"year": 2026, "month": 4, "day": 15},
            )
        assert response.status_code == 500
