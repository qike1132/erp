"""后端页面路由回收测试"""
import pytest


class TestBackendPageExposure:
    @pytest.mark.asyncio
    async def test_root_endpoint_returns_api_metadata(self, client):
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "version" in data
        assert data["docs"] == "/api/docs"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/login",
            "/order/list",
            "/product/list",
            "/stock/stockins",
            "/customer/list",
            "/finance/statistics",
            "/batch/management",
        ],
    )
    async def test_legacy_server_rendered_pages_are_not_exposed(self, client, path):
        response = await client.get(path)
        assert response.status_code == 404
