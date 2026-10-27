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
import contextlib
import os
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 项目根目录
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

# 测试基线：强制非生产，避免继承本机 .env 的 APP_ENV=production（与
# fastapi_app/tests/conftest.py 同一约定）。否则 TrustedHostMiddleware 用
# 生产 ALLOWED_HOSTS 白名单拒绝测试客户端 Host 头（400 Invalid host header）、
# DOCS_URL/OPENAPI_URL 被置 None，根目录 tests/ 的冒烟/中间件用例在
# 生产机上假失败。需要生产行为的用例各自内部 monkeypatch.setenv。
# 必须在 import config/main 之前设置：config.py 的 load_dotenv(override=False)
# 不会覆盖已存在的环境变量。
os.environ["APP_ENV"] = "test"


# ============================================================
# 测试 Redis 隔离（P0.5，2026-10-01）
# ============================================================
# 限流器（core/limiter.py:56）在 import 期读取 REDIS_CACHE_URL 作为存储 URI，
# 端点缓存管理器（utils/redis_cache）由 lifespan 的 init_app 同源读取——
# 两者都必须在导入 app 之前重定向，否则测试的登录限流计数会写进生产
# Redis db0（实证：一轮 smoke 写入 LIMITS:.../auth/login... = 19）。
# 改库号为 15（测试专用）：主机/端口/口令不变，Redis 16 个逻辑库互不可见。
# 必须在 import config/main 之前设置：load_dotenv(override=False) 不会覆盖
# 已存在的环境变量。
def _redirect_test_redis() -> None:
    import re as _re

    env_path = os.path.join(_project_root, ".env")
    raw = None
    if os.path.exists(env_path):
        try:
            with open(env_path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip().startswith("REDIS_CACHE_URL="):
                        raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        except OSError:
            # .env 存在但不可读（生产机 ACL）时按「无 .env」处理，回落环境变量/默认值；
            # 测试引导不应因读不到凭据文件而整体 ImportError。
            raw = None
    if not raw:
        raw = os.getenv("REDIS_CACHE_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
    test_url = _re.sub(r"/\d*$", "/15", raw)
    os.environ["REDIS_CACHE_URL"] = test_url
    os.environ["REDIS_URL"] = test_url
    os.environ["REDIS_DB"] = "15"


_redirect_test_redis()

from sqlalchemy import text

from fastapi_app.core.config import settings
from fastapi_app.core.security import hash_password
from fastapi_app.main import app

# ============================================================
# 测试配置：注入测试专用主机名
# ============================================================
for _host in ("test", "testserver"):
    if _host not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS.append(_host)


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


def _assert_is_test_database(url: str) -> None:
    """硬闸（2026-10-17 审计 F-TEST-BE-TOP-03）：测试会话会 DROP SCHEMA public CASCADE，
    目标 URL 必须显式指向 *_test 库。

    派生逻辑 parsed.path.replace(f"/{db_name}", ...) 在 DB_NAME 与实际库名不一致时
    静默 no-op，返回的就是生产库 URL；TEST_DATABASE_URL 环境变量分支则完全无校验。
    两个来路都在这里收口——不满足直接终止整个会话，不跑任何用例。

    ⚠️ 必须按 **SQLAlchemy 的解析口径**判定，而不是 urlparse：PG 方言的
    ``create_connect_args`` 会 ``opts.update(url.query)``，URL 里的
    ``?database=erp_system`` / ``?host=…`` 会**覆盖**路径上的库名与主机。
    只看 path 会让
    ``postgresql+asyncpg://u:p@h:5432/erp_system_test?database=erp_system``
    通过校验，实际连的却是生产库 ⇒ DROP SCHEMA 打生产。故：这类覆盖参数一律拒绝。
    """
    from sqlalchemy.engine import make_url

    try:
        parsed = make_url(url)
    except Exception as exc:
        pytest.exit(
            f"拒绝运行：无法解析测试库 URL（{type(exc).__name__}: {exc}）：{url!r}",
            returncode=2,
        )

    forbidden = {'database', 'host', 'port'} & set(parsed.query.keys())
    if forbidden:
        pytest.exit(
            f"拒绝运行：测试库 URL 带了会覆盖连接目标的 query 参数 "
            f"{sorted(forbidden)}（SQLAlchemy 的 PG 方言会让它们覆盖 URL 路径上的"
            f"库名/主机）。请把它们写进 URL 路径本身，不要用 query 参数。",
            returncode=2,
        )

    if not (parsed.database or '').rstrip('/').endswith('_test'):
        pytest.exit(
            f"拒绝运行：测试库 URL 指向非测试库 {(parsed.database or '')!r}"
            f"（本会话会对它执行 DROP SCHEMA public CASCADE）。"
            f"请检查 DB_NAME 与 ASYNC_DATABASE_URL 的库名是否一致，"
            f"或显式设置指向 *_test 库的 TEST_DATABASE_URL。",
            returncode=2,
        )


_assert_is_test_database(TEST_DATABASE_URL)


# ============================================================
# 集成测试标记
# ============================================================
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: 需要数据库的集成测试（标记后自动获得 async_db_session 等 fixtures）"
    )
    # 2026-09-30：`flask_legacy` 标记已退役（全仓 0 处使用），故不再注册。
    #   该标记原先配合 CI 的 `-m "not flask_legacy"` 把 9 个测试文件整批反选，
    #   属「掩盖而非挂起」：连 skip 记录都不出现在日志里。现 9 个文件已分别
    #   改为带 reason 的显式 skip 或恢复正常收集，CI 侧也已移除反选参数。
    #   注：`--strict-markers` 只校验测试上实际应用的标记，不再注册它不影响
    #   任何现存调用；`pytest -m "not flask_legacy"` 也仍然可用（只是恒真）。


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
    # begin_nested 返回一个 async context manager
    nested = AsyncMock()
    nested.__aenter__ = AsyncMock(return_value=nested)
    nested.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested)
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

