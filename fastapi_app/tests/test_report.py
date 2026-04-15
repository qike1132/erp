"""报表统计模块测试"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestReportSchemas:
    def test_report_log_item(self):
        from fastapi_app.schemas.report import ReportLogItem
        item = ReportLogItem(customer="测试", product_name="产品A", quantity=100)
        assert item.customer == "测试"
        assert item.quantity == 100

    def test_report_export_request(self):
        from fastapi_app.schemas.report import ReportExportRequest
        req = ReportExportRequest(type="order", customer="客户1")
        assert req.type == "order"


class TestReportService:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_empty_result(self):
        """Mock an empty text query result"""
        result = MagicMock()
        result.scalar.return_value = 0
        result.fetchall.return_value = []
        return result

    @pytest.mark.asyncio
    async def test_get_order_logs_empty(self, mock_db, mock_empty_result):
        from fastapi_app.services.report_service import get_order_logs
        mock_db.execute = AsyncMock(return_value=mock_empty_result)

        result = await get_order_logs(mock_db, page=1, per_page=20)
        assert result['logs'] == []
        assert result['stats']['total_count'] == 0

    @pytest.mark.asyncio
    async def test_get_stockin_logs_empty(self, mock_db, mock_empty_result):
        from fastapi_app.services.report_service import get_stockin_logs
        mock_db.execute = AsyncMock(return_value=mock_empty_result)

        result = await get_stockin_logs(mock_db, page=1, per_page=20)
        assert result['logs'] == []

    @pytest.mark.asyncio
    async def test_get_stockout_logs_empty(self, mock_db, mock_empty_result):
        from fastapi_app.services.report_service import get_stockout_logs
        mock_db.execute = AsyncMock(return_value=mock_empty_result)

        result = await get_stockout_logs(mock_db, page=1, per_page=20)
        assert result['logs'] == []

    @pytest.mark.asyncio
    async def test_get_deduction_logs_empty(self, mock_db, mock_empty_result):
        from fastapi_app.services.report_service import get_deduction_logs
        mock_db.execute = AsyncMock(return_value=mock_empty_result)

        result = await get_deduction_logs(mock_db, page=1, per_page=20)
        assert result['logs'] == []


class TestReportEndpoints:
    @pytest.mark.asyncio
    async def test_order_logs_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/reports/order-logs")
        assert response.status_code == 200
        data = response.json()
        assert data['logs'] == []

    @pytest.mark.asyncio
    async def test_stockin_logs_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/reports/stockin-logs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_stockout_logs_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/reports/stockout-logs")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_deduction_logs_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/reports/deduction-logs")
        assert response.status_code == 200
