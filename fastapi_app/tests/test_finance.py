"""财务统计接口测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestFinanceEndpoints:
    @pytest.mark.asyncio
    async def test_customer_summary_success(self, client, mock_db):
        """测试客户汇总接口 - 正常返回"""
        mock_service_result = {
            'success': True,
            'logs': [
                {
                    'customer': '测试客户A',
                    'total_quantity': 100,
                    'total_amount': 5000.0,
                    'stockout_count': 3,
                }
            ],
            'stats': {
                'total_count': 1,
                'total_quantity': 100,
                'total_amount': 5000.0,
            },
            'pagination': {
                'page': 1,
                'per_page': 20,
                'total': 1,
                'pages': 1,
            },
        }

        with patch('fastapi_app.services.finance_service.get_customer_summary',
                    new_callable=AsyncMock, return_value=mock_service_result):
            response = await client.get("/api/v1/finance/customer-summary")
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            assert len(data['logs']) == 1
            assert data['logs'][0]['customer'] == '测试客户A'

    @pytest.mark.asyncio
    async def test_customer_summary_with_filters(self, client, mock_db):
        """测试客户汇总接口 - 带筛选参数"""
        mock_service_result = {
            'success': True,
            'logs': [],
            'stats': {'total_count': 0, 'total_quantity': 0, 'total_amount': 0.0},
            'pagination': {'page': 1, 'per_page': 20, 'total': 0, 'pages': 0},
        }

        with patch('fastapi_app.services.finance_service.get_customer_summary',
                    new_callable=AsyncMock, return_value=mock_service_result):
            response = await client.get(
                "/api/v1/finance/customer-summary",
                params={
                    'customer': '测试客户',
                    'start_date': '2026-01-01',
                    'end_date': '2026-12-31',
                    'page': 1,
                    'per_page': 10,
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            assert data['logs'] == []

    @pytest.mark.asyncio
    async def test_daily_amount_success(self, client, mock_db):
        """测试按日汇总金额接口 - 正常返回"""
        mock_service_result = {
            'success': True,
            'logs': [
                {
                    'date': '2026-01-15',
                    'total_quantity': 50,
                    'total_amount': 2500.0,
                    'stockout_count': 2,
                    'customer_names': '客户A、客户B',
                }
            ],
            'stats': {
                'total_count': 1,
                'total_quantity': 50,
                'total_amount': 2500.0,
            },
            'pagination': {
                'page': 1,
                'per_page': 20,
                'total': 1,
                'pages': 1,
            },
        }

        with patch('fastapi_app.services.finance_service.get_daily_amount',
                    new_callable=AsyncMock, return_value=mock_service_result):
            response = await client.get("/api/v1/finance/daily-amount")
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            assert data['logs'][0]['date'] == '2026-01-15'

    @pytest.mark.asyncio
    async def test_daily_amount_chart_success(self, client, mock_db):
        """测试按日汇总金额图表接口 - 正常返回"""
        mock_service_result = {
            'success': True,
            'chart': {
                'dates': ['2026-01-01', '2026-01-02'],
                'quantities': [100, 200],
                'amounts': [5000.0, 10000.0],
            }
        }

        with patch('fastapi_app.services.finance_service.get_daily_amount_chart',
                    new_callable=AsyncMock, return_value=mock_service_result):
            response = await client.get("/api/v1/finance/daily-amount-chart")
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            assert len(data['chart']['dates']) == 2
            assert data['chart']['amounts'] == [5000.0, 10000.0]

    @pytest.mark.asyncio
    async def test_daily_amount_chart_with_customer(self, client, mock_db):
        """测试按日汇总金额图表接口 - 带客户筛选"""
        mock_service_result = {
            'success': True,
            'chart': {
                'dates': [],
                'quantities': [],
                'amounts': [],
            }
        }

        with patch('fastapi_app.services.finance_service.get_daily_amount_chart',
                    new_callable=AsyncMock, return_value=mock_service_result):
            response = await client.get(
                "/api/v1/finance/daily-amount-chart",
                params={'customer': '不存在的客户'}
            )
            assert response.status_code == 200
            data = response.json()
            assert data['success'] is True
            assert data['chart']['dates'] == []
