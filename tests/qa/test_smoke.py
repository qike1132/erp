"""ERP系统冒烟测试 - 覆盖19个业务板块核心功能（路由已修正）"""
import os
import sys
from datetime import datetime

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

# plans/summary/records 三个端点的 year&month 为必填/条件必填（purchase_plan.py:61、
# production_summary.py、daily_production.py），裸 GET 恒 422；带当前年月保持"冒烟=能通"语义
_YM = f"year={datetime.now().year}&month={datetime.now().month}"

SMOKE_TESTS = [
    ("采购中心", "GET", "/api/v1/purchase-center/orders", None),
    ("供应商管理", "GET", "/api/v1/suppliers/list", None),
    ("物料计算器", "GET", f"/api/v1/plans/list?{_YM}", None),
    ("来料登记", "GET", "/api/v1/material-registrations/registrations", None),
    ("核心业务", "GET", "/api/v1/dashboard/stats", None),
    ("产品清单", "GET", "/api/v1/products/list", None),
    ("客户订单", "GET", "/api/v1/orders/list", None),
    ("出库管理", "GET", "/api/v1/stock/out/list", None),
    ("出货计划", "GET", f"/api/v1/production-summary/summary?{_YM}", None),
    ("生产报表", "GET", f"/api/v1/daily-production/records?{_YM}", None),
    ("数据查询", "GET", "/api/v1/products/search", None),
    ("订单查询", "GET", "/api/v1/orders/list", None),
    ("报表管理", "GET", "/api/v1/reports/order-logs", None),
    ("皮套管理", "GET", "/api/v1/cases/items", None),
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
    # smoke 自建 admin：测试库每轮会话整库重建，不能依赖其他用例恰好建过号。
    # 经 app_on_test_db 重定向后的引擎写入测试库，幂等（存在即跳过）。
    from sqlalchemy import select

    from fastapi_app.core import database as db_mod
    from fastapi_app.core.security import hash_password
    from fastapi_app.shared_models.user import User

    await db_mod.ensure_engine_for_current_loop()
    async with db_mod._AsyncSessionLocal() as session:
        async with session.begin():
            exists = await session.scalar(select(User).where(User.username == "admin"))
            if not exists:
                session.add(User(
                    username="admin",
                    password=hash_password("admin123"),
                    is_super=True,
                    status=True,
                ))

    resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    # 登录失败不允许静默放行：返回空头会让全部用例吃 401 而 401 恰在断言白名单里，
    # 整个文件"假绿"，接口契约漂移（如 year&month 必填）被发现不了。
    assert resp.status_code == 200, f"smoke 登录失败 HTTP {resp.status_code}: {resp.text[:200]}"
    return {"Authorization": f"Bearer {resp.json().get('access_token', '')}"}


# 显式豁免（收口审计 2026-10-03）：整棵 /api/v1/backup 路由挂
# dependencies=[Depends(get_current_user_id_strict)]（router.py），黑名单校验
# fail-closed —— 测试环境无 Redis，携带有效 token 也 401。这是**已知且唯一**的
# 环境性豁免；除此之外任何端点返回 401/403 都会被断言拦下（本仓历史高发的
# 鉴权坏掉 401 / 权限码错配 403 不再被白名单掩盖）。
KNOWN_ENV_401 = {"数据备份"}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,method,url,body", SMOKE_TESTS)
async def test_smoke(client, auth_headers, name, method, url, body):
    if method == "GET":
        resp = await client.get(url, headers=auth_headers)
    elif method == "POST":
        resp = await client.post(url, headers=auth_headers, json=body or {})
    else:
        pytest.skip(f"Unsupported method: {method}")

    if name in KNOWN_ENV_401:
        # 豁免端点只要求"不要 5xx/404"——401 即环境性严格认证的预期结果
        assert resp.status_code in (200, 201, 401), \
            f"\n  【{name}】{method} {url}\n  状态码: HTTP {resp.status_code}\n  响应: {resp.text[:300]}"
    else:
        assert resp.status_code in (200, 201), \
            f"\n  【{name}】{method} {url}\n  状态码: HTTP {resp.status_code}\n  响应: {resp.text[:300]}"

    if resp.status_code in (200, 201):
        print(f"\n  [PASS] {name}: {method} {url}")
    else:
        print(f"\n  [ENV] {name}: {method} {url} -> {resp.status_code} (严格认证需 Redis，环境性豁免)")
