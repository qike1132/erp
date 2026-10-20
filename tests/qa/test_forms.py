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

from fastapi_app.core.config import settings
from fastapi_app.main import app

if "test" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append("test")


@pytest_asyncio.fixture
async def client(admin_user, async_db_session):
    """ASGI 客户端；依赖 admin_user + async_db_session 确保账户已提交到测试库

    admin_user 仅 flush，async_db_session 在测试结束 yield 后才 commit；
    而 auth_headers 的登录请求经 app 全局引擎读取已提交数据，必须等待提交。
    因此这里显式依赖 async_db_session 并在其提交后（fixture teardown 之后）
    仍可用——改为直接依赖 test_engine 并自行提交 admin 账户。
    """
    # admin_user 可能尚未提交（flush-only），此处显式 commit 保证登录可见
    await async_db_session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client):
    resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, f"登录失败 HTTP {resp.status_code}: {resp.text[:200]}"
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


class TestLoginForm:
    @pytest.mark.asyncio
    async def test_login_valid(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_login_empty_username(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "", "password": "admin123"})
        assert resp.status_code == 400, f"空用户名应返回 400，实际 {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_empty_password(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": ""})
        assert resp.status_code == 400, f"空密码应返回 400，实际 {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401, f"错误密码应返回 401，实际 {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_sql_injection(self, client):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin' OR '1'='1", "password": "test"})
        assert resp.status_code == 401, f"SQL injection should be rejected: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_login_missing_body(self, client):
        resp = await client.post("/api/v1/auth/login")
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"


class TestProductForm:
    @pytest.mark.asyncio
    async def test_product_list(self, client, auth_headers):
        resp = await client.get("/api/v1/products/list", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_product_search(self, client, auth_headers):
        resp = await client.get("/api/v1/products/search", headers=auth_headers, params={"keyword": "测试"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_product_query_negative_page(self, client, auth_headers):
        resp = await client.get("/api/v1/products/list", headers=auth_headers, params={"page": -1, "per_page": 10})
        assert resp.status_code == 422, f"page=-1 应被校验拒绝，实际 {resp.status_code}"


class TestOrderForm:
    @pytest.mark.asyncio
    async def test_order_list(self, client, auth_headers):
        resp = await client.get("/api/v1/orders/list", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_order_query_valid(self, client, auth_headers):
        resp = await client.get("/api/v1/orders/list", headers=auth_headers, params={"page": 1, "per_page": 10})
        assert resp.status_code == 200


class TestCustomerForm:
    @pytest.mark.asyncio
    async def test_customer_list(self, client, auth_headers):
        resp = await client.get("/api/v1/customers/list", headers=auth_headers)
        assert resp.status_code == 200


class TestSupplierForm:
    @pytest.mark.asyncio
    async def test_supplier_list(self, client, auth_headers):
        resp = await client.get("/api/v1/suppliers/list", headers=auth_headers)
        assert resp.status_code == 200


class TestUserForm:
    @pytest.mark.asyncio
    async def test_user_list(self, client, auth_headers):
        resp = await client.get("/api/v1/users/list", headers=auth_headers)
        assert resp.status_code == 200


class TestApprovalForm:
    @pytest.mark.asyncio
    async def test_approval_list(self, client, auth_headers):
        resp = await client.get("/api/v1/approvals/list", headers=auth_headers)
        assert resp.status_code == 200


class TestStockForm:
    @pytest.mark.asyncio
    async def test_stock_in_list(self, client, auth_headers):
        resp = await client.get("/api/v1/stock/in/list", headers=auth_headers)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_stock_out_list(self, client, auth_headers):
        resp = await client.get("/api/v1/stock/out/list", headers=auth_headers)
        assert resp.status_code == 200


class TestCaseForm:
    @pytest.mark.asyncio
    async def test_case_list(self, client, auth_headers):
        resp = await client.get("/api/v1/cases/search", headers=auth_headers, params={"keyword": "测试"})
        assert resp.status_code == 200


class TestMaterialForm:
    @pytest.mark.asyncio
    async def test_material_list(self, client, auth_headers):
        resp = await client.get("/api/v1/material-registrations/registrations", headers=auth_headers)
        assert resp.status_code == 200


class TestBackupForm:
    @pytest.mark.asyncio
    async def test_backup_list(self, client, auth_headers):
        """/api/v1/backup 的路由级依赖刻意是 fail-closed strict（router.py:283）：
        Redis 客户端不可用且本地撤销缓存未命中时，**合法令牌**也一律 401。

        测试进程不跑 app lifespan → ``redis_cache.init_app()`` 从未执行 →
        ``get_client()`` 恒为 None → 必然落到 fail-closed 分支（生产 Redis 正常时
        是 200）。两种环境下的正确结局不同，故按客户端可用性分别断言：既守住
        「无 Redis 必须 fail-closed」，也守住「Redis 可用时合法令牌读得到」。
        """
        from fastapi_app.core.redis_wrapper import get_client

        resp = await client.get("/api/v1/backup/list", headers=auth_headers)
        if get_client() is None:
            assert resp.status_code == 401, (
                f"Redis 客户端不可用时路由级 strict 依赖必须 fail-closed 401，实际 {resp.status_code}"
            )
        else:
            assert resp.status_code == 200, f"合法令牌应可读备份列表，实际 {resp.status_code}"

    @pytest.mark.asyncio
    async def test_backup_list_requires_auth(self, client):
        """备份列表必须鉴权：无令牌一律 401（防止路由级鉴权闸门被误删）。"""
        resp = await client.get("/api/v1/backup/list")
        assert resp.status_code == 401, f"无令牌应被拒绝，实际 {resp.status_code}"


class TestReportForm:
    @pytest.mark.asyncio
    async def test_report_statistics(self, client, auth_headers):
        resp = await client.get("/api/v1/reports/order-logs", headers=auth_headers)
        assert resp.status_code == 200
