"""端到端冒烟测试 - 覆盖关键 API 路径

Phase 5.2: FastAPI TestClient 集成测试
确保关键只读端点可访问、返回合理 schema，作为 CI 门禁基础。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestHealthEndpoints:
    """健康检查端点冒烟测试"""

    @pytest.mark.asyncio
    async def test_health(self, client):
        r = await client.get("/api/v1/aux/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_metrics(self, client):
        r = await client.get("/metrics")
        assert r.status_code in (200, 404)


class TestReadOnlyEndpoints:
    """只读端点冒烟测试 - 使用 mock_db 避免真实数据库"""

    @pytest.mark.asyncio
    async def test_product_search(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        r = await client.get("/api/v1/aux/product-search?q=test")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_customer_search(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        r = await client.get("/api/v1/customers/search?q=test")
        assert r.status_code == 200


class TestCSRFEnforcement:
    """CSRF 保护检查 - 确保写操作需要 token"""

    @pytest.mark.asyncio
    async def test_csrf_cookie_set(self, client):
        response = await client.get("/")
        assert response.status_code in (200, 303)
        cookie = client.cookies.get("fastapi_csrf_token")
        assert cookie is not None and len(cookie) > 0

    @pytest.mark.asyncio
    async def test_csrf_header_auto_attached(self, client):
        r = await client.post("/api/v1/ocr-import/create-task")
        assert r.status_code == 200
        assert "task_id" in r.json()


class TestOpenAPI:
    """OpenAPI schema 冒烟测试"""

    @pytest.mark.asyncio
    async def test_openapi_schema(self, client):
        r = await client.get("/api/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        assert "paths" in schema
        # 关键端点必须存在
        assert any("/aux/health" in p for p in schema["paths"])

    @pytest.mark.asyncio
    async def test_docs_accessible(self, client):
        r = await client.get("/api/docs")
        assert r.status_code == 200
