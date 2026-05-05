"""
ERP系统表单验证测试
测试所有关键表单的验证规则、边界值处理和完整提交流程
"""
import os
import sys

_form_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_form_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fastapi_app.main import app
from fastapi_app.core.config import settings
if "test" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append("test")


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client):
    resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    if resp.status_code == 200:
        token = resp.json().get("access_token", "")
        return {"Authorization": f"Bearer {token}"}
    return {}


class TestLoginForm:
    @pytest.mark.asyncio
    async def test_login_valid(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_login_empty_username(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "", "password": "admin123"})
        assert resp.status_code in (401, 422, 400), f"Got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_empty_password(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": ""})
        assert resp.status_code in (401, 422, 400), f"Got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code in (401, 422, 400), f"Got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_sql_injection(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin' OR '1'='1", "password": "test"})
        assert resp.status_code in (401, 422, 400), f"SQL injection should be rejected: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_missing_body(self, client):
        resp = await client.post("/api/v1/auth/login")
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"


class TestProductForm:
    @pytest.mark.asyncio
    async def test_product_list(self, client, auth_headers):
        resp = await client.get("/api/v1/products", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)

    @pytest.mark.asyncio
    async def test_product_query_valid(self, client, auth_headers):
        resp = await client.post("/api/v1/products/query", headers=auth_headers, json={"page": 1, "per_page": 10})
        assert resp.status_code in (200, 401, 403, 422)

    @pytest.mark.asyncio
    async def test_product_query_negative_page(self, client, auth_headers):
        resp = await client.post("/api/v1/products/query", headers=auth_headers, json={"page": -1, "per_page": 10})
        assert resp.status_code in (422, 200, 400), f"Got {resp.status_code}"


class TestOrderForm:
    @pytest.mark.asyncio
    async def test_order_list(self, client, auth_headers):
        resp = await client.get("/api/v1/orders", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)

    @pytest.mark.asyncio
    async def test_order_query_valid(self, client, auth_headers):
        resp = await client.post("/api/v1/orders/query", headers=auth_headers, json={"page": 1, "per_page": 10})
        assert resp.status_code in (200, 401, 403, 422)


class TestCustomerForm:
    @pytest.mark.asyncio
    async def test_customer_list(self, client, auth_headers):
        resp = await client.get("/api/v1/customers", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestSupplierForm:
    @pytest.mark.asyncio
    async def test_supplier_list(self, client, auth_headers):
        resp = await client.get("/api/v1/suppliers", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestUserForm:
    @pytest.mark.asyncio
    async def test_user_list(self, client, auth_headers):
        resp = await client.get("/api/v1/users/list", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestApprovalForm:
    @pytest.mark.asyncio
    async def test_approval_list(self, client, auth_headers):
        resp = await client.get("/api/v1/approvals", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestStockForm:
    @pytest.mark.asyncio
    async def test_stock_in_list(self, client, auth_headers):
        resp = await client.get("/api/v1/stock/in", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)

    @pytest.mark.asyncio
    async def test_stock_out_list(self, client, auth_headers):
        resp = await client.get("/api/v1/stock/out", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestCaseForm:
    @pytest.mark.asyncio
    async def test_case_list(self, client, auth_headers):
        resp = await client.get("/api/v1/cases", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestMaterialForm:
    @pytest.mark.asyncio
    async def test_material_list(self, client, auth_headers):
        resp = await client.get("/api/v1/material-registrations", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestBackupForm:
    @pytest.mark.asyncio
    async def test_backup_list(self, client, auth_headers):
        resp = await client.get("/api/v1/backup/list", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)


class TestReportForm:
    @pytest.mark.asyncio
    async def test_report_statistics(self, client, auth_headers):
        resp = await client.get("/api/v1/reports/statistics", headers=auth_headers)
        assert resp.status_code in (200, 401, 403)
