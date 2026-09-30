"""ERP系统冒烟测试 - 覆盖19个业务板块核心功能（路由已修正）"""
import os
import sys

_smoke_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_smoke_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fastapi_app.core.config import settings
from fastapi_app.main import app

if "test" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append("test")

SMOKE_TESTS = [
    ("采购中心", "GET", "/api/v1/purchase-center/orders", None),
    ("供应商管理", "GET", "/api/v1/suppliers/list", None),
    ("物料计算器", "GET", "/api/v1/plans/list", None),
    ("来料登记", "GET", "/api/v1/material-registrations/registrations", None),
    ("核心业务", "GET", "/api/v1/dashboard/stats", None),
    ("产品清单", "GET", "/api/v1/products/list", None),
    ("客户订单", "GET", "/api/v1/orders/list", None),
    ("出库管理", "GET", "/api/v1/stock/out/list", None),
    ("出货计划", "GET", "/api/v1/production-summary/summary", None),
    ("生产报表", "GET", "/api/v1/daily-production/records", None),
    ("数据查询", "GET", "/api/v1/products/search", None),
    ("订单查询", "GET", "/api/v1/orders/list", None),
    ("报表管理", "GET", "/api/v1/reports/order-logs", None),
    ("皮套管理", "GET", "/api/v1/cases/in/list", None),
    ("系统管理", "GET", "/api/v1/permissions/list", None),
    ("用户管理", "GET", "/api/v1/users/list", None),
    ("客户管理", "GET", "/api/v1/customers/list", None),
    ("审批管理", "GET", "/api/v1/approvals/list", None),
    ("数据备份", "GET", "/api/v1/backup/list", None),
]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("name,method,url,body", SMOKE_TESTS)
async def test_smoke(client, auth_headers, name, method, url, body):
    if method == "GET":
        resp = await client.get(url, headers=auth_headers)
    elif method == "POST":
        resp = await client.post(url, headers=auth_headers, json=body or {})
    else:
        pytest.skip(f"Unsupported method: {method}")

    assert resp.status_code in (200, 201, 403, 401), \
        f"\n  【{name}】{method} {url}\n  状态码: HTTP {resp.status_code}\n  响应: {resp.text[:300]}"

    if resp.status_code in (200, 201):
        print(f"\n  [PASS] {name}: {method} {url}")
    else:
        print(f"\n  [WARN] {name}: {method} {url} -> {resp.status_code} (需认证/权限)")
