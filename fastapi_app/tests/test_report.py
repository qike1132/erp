"""报表统计模块测试"""
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestReportSchemas:
    def test_report_log_item(self):
        from fastapi_app.schemas.report import ReportLogItem
        item = ReportLogItem(customer="测试", product_name="产品A", quantity=100)
        assert item.customer == "测试"
        assert item.quantity == 100

    def test_report_response_keeps_flow_nos(self):
        """聚合行的还原单号与备注不得被 response_model 裁掉（回归 2026-10-08）。

        出货流水行内编辑/删除靠 stockout_nos 还原明细行，备货抵扣备注列读 order_note。
        二者曾不在 ReportLogItem 里，被 FastAPI 的 response_model 静默剔除，前端
        拿不到单号 → 弹「未能找到该组对应的明细记录」，行内操作从未生效。
        """
        from fastapi_app.schemas.report import ReportResponse
        resp = ReportResponse(logs=[{
            'stockout_nos': 'SO-20261006-0001',
            'order_note': '抵扣备注',
        }])
        row = resp.model_dump()['logs'][0]
        assert row['stockout_nos'] == 'SO-20261006-0001'
        assert row['order_note'] == '抵扣备注'

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
    async def test_get_order_logs_search_also_matches_order_no(self, mock_db, mock_empty_result):
        """搜索框兼搜订单号：product 关键字须同时匹配 o.order_no（2026-10-13）。

        前端搜索框占位符为「产品名称 / SKU / 订单号」，靠这一个 product 参数承载；
        若漏掉 o.order_no 条件，按订单号搜会恒空（且不报错）。
        """
        from fastapi_app.services.report_service import get_order_logs
        mock_db.execute = AsyncMock(return_value=mock_empty_result)

        await get_order_logs(mock_db, product='SO-2026', page=1, per_page=20)

        sqls = [str(call.args[0]) for call in mock_db.execute.call_args_list]
        assert sqls, '应至少执行一次查询'
        assert any('o.order_no LIKE :product' in sql for sql in sqls), '订单号搜索条件缺失'

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

    @pytest.mark.asyncio
    async def test_get_return_logs_empty(self, mock_db, mock_empty_result):
        from fastapi_app.services.report_service import get_return_logs
        mock_db.execute = AsyncMock(return_value=mock_empty_result)

        result = await get_return_logs(mock_db, page=1, per_page=20)
        assert result['logs'] == []
        assert result['stats']['total_count'] == 0


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

    @pytest.mark.asyncio
    async def test_return_logs_endpoint(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get("/api/v1/reports/return-logs")
        assert response.status_code == 200
        data = response.json()
        assert data['success'] is True