# PostgreSQL 咨询锁（advisory lock）键：双参数版本的作用域是**当前数据库**，
# 同一测试库互斥、不同测试库互不影响。0x7079/0x7465 = 'py'/'te'。
_TEST_DB_LOCK_KEY = (0x7079, 0x7465)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _exclusive_test_db_lock():
    """独占测试库：同一测试库不允许两个 pytest 进程并跑（审计 Z09-R5）。

    本目录的会话夹具会对测试库执行 ``DROP SCHEMA public CASCADE`` 整库重置。
    两个 pytest 进程并跑同一测试库时，一方在 DROP SCHEMA、另一方正在查数据，
    于是稳定复现"唯一键冲突 / 表不存在"这类**假红**（pitfalls §7 记过两次真实
    事故）。AGENTS.md §4 的"全量 pytest 必须独占单实例"此前只是文档约束。

    护栏用 PostgreSQL 咨询锁而不是锁文件：咨询锁按**数据库**加锁，同一测试库
    即便从不同工作目录/工作树启动也互斥（锁文件做不到这点——不同 checkout 各有
    自己的 logs/），且连接断开/进程退出即自动释放，不会留下要人工清理的死锁。

    拿不到锁就终止整个会话：此时继续跑只会产出假红，掩盖真红。
    """
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    conn = await engine.connect()
    try:
        acquired = await conn.scalar(
            text("SELECT pg_try_advisory_lock(:k1, :k2)"),
            {"k1": _TEST_DB_LOCK_KEY[0], "k2": _TEST_DB_LOCK_KEY[1]},
        )
        if not acquired:
            holder = await conn.execute(
                text(
                    "SELECT a.pid, a.application_name, a.state, a.backend_start "
                    "FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                    "WHERE l.locktype = 'advisory' AND l.classid = :k1 AND l.objid = :k2"
                ),
                {"k1": _TEST_DB_LOCK_KEY[0], "k2": _TEST_DB_LOCK_KEY[1]},
            )
            owners = "; ".join(
                f"pid={r.pid} app={r.application_name!r} state={r.state} since={r.backend_start}"
                for r in holder
            )
            pytest.exit(
                "拒绝运行：测试库已被另一个 pytest 实例占用"
                f"（{TEST_DATABASE_URL.rsplit('/', 1)[-1]}）。\n"
                "本会话的夹具会执行 DROP SCHEMA public CASCADE，并跑必然互撞出假红。\n"
                f"占用者：{owners or '未知（可能刚退出的实例）'}\n"
                "请先结束另一个实例，或用 TEST_DATABASE_URL 指向另一个 *_test 库。",
                returncode=2,
            )
        yield
    finally:
        with contextlib.suppress(Exception):
            await conn.execute(
                text("SELECT pg_advisory_unlock(:k1, :k2)"),
                {"k1": _TEST_DB_LOCK_KEY[0], "k2": _TEST_DB_LOCK_KEY[1]},
            )
        with contextlib.suppress(Exception):
            await conn.close()
        with contextlib.suppress(Exception):
            await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def test_engine(_exclusive_test_db_lock):
    """会话级数据库引擎 — 整次测试运行只创建一次。

    引擎创建（含连接池初始化）开销 ~300ms，
    session scope 可避免每个测试函数重复创建。

    使用 NullPool：pytest-asyncio 为每个测试函数新建事件循环，
    asyncpg 连接绑定在创建它的 loop 上；默认 QueuePool 会让上一轮
    loop 的残留连接进入下一轮，触发 "Event loop is closed" /
    "'NoneType' object has no attribute 'send'" teardown 错误。
    NullPool 每次检出新建连接、归还即关闭，连接永不跨 loop 存活。
    """
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)

    # 清理 + 重建测试库 schema（会话级，幂等）：
    # 先整体 DROP SCHEMA ... CASCADE 再重建，而不是 Base.metadata.drop_all。
    # 原因：测试库会积累已从模型中删除的孤儿表（如 device_token），
    # 其外键会阻止 drop_all 删除现存表（DependentObjectsStillExistError）；
    # 且 create_all 对已存在的旧表不会补新列，导致列漂移（如 product.default_bom_label）。
    # 整库重置一次性消除这两类漂移。仅作用于 erp_system_test 测试库。
    from fastapi_app.shared_models import Base
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        # pg_trgm：customer/case 等模型的 trgm GIN 索引依赖（DROP SCHEMA 会连带删除）
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # 测试会话结束时释放连接池
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def app_on_test_db(test_engine):
    """把应用的全局异步/同步引擎重定向到测试库（会话级）。

    tests/ 下的集成套件（test_stock_routes、qa/* 等）通过 ASGITransport
    直连真实 app（真实登录、真实依赖注入），要求 app 读写测试库。
    dispose 后置空引擎全局引用，首个异步入口会经
    ensure_engine_for_current_loop() 用重定向后的 URL 重建连接池。
    结束时恢复设置并再次 dispose，避免污染同进程内的其他测试会话。
    """
    from fastapi_app.core import database as db_mod
    from fastapi_app.core.config import settings as _settings

    saved_async_url = _settings.ASYNC_DATABASE_URL
    saved_sync_url = _settings.DATABASE_URL
    saved_replica_url = _settings.ASYNC_DATABASE_REPLICA_URL

    # 同步完成设置替换与引擎丢弃（ dispose 需要旧 loop，放 try 外统一处理）
    _settings.ASYNC_DATABASE_URL = TEST_DATABASE_URL
    # 同步引擎与生产同驱动（psycopg3）。⚠️ 必须 replace 成 '+psycopg' 而不是删空：
    # 只删 '+asyncpg' 会留下**裸 postgresql://**，SQLAlchemy 同步方言默认挑 psycopg2，
    # 而本仓只声明 psycopg3（psycopg2 仅在 requirements/dev.txt，供几个一次性运维脚本）。
    # 且裸 URL 会绕过 config.py 的**导入期**规范化（那段只在 config 首次加载时跑一次），
    # 于是 report_tasks 这类模块级建同步引擎的地方报 ModuleNotFoundError: psycopg2
    # （2026-10-12 实测：tests/test_report.py::TestExportTypeParity 2 条假红）。
    _settings.DATABASE_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg")
    _settings.ASYNC_DATABASE_REPLICA_URL = ""  # 测试不依赖只读副本

    stale = db_mod._async_engine
    db_mod._async_engine = None
    db_mod._AsyncSessionLocal = None
    db_mod.async_engine = None
    db_mod._engine_loop = None
    db_mod._read_engine = None
    db_mod._ReadSessionLocal = None
    db_mod._sync_engine = None
    db_mod._SyncSessionLocal = None

    if stale is not None:
        # 旧 loop 引擎清理失败不影响测试
        with contextlib.suppress(Exception):
            await stale.dispose(close=False)

    yield

    # 恢复设置，丢弃测试库引擎
    _settings.ASYNC_DATABASE_URL = saved_async_url
    _settings.DATABASE_URL = saved_sync_url
    _settings.ASYNC_DATABASE_REPLICA_URL = saved_replica_url
    stale = db_mod._async_engine
    db_mod._async_engine = None
    db_mod._AsyncSessionLocal = None
    db_mod.async_engine = None
    db_mod._engine_loop = None
    db_mod._read_engine = None
    db_mod._ReadSessionLocal = None
    db_mod._sync_engine = None
    db_mod._SyncSessionLocal = None
    if stale is not None:
        # 旧 loop 引擎清理失败不影响测试
        with contextlib.suppress(Exception):
            await stale.dispose(close=False)


