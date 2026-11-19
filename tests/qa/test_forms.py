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
from tests.qa._shape_assert import assert_list_shape

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
    # 浏览器登录把令牌放 httpOnly cookie，body 里是 None（见 auth.py:436-438）——
    # 原来这里取 body 的 access_token 得到空串，实际发出去的是 "Authorization: Bearer "
    # 这种**假覆盖**（请求全靠 cookie jar 才通）。改为从 cookie jar 取真实令牌，
    # 同时带 Bearer 与 cookie（服务端先认哪个都行）；Bearer **单独**可用由
    # test_bearer_channel_alone_is_accepted 钉住，否则两通道同在等于只测了 cookie。
    token = client.cookies.get("access_token", "")
    assert token, "登录成功但 client cookie jar 里没有 access_token"
    return {"Authorization": f"Bearer {token}"}


class TestLoginForm:
    @pytest.mark.asyncio
    async def test_login_valid(self, client):
        """浏览器登录：token 只进 httpOnly cookie，响应体 access_token 必须为 None。

        审计 2.5：原来只断 ``status_code == 200`` —— 「200 但既不下发 cookie 也不回
        任何 token」照样通过。这里钉住两条真实契约（见 auth.py:436-438）：
        1. cookie 必须下发且带 httpOnly（浏览器唯一的取 token 通道）；
        2. 响应体**不得**回传 token（防 XSS/日志/浏览器历史泄露，Capacitor 才回传）。
        """
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
        assert resp.status_code == 200, f"登录失败 HTTP {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert body.get("access_token") is None, (
            f"浏览器登录不得在响应体回传 access_token：{body}"
        )
        assert (body.get("user") or {}).get("username") == "admin", f"登录响应缺少用户信息：{body}"
        access_cookies = [
            c for c in resp.headers.get_list("set-cookie")
            if c.lower().startswith("access_token=")
        ]
        assert access_cookies, (
            f"登录成功但未下发 access_token cookie：{resp.headers.get_list('set-cookie')}"
        )
        assert "httponly" in access_cookies[0].lower(), (
            f"access_token cookie 必须 httpOnly（否则 JS 可读，等同 body 泄露）：{access_cookies[0]}"
        )

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
        assert_list_shape(resp, '产品列表')


    @pytest.mark.asyncio
    async def test_bearer_channel_alone_is_accepted(self, client, auth_headers):
        """Bearer 通道单独也要通 —— Capacitor 客户端唯一可用的通道。

        评审（2026-11-19）：`auth_headers` 现在带的是真令牌，但请求同时带着 client 的
        cookie jar，服务端先认 cookie 就永远测不到 `Authorization` 解析。这里清掉 cookie
        再发，「Bearer 通道活着」才有判定力。
        """
        client.cookies.clear()
        resp = await client.get("/api/v1/products/list", headers=auth_headers)
        assert_list_shape(resp, "产品列表(Bearer-only)")
    @pytest.mark.asyncio
    async def test_product_search(self, client, auth_headers):
        resp = await client.get("/api/v1/products/search", headers=auth_headers, params={"keyword": "测试"})
        assert_list_shape(resp, '产品搜索')

    @pytest.mark.asyncio
    async def test_product_query_negative_page(self, client, auth_headers):
        resp = await client.get("/api/v1/products/list", headers=auth_headers, params={"page": -1, "per_page": 10})
        assert resp.status_code == 422, f"page=-1 应被校验拒绝，实际 {resp.status_code}"


class TestOrderForm:
    @pytest.mark.asyncio
    async def test_order_list(self, client, auth_headers):
        resp = await client.get("/api/v1/orders/list", headers=auth_headers)
        assert_list_shape(resp, '订单列表')

    @pytest.mark.asyncio
    async def test_order_query_valid(self, client, auth_headers):
        resp = await client.get("/api/v1/orders/list", headers=auth_headers, params={"page": 1, "per_page": 10})
        assert_list_shape(resp, '订单列表(分页)')


class TestCustomerForm:
    @pytest.mark.asyncio
    async def test_customer_list(self, client, auth_headers):
        resp = await client.get("/api/v1/customers/list", headers=auth_headers)
        assert_list_shape(resp, '客户列表')


class TestSupplierForm:
    @pytest.mark.asyncio
    async def test_supplier_list(self, client, auth_headers):
        resp = await client.get("/api/v1/suppliers/list", headers=auth_headers)
        assert_list_shape(resp, '供应商列表')


class TestUserForm:
    @pytest.mark.asyncio
    async def test_user_list(self, client, auth_headers):
        resp = await client.get("/api/v1/users/list", headers=auth_headers)
        assert_list_shape(resp, '用户列表')


class TestApprovalForm:
    @pytest.mark.asyncio
    async def test_approval_list(self, client, auth_headers):
        resp = await client.get("/api/v1/approvals/list", headers=auth_headers)
        assert_list_shape(resp, '审批列表')


class TestStockForm:
    @pytest.mark.asyncio
    async def test_stock_in_list(self, client, auth_headers):
        resp = await client.get("/api/v1/stock/in/list", headers=auth_headers)
        assert_list_shape(resp, '入库列表')

    @pytest.mark.asyncio
    async def test_stock_out_list(self, client, auth_headers):
        resp = await client.get("/api/v1/stock/out/list", headers=auth_headers)
        assert_list_shape(resp, '出库列表')


class TestCaseForm:
    @pytest.mark.asyncio
    async def test_case_list(self, client, auth_headers):
        resp = await client.get("/api/v1/cases/search", headers=auth_headers, params={"keyword": "测试"})
        assert_list_shape(resp, '皮套搜索')


class TestMaterialForm:
    @pytest.mark.asyncio
    async def test_material_list(self, client, auth_headers):
        resp = await client.get("/api/v1/material-registrations/registrations", headers=auth_headers)
        assert_list_shape(resp, '来料登记列表')


class TestBackupForm:
    @pytest.mark.asyncio
    async def test_backup_list(self, client, auth_headers):
        """合法令牌在根集成套件的内存撤销存储下应可读备份列表。

        根 conftest 的 ``_in_memory_token_revocation`` 为每次用例提供独立、可判定的
        撤销存储，因此这里不是「Redis 故障且状态不可判定」场景。真正的 Redis 故障
        fail-closed 由 fastapi_app/tests/test_strict_auth_wiring.py 等专项测试覆盖。
        """
        resp = await client.get("/api/v1/backup/list", headers=auth_headers)
        assert_list_shape(resp, '备份列表')

    @pytest.mark.asyncio
    async def test_backup_list_requires_auth(self, client):
        """备份列表必须鉴权：无令牌一律 401（防止路由级鉴权闸门被误删）。"""
        resp = await client.get("/api/v1/backup/list")
        assert resp.status_code == 401, f"无令牌应被拒绝，实际 {resp.status_code}"


class TestReportForm:
    @pytest.mark.asyncio
    async def test_report_statistics(self, client, auth_headers):
        resp = await client.get("/api/v1/reports/order-logs", headers=auth_headers)
        assert_list_shape(resp, '报表日志列表')
