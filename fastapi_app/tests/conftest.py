"""
测试配置 - FastAPI 测试用 conftest

提供测试用的 FastAPI 客户端和 mock 数据库会话。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from fastapi_app.core.config import settings
from fastapi_app.main import app

# 将测试用主机名加入 ALLOWED_HOSTS，
# 避免 TrustedHostMiddleware 拒绝 httpx 测试客户端的 Host: test 头
if "test" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append("test")


@pytest.fixture(autouse=True)
def _clear_l1_cache():
    """每个测试前清空 L1 进程内缓存，避免缓存键命中上一轮测试结果导致假阳性"""
    from fastapi_app.core.cache import invalidate_local_cache
    invalidate_local_cache('*')
    yield


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
    session.scalar = AsyncMock(return_value=0)
    session.add = MagicMock()
    session.expunge = MagicMock()
    # db.info 必须是真实 dict，否则 db_transaction 的
    # db.info.pop('post_commit_callbacks', []) 会因 AsyncMock 自动生成
    # coroutine 而报 'coroutine' object is not iterable
    session.info = {}

    class _MockNested:
        def __init__(self):
            self.commit = AsyncMock()
            self.rollback = AsyncMock()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    session.begin_nested = MagicMock(return_value=_MockNested())
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


@pytest_asyncio.fixture(autouse=True)
async def override_deps(mock_db, mock_current_user):
    """自动覆盖 FastAPI 依赖注入"""

    async def override_get_async_db():
        yield mock_db

    def override_get_sync_db():
        yield mock_db

    async def override_get_async_read_db():
        yield mock_db

    async def override_get_user_with_permissions():
        return mock_current_user

    async def override_get_current_user_id(request=None):
        return 1

    app.dependency_overrides.clear()
    from fastapi_app.core.database import get_async_db, get_async_read_db, get_sync_db
    app.dependency_overrides[get_async_db] = override_get_async_db
    app.dependency_overrides[get_async_read_db] = override_get_async_read_db
    app.dependency_overrides[get_sync_db] = override_get_sync_db

    from fastapi_app.core.deps import _get_user_with_permissions, get_current_user_id
    app.dependency_overrides[_get_user_with_permissions] = override_get_user_with_permissions
    app.dependency_overrides[get_current_user_id] = override_get_current_user_id

    # 避免 /api/health 等端点触发真实 DB/Redis 连接：
    # verify_db_connectivity / _get_async_redis_client 不走 FastAPI 依赖注入，
    # 若走真实连接会在测试进程中创建 asyncpg/redis 连接，污染 event loop
    # 导致后续测试报 "Event loop is closed" / "'NoneType' object has no attribute 'send'"。
    async def _fake_verify_db_connectivity() -> bool:
        return True

    async def _fake_get_async_redis_client():
        return None

    # 审计日志直接写入真实库（_write_audit_direct 用 async_engine）在测试环境无意义，
    # 且会触发真实 asyncpg 连接导致 event loop 污染。测试中审计写入置为 no-op。
    async def _noop_write_audit_direct(entries):
        return None

    with patch(
        'fastapi_app.core.database.verify_db_connectivity',
        side_effect=_fake_verify_db_connectivity,
    ), patch(
        # 批次1-4 客户端上提后 patch 目标同步更新（旧 notification_service 路径已失效）
        'fastapi_app.core.redis_client.get_async_redis_client',
        side_effect=_fake_get_async_redis_client,
    ), patch(
        'fastapi_app.core.audit_middleware._write_audit_direct',
        side_effect=_noop_write_audit_direct,
    ), patch(
        # 终极防护：阻止任何代码路径通过 async_engine 创建真实 asyncpg 连接。
        # 连接池在 teardown 时尝试优雅关闭已创建的连接，但 event loop 已关闭
        # → "'NoneType' object has no attribute 'send'" teardown 竞态。
        'fastapi_app.core.database.async_engine',
        None,
    ), patch(
        'fastapi_app.core.database._AsyncSessionLocal',
        None,
    ):
        yield

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client():
    """异步 HTTP 测试客户端

    自动处理 CSRF：先发 GET 请求获取 CSRF cookie，
    后续 POST/PUT/DELETE 请求自动携带 X-CSRF-Token header。
    同时设置 Bearer token，使 CSRF 中间件跳过验证。
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/api/health")
        csrf_cookie = ac.cookies.get("fastapi_csrf_token", "")
        if csrf_cookie:
            ac.headers["X-CSRF-Token"] = csrf_cookie
        ac.headers["Authorization"] = "Bearer test-token"
        yield ac