@pytest.fixture(autouse=True)
def _isolate_memory_cache_fallback():
    """每个用例前后清空 redis_cache 的进程内内存降级缓存。

    测试进程不跑 lifespan → redis_cache 无客户端 → 端点缓存退化为进程级
    内存 dict；同进程内跨用例残留会让后跑的用例吃到先跑用例写入的缓存
    （test_list_customers "total 0 != 1" 的事故根因）。逐用例清空，等价于
    给每个用例一个独立的内存缓存库。私有属性访问仅限测试侧。
    """
    from utils.redis_cache import redis_cache

    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()
    yield
    redis_cache._fallback_cache.clear()
    redis_cache._fallback_timestamps.clear()


@pytest.fixture(autouse=True)
def _in_memory_token_revocation(monkeypatch):
    """根集成套件的撤销存储替身（不绕过写鉴权接线）。

    测试进程不跑 lifespan，Redis 客户端未初始化。这里替换的是**撤销存储**
    本身，而不是业务路由的 ``get_current_user_id_write_strict`` 依赖：
    所有写请求仍经过生产 fail-closed 依赖、token 解码、用户启用校验，
    只是撤销状态由一个每次用例清空的内存集合判定。这样既避免测试依赖
    本机 Redis，又不会让 5000+ 用例绕过新接线。

    真正的 Redis 故障 fail-closed 语义由
    ``fastapi_app/tests/test_strict_auth_wiring.py`` 与
    ``test_blacklist_degradation.py`` 单独覆盖。
    """
    import fastapi_app.core.deps as deps

    revoked: set[str] = set()

    async def _is_token_revoked(jti, *, fail_closed: bool = False) -> bool:
        return bool(jti and jti in revoked)

    async def _revoke_token(jti: str, exp: int) -> None:
        if jti:
            revoked.add(jti)

    monkeypatch.setattr(deps, 'is_token_revoked', _is_token_revoked)
    monkeypatch.setattr(deps, 'revoke_token', _revoke_token)


