"""
测试配置 - FastAPI 测试用 conftest

提供测试用的 FastAPI 客户端和 mock 数据库会话。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from fastapi_app.core.config import settings
from fastapi_app.main import app

# 将测试用主机名加入 ALLOWED_HOSTS，
# 避免 TrustedHostMiddleware 拒绝 httpx 测试客户端的 Host: test 头
if "test" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append("test")


@pytest.fixture
def mock_db():
    """Mock 异步数据库会话"""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_current_user():
    """Mock 当前用户"""
    user = MagicMock()
    user.id = 1
    user.username = "admin"
    user.is_super = True
    user.has_permission = MagicMock(return_value=True)
    return user


@pytest.fixture
def mock_product():
    """Mock 产品对象"""
    product = MagicMock()
    product.id = 1
    product.name = "测试产品A"
    product.barcode = "6901234567890"
    product.current_stock = 100
    product.initial_stock = 100
    return product


@pytest.fixture
def mock_order(mock_product):
    """Mock 订单对象"""
    order = MagicMock()
    order.id = 1
    order.order_no = "PO-20260101-0001"
    order.customer = "测试客户"
    order.product_id = 1
    order.quantity = 50
    order.product = mock_product
    order.status = "待备货"
    return order


@pytest.fixture(autouse=True)
def override_deps(mock_db, mock_current_user):
    """自动覆盖 FastAPI 依赖注入"""

    async def override_get_async_db():
        yield mock_db

    def override_get_sync_db():
        yield mock_db

    def override_get_user_with_permissions():
        return mock_current_user

    def override_require_permission(permission_name):
        def checker():
            return mock_current_user
        return checker

    app.dependency_overrides.clear()
    from fastapi_app.core.database import get_async_db, get_sync_db
    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[get_sync_db] = override_get_sync_db

    from fastapi_app.core.deps import _get_user_with_permissions, get_current_user_id
    app.dependency_overrides[_get_user_with_permissions] = override_get_user_with_permissions

    async def override_get_current_user_id(request=None):
        return 1  # Return mock user_id

    app.dependency_overrides[get_current_user_id] = override_get_current_user_id

    # 覆盖 require_permission 工厂，使它返回的 checker 也直接返回 mock 用户
    with patch('fastapi_app.core.deps.require_permission', side_effect=override_require_permission):
        yield

    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    """异步 HTTP 测试客户端

    自动处理 CSRF：先发 GET 请求获取 CSRF cookie，
    后续 POST/PUT/DELETE 请求自动携带 X-CSRFToken header。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 获取 CSRF cookie（starlette-csrf 在首个响应中设置）
        await ac.get("/api/health")
        csrf_cookie = ac.cookies.get("fastapi_csrf_token", "")
        # 设置默认 headers，使 POST 等非安全方法自动携带 CSRF token
        if csrf_cookie:
            ac.headers["X-CSRFToken"] = csrf_cookie
        yield ac
