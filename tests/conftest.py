"""
测试配置文件 — 纯 FastAPI 异步模式

Fixtures:
  单元测试级（Mock，无需数据库）：
    - mock_async_db         Mock 异步数据库会话
    - mock_user             Mock 当前用户

  集成测试级（httpx.AsyncClient，需要运行中的数据库）：
    - async_client          httpx AsyncClient 连接 FastAPI app
    - async_db_session      异步数据库会话（事务回滚，隔离测试）
    - auth_headers          管理员 JWT Bearer 认证头（通过 /api/v1/auth/login）

  Factory fixtures（异步，依赖 async_db_session）：
    - admin_user / normal_user    创建测试用户
    - test_product / test_products  创建测试产品
    - test_customer                 创建测试客户
    - test_order / test_stockin / test_stockout  创建测试业务记录
    - test_permission               创建测试权限

用法:
    # 集成测试（需要数据库）
    pytest tests/ -m integration

    # 单元测试（Mock，无需数据库）
    pytest tests/ -m "not integration"

标记说明:
    @pytest.mark.integration  — 需要数据库的集成测试
    无标记                       — 默认单元测试（Mocks）
"""
import os
import sys
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock, MagicMock

# 项目根目录
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

from fastapi_app.main import app
from fastapi_app.core.config import settings
from fastapi_app.core.security import hash_password


# ============================================================
# 测试配置：注入测试专用主机名
# ============================================================
if "test" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS.append("test")


# ============================================================
# 测试数据库 URL（可通过环境变量覆盖）
# ============================================================
def _build_test_db_url() -> str:
    """使用 TEST_DATABASE_URL 或基于主库配置构建测试库 URL

    优先使用 TEST_DATABASE_URL 环境变量；
    否则基于主库 URL 替换数据库名为 {db_name}_test。
    """
    test_url = os.getenv("TEST_DATABASE_URL")
    if test_url:
        return test_url

    # 安全替换：仅替换 URL 路径最后的数据库名（/dbname 之后的内容）
    from urllib.parse import urlparse, urlunparse

    db_name = os.getenv("DB_NAME", "erp_system")
    main_url = settings.ASYNC_DATABASE_URL
    parsed = urlparse(main_url)
    # path 格式为 /dbname，替换为 /dbname_test
    new_path = parsed.path.replace(f"/{db_name}", f"/{db_name}_test", 1)
    test_url = urlunparse(parsed._replace(path=new_path))
    return test_url


TEST_DATABASE_URL = _build_test_db_url()


# ============================================================
# 集成测试标记
# ============================================================
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: 需要数据库的集成测试（标记后自动获得 async_db_session 等 fixtures）"
    )
    config.addinivalue_line(
        "markers",
        "flask_legacy: Flask 遗留测试（迁移期间跳过）"
    )


# ============================================================
# 单元测试 fixtures（无数据库依赖）
# ============================================================

@pytest.fixture
def mock_async_db():
    """Mock 异步数据库会话（适用于服务层单测）"""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    session.add = MagicMock()
    session.begin_nested = MagicMock(return_value=AsyncMock())
    return session


@pytest.fixture
def mock_user():
    """Mock 当前用户（is_super=True，拥有所有权限）"""
    user = MagicMock()
    user.id = 1
    user.username = "admin"
    user.is_super = True
    user.factory = None
    user.has_permission = MagicMock(return_value=True)
    return user


# ============================================================
# 集成测试 fixtures（需要数据库）
# ============================================================

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """会话级数据库引擎 — 整次测试运行只创建一次。

    引擎创建（含连接池初始化）开销 ~300ms，
    session scope 可避免每个测试函数重复创建。
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # 确保表存在（会话级，幂等操作，只执行一次）
    from fastapi_app.shared_models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # 测试会话结束时释放连接池
    await engine.dispose()


@pytest_asyncio.fixture
async def async_client():
    """httpx AsyncClient，连接 FastAPI app"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def async_db_session(test_engine):
    """异步数据库会话 — 事务回滚模式，测试间不污染数据库。

    每个测试函数在独立事务中运行，结束时自动回滚，
    确保测试数据不写入数据库。

    依赖会话级 test_engine 避免重复建引擎和建表。
    """
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_factory() as session:
        async with session.begin() as transaction:
            yield session
            await transaction.rollback()


@pytest_asyncio.fixture
async def auth_headers(async_client, admin_user):
    """管理员 JWT Bearer 认证头，通过登录接口获取。

    依赖 admin_user fixture 确保管理员账户存在。
    """
    resp = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    if resp.status_code == 200:
        data = resp.json()
        return {"Authorization": f"Bearer {data.get('access_token', '')}"}
    # 登录失败时返回空头（测试会因 401 失败）
    return {}


# ============================================================
# Factory fixtures — 异步创建测试数据
# ============================================================