@pytest_asyncio.fixture
async def async_client(test_engine, async_db_session):
    """httpx AsyncClient，连接 FastAPI app。

    将 get_async_db/get_async_read_db 覆盖为共享的 async_db_session：
    端点请求与 fixture 数据（admin_user/test_product 等，仅 flush）
    处于同一事务，登录与业务断言均可见，无需中途提交。
    非请求路径（审计直写、健康检查、编号序列）走 app_on_test_db
    重定向后的真实引擎；此处先跑 loop 守卫，保证引擎在当前测试的
    事件循环上重建，numbering_sequence 等直接引用 _AsyncSessionLocal
    的路径才能拿到有效 sessionmaker。
    """
    from fastapi_app.core import database as db_mod
    from fastapi_app.core.database import get_async_db, get_async_read_db

    async def _shared_db():
        await db_mod.ensure_engine_for_current_loop()
        yield async_db_session

    app.dependency_overrides[get_async_db] = _shared_db
    app.dependency_overrides[get_async_read_db] = _shared_db

    # F-BE-CORE-07（CSRF 收口）后，Bearer+Cookie 的写请求必须过 double-submit：
    # X-CSRF-Token 头须与 fastapi_csrf_token cookie 同值。token 会在响应中被
    # 轮换，固定值会变陈旧 —— 用请求钩子在每次发请求前从 cookie jar 同步到头。
    # （httpx.Request 没有 cookies 属性，jar 在 client 上；client 在钩子闭包
    # 捕获时尚未实例化，故经 holder 间接引用运行时实例。）
    holder: dict[str, AsyncClient] = {}

    async def _sync_csrf_header(request: httpx.Request) -> None:
        client = holder.get('client')
        if client is None:
            return
        token = client.cookies.get("fastapi_csrf_token")
        if token:
            request.headers["X-CSRF-Token"] = token

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test",
            event_hooks={"request": [_sync_csrf_header]},
        ) as client:
            holder['client'] = client
            yield client
    finally:
        app.dependency_overrides.pop(get_async_db, None)
        app.dependency_overrides.pop(get_async_read_db, None)


