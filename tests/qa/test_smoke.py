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
from tests.qa._shape_assert import assert_list_shape

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
    # 浏览器登录把令牌放 httpOnly cookie，body 的 access_token 恒为 None（auth.py:436-438）——
    # 从 body 取会得到空串、只能靠 cookie 通，「Bearer 通道活着」就没被测到。
    token = client.cookies.get("access_token", "")
    assert token, "smoke 登录成功但 client cookie jar 里没有 access_token"
    return {"Authorization": f"Bearer {token}"}


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


#: 3.3（2026-10-17 审计 P2）：只断状态码时，「接口活着但返回空 / 形状漂移」会静默通过。
#: 对 5 个高频列表页补**形状断言**（不断数据内容，只断「有一个列表容器」）。
#: 判定实现与 tests/qa/test_forms.py 共用 `_shape_assert` —— 两处各写一份必然漂移。
SHAPE_EXPECT_LIST = {'客户订单', '产品清单', '客户管理', '出库管理', '系统管理'}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(SHAPE_EXPECT_LIST))
async def test_list_endpoints_return_list_shape(client, auth_headers, name):
    """高频列表页必须有列表容器，且 total/page（若存在）是整数。

    审计 3.3：``test_smoke.py`` 是全仓唯一在 ASGI 端到端层扫 19 个板块只读端点的用例，
    此前只断状态码 —— 端点返回 ``{}`` 或某个标量也照样「冒烟通过」。
    """
    method, url = next((m, u) for n, m, u, _b in SMOKE_TESTS if n == name)
    assert method == 'GET'
    resp = await client.get(url, headers=auth_headers)
    assert_list_shape(resp, name)