@pytest_asyncio.fixture
async def admin_user(async_db_session):
    """创建或查询管理员用户"""
    from fastapi_app.shared_models.user import User
    from sqlalchemy import select

    result = await async_db_session.execute(
        select(User).where(User.username == "admin")
    )
    user = result.scalars().first()
    if not user:
        user = User(
            username="admin",
            password=hash_password("admin123"),
            is_super=True,
            status=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()
    return user


@pytest_asyncio.fixture
async def normal_user(async_db_session):
    """创建或查询普通用户"""
    from fastapi_app.shared_models.user import User
    from sqlalchemy import select

    result = await async_db_session.execute(
        select(User).where(User.username == "testuser")
    )
    user = result.scalars().first()
    if not user:
        user = User(
            username="testuser",
            password=hash_password("test123"),
            is_super=False,
            status=True,
        )
        async_db_session.add(user)
        await async_db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_product(async_db_session):
    """创建或查询测试产品（幂等，重复调用不抛唯一约束异常）"""
    from fastapi_app.shared_models.product import Product

    result = await async_db_session.execute(
        select(Product).where(Product.barcode == "TEST001")
    )
    product = result.scalars().first()
    if not product:
        product = Product(
            name="测试产品",
            barcode="TEST001",
            current_stock=100,
            initial_stock=100,
        )
        async_db_session.add(product)
        await async_db_session.flush()
    return product


@pytest_asyncio.fixture
async def test_products(async_db_session):
    """创建或查询多个测试产品（幂等，5 个）"""
    from fastapi_app.shared_models.product import Product

    products = []
    for i in range(1, 6):
        barcode = f"TEST00{i}"
        result = await async_db_session.execute(
            select(Product).where(Product.barcode == barcode)
        )
        product = result.scalars().first()
        if not product:
            product = Product(
                name=f"测试产品{i}",
                barcode=barcode,
                current_stock=100 * i,
                initial_stock=100 * i,
            )
            async_db_session.add(product)
        products.append(product)
    await async_db_session.flush()
    return products


@pytest_asyncio.fixture
async def test_customer(async_db_session):
    """创建或查询测试客户（幂等）"""
    from fastapi_app.shared_models.customer import Customer

    result = await async_db_session.execute(
        select(Customer).where(Customer.name == "测试客户")
    )
    customer = result.scalars().first()
    if not customer:
        customer = Customer(
            name="测试客户",
            contact="张三",
            phone="13800138000",
            address="测试地址",
            status=True,
        )
        async_db_session.add(customer)
        await async_db_session.flush()
    return customer


@pytest_asyncio.fixture
async def test_order(async_db_session, test_product, test_customer):
    """创建或查询测试订单（幂等）"""
    from fastapi_app.shared_models.order import Order

    result = await async_db_session.execute(
        select(Order).where(Order.order_no == "ORD-TEST-001")
    )
    order = result.scalars().first()
    if not order:
        order = Order(
            order_no="ORD-TEST-001",
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=10,
            order_date=datetime.now(timezone.utc),
            status="待备货",
        )
        async_db_session.add(order)
        await async_db_session.flush()
    return order


@pytest_asyncio.fixture
async def test_stockin(async_db_session, test_product, test_customer):
    """创建或查询测试入库记录（幂等）"""
    from fastapi_app.shared_models.stock_in import StockIn

    result = await async_db_session.execute(
        select(StockIn).where(StockIn.stockin_no == "SI-TEST-001")
    )
    stockin = result.scalars().first()
    if not stockin:
        stockin = StockIn(
            stockin_no="SI-TEST-001",
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=50,
            stockin_date=datetime.now(timezone.utc),
        )
        async_db_session.add(stockin)
        await async_db_session.flush()
    return stockin


@pytest_asyncio.fixture
async def test_stockout(async_db_session, test_product, test_customer):
    """创建或查询测试出库记录（幂等）"""
    from fastapi_app.shared_models.stock_out import StockOut

    result = await async_db_session.execute(
        select(StockOut).where(StockOut.stockout_no == "SO-TEST-001")
    )
    stockout = result.scalars().first()
    if not stockout:
        stockout = StockOut(
            stockout_no="SO-TEST-001",
            product_id=test_product.id,
            customer=test_customer.name,
            quantity=20,
            stockout_date=datetime.now(timezone.utc),
        )
        async_db_session.add(stockout)
        await async_db_session.flush()
    return stockout


@pytest_asyncio.fixture
async def test_permission(async_db_session):
    """创建或查询测试权限（幂等）"""
    from fastapi_app.shared_models.permission import Permission

    result = await async_db_session.execute(
        select(Permission).where(Permission.code == "test_view")
    )
    permission = result.scalars().first()
    if not permission:
        permission = Permission(
            name="test_permission",
            description="测试权限",
            code="test_view",
        )
        async_db_session.add(permission)
        await async_db_session.flush()
    return permission