@pytest_asyncio.fixture
async def async_db_session(test_engine):
    """异步数据库会话 — 提交模式（配合 app_on_test_db）。

    tests/ 集成套件通过真实 app 发请求，要求 fixture 数据对请求可见，
    因此提交而非回滚；隔离由会话开始时的整库重置（test_engine）提供。
    """
    async_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
        autoflush=False,  # 与应用 async_sessionmaker 保持一致，否则挂起的 INSERT
                          # 会在服务层 SELECT 时被隐式 flush，触发 FK 违反 → 500
    )

    async with async_session_factory() as session:
        yield session
        await session.commit()


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
        # CSRF double-submit 由 async_client 的请求钩子统一处理（见上），
        # 这里只需带 Bearer 头。
        return {"Authorization": f"Bearer {data.get('access_token', '')}"}
    # 登录失败时返回空头（测试会因 401 失败）
    return {}


# ============================================================
# Factory fixtures — 异步创建测试数据
# ============================================================

# 测试产品的基准库存：test_product 夹具进入用例时归位到这里、退出用例时写回
# （审计 Z09-R6：跨用例的库存漂移会让聚焦跑与全量跑的初值不一致）。
TEST_PRODUCT_BASELINE_STOCK = 100

@pytest_asyncio.fixture
async def admin_user(async_db_session):
    """创建或查询管理员用户"""
    from sqlalchemy import select

    from fastapi_app.shared_models.user import User

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
    from sqlalchemy import select

    from fastapi_app.shared_models.user import User

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
    """创建或查询测试产品（幂等，重复调用不抛唯一约束异常）

    用例级库存恢复（审计 Z09-R6）：夹具按 barcode 幂等查回**同一行**，而
    ``async_db_session`` 在用例结束会把挂起变更提交进共享测试库——用例之间因此
    通过 DB 隐式传递库存状态，依赖库存数值的断言在聚焦跑（``pytest -k``）与全量
    跑下可能因初值不同而结论不同（聚焦绿 ≠ 全量绿）。这里进入用例时把库存归位
    到基准值、退出用例时再写回，两个端口都断掉跨用例的状态传递。
    """
    from fastapi_app.shared_models.product import Product

    result = await async_db_session.execute(
        select(Product).where(Product.barcode == "TEST001")
    )
    product = result.scalars().first()
    if not product:
        product = Product(
            name="测试产品",
            barcode="TEST001",
            current_stock=TEST_PRODUCT_BASELINE_STOCK,
            initial_stock=TEST_PRODUCT_BASELINE_STOCK,
        )
        async_db_session.add(product)
        await async_db_session.flush()
    elif product.current_stock != TEST_PRODUCT_BASELINE_STOCK:
        # 上一用例（或历史脏数据）留下的库存漂移：归位到基准值
        product.current_stock = TEST_PRODUCT_BASELINE_STOCK
        await async_db_session.flush()
    # 库存结余闸门（2026-10-07）要求「包装部入库 − 已出货」≥ 出货量；
    # 测试产品无生产数据时闸门恒拒，故补一条包装部入库记录（幂等、足量）。
    from fastapi_app.shared_models import DailyProductionRecord
    has_packaging = (await async_db_session.execute(
        select(DailyProductionRecord.id).where(
            DailyProductionRecord.department == 'packaging',
            DailyProductionRecord.product_id == product.id,
        ).limit(1)
    )).scalar()
    if not has_packaging:
        async_db_session.add(DailyProductionRecord(
            department='packaging', product_id=product.id,
            product_name=product.name, barcode=product.barcode or '',
            quantity=100000, production_date=datetime.now(UTC).date(),
        ))
        await async_db_session.flush()
    yield product
    # 用例级恢复：库存写回基准值并提交，不把漂移留给下一个用例
    product.current_stock = TEST_PRODUCT_BASELINE_STOCK
    await async_db_session.commit()


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
            # 50：出库集成测试按 FIFO 受订单量约束（test_stockout_exact_stock 需要出货 50）
            quantity=50,
            order_date=datetime.now(UTC),
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
            stockin_date=datetime.now(UTC),
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
            stockout_date=datetime.now(UTC),
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
