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
import logging
import os
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# 项目根目录
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)

logger = logging.getLogger(__name__)

# 测试基线：强制非生产，避免继承本机 .env 的 APP_ENV=production（与
# fastapi_app/tests/conftest.py 同一约定）。否则 TrustedHostMiddleware 用
# 生产 ALLOWED_HOSTS 白名单拒绝测试客户端 Host 头（400 Invalid host header）、
# DOCS_URL/OPENAPI_URL 被置 None，根目录 tests/ 的冒烟/中间件用例在
# 生产机上假失败。需要生产行为的用例各自内部 monkeypatch.setenv。
# 必须在 import config/main 之前设置：config.py 的 load_dotenv(override=False)
# 不会覆盖已存在的环境变量。
os.environ["APP_ENV"] = "test"
# 同 fastapi_app/tests/conftest.py：测试环境显式开启文档端点，保证
# tests/test_docs_url_runtime.py 里 app 装配断言可验证；默认关闭契约由
# fastapi_app/tests/test_docs_endpoint_exposure.py 覆盖。
os.environ["API_DOCS_ENABLED"] = "true"


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


@pytest.fixture(scope="session", autouse=True)
def _isolate_maintenance_sentinel(tmp_path_factory):
    """把维护模式哨兵重定向到临时目录，禁止测试写仓库级 `logs/maintenance_mode.sentinel`。

    根因：`enter_maintenance()` 即使 Redis 客户端被 mock，仍会写本地哨兵文件。
    用例若在 enter 之后异常退出（未走到 `exit_maintenance()`），哨兵会残留，
    并在 `_SENTINEL_MAX_AGE` 窗口内让**后续所有**写请求返回 503 MAINTENANCE ——
    单点失败被放大成成片假红，掩盖真实结果。
    """
    from fastapi_app.core import maintenance as maintenance_module

    sentinel_dir = tmp_path_factory.mktemp("maintenance_sentinel")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        maintenance_module,
        "_MAINTENANCE_SENTINEL",
        sentinel_dir / "maintenance_mode.sentinel",
    )
    yield
    monkeypatch.undo()


# 测试期运行期证据隔离（死信目录 + 审计溢出文件）：实现见
# fastapi_app/tests/evidence_isolation.py，两棵测试树共用一份，避免两份实现漂移。
# pytest 会收集 conftest 命名空间里被 import 的 fixture。
from fastapi_app.tests.evidence_isolation import (  # noqa: F401
    _isolate_runtime_evidence_files,
)


# ============================================================
# 测试数据库 URL（可通过环境变量覆盖）
# ============================================================
def _build_test_db_url() -> str:
    """派生测试库 URL —— 唯一实现在 `fastapi_app/tests/_test_db_guard.py`。

    为什么改成委托（2026-11-17 OCR 复审）：
    提交 ``db90ad5d``（2026-11-16 审计 H-6）已把「测试库 URL 派生」收敛到
    `_test_db_guard.derive_test_db_url / resolve_test_db_url`，但根树 conftest 这份
    仍是**被否定的写法**：

        parsed.path.replace(f"/{db_name}", f"/{db_name}_test", 1)

    `DB_NAME` 与 URL 里实际库名不一致时它找不到子串 → **静默 no-op**，原样返回生产库 URL。
    失败形态没变（只是碰巧被下面的硬闸拦下，而拦法是把整场会话 pytest.exit(2)，
    一个模块拿不到 URL 就让几万条用例一条都跑不了）。

    `derive_test_db_url` 改为按 URL 里**实际的库名**追加 `_test`：不依赖 DB_NAME、
    不可能 no-op、query 参数原样保留（`?database=` 这类覆盖参数仍由硬闸拒绝）。
    `resolve_test_db_url` 先取 `TEST_DATABASE_URL`，缺失才派生——与本函数原来的分支顺序一致。

    两棵测试树（`tests/` 与 `fastapi_app/tests/`）是不同目录，但 conftest 早已把
    `_project_root` 插进 sys.path，且已 import `fastapi_app.tests.evidence_isolation`，
    故 `from fastapi_app.tests._test_db_guard import ...` 可行（同包，无循环依赖：
    该模块只在函数体内延迟 import pytest/sqlalchemy）。
    """
    from fastapi_app.tests._test_db_guard import resolve_test_db_url

    return resolve_test_db_url()


TEST_DATABASE_URL = _build_test_db_url()


def _assert_is_test_database(url: str) -> None:
    """硬闸（2026-10-17 审计 F-TEST-BE-TOP-03）：测试会话会 DROP SCHEMA public CASCADE，
    目标 URL 必须显式指向 *_test 库。

    2026-11-17 OCR 复审：判定逻辑收敛到 `_test_db_guard.assert_is_test_database`
    （提交 db90ad5d 的单一实现）。此前两棵树各有一份复制件，改一处漏一处就会让
    某一路来路裸奔——现在只留一份实现 + 一份回归锁
    （`fastapi_app/tests/test_test_db_guard_helper.py`，含 `?database=`/`?host=`/`?port=`
    这类**覆盖型 query 参数**的拒绝用例：PG 方言的 ``create_connect_args`` 会
    ``opts.update(url.query)``，只按 path 判定会让
    ``…/erp_system_test?database=erp_system`` 通过校验而实际连生产库）。

    本函数保留原名与「不满足即 pytest.exit(2)」的语义（`tests/test_test_db_url_guard.py`
    import 它）：`assert_is_test_database` 的 `exit_fn` 默认就是 ``pytest.exit``，
    ``returncode=2``，行为与改造前逐条一致。
    """
    from fastapi_app.tests._test_db_guard import assert_is_test_database

    assert_is_test_database(url)


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
    from tests._test_db_reset import ENV_SKIP, database_name_from_url, record_reset, reset_enabled

    async with engine.begin() as conn:
        if reset_enabled():
            # 留痕必须在 DROP **之前**（审计 TEST 区 1.4）：随后崩溃也能回答「谁清了哪个库」。
            tables_before = await conn.scalar(
                text("SELECT count(*) FROM information_schema.tables "
                     "WHERE table_schema = 'public'")
            )
            record_reset(
                database=database_name_from_url(TEST_DATABASE_URL),
                tables=int(tables_before or 0),
            )
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        else:
            # 逃生口：本轮不重置（仍在下面补缺表）。副作用要说清：残留数据与旧列都不会被清理。
            logger.warning(
                "按 %s 跳过测试库整库重置：残留数据/旧列不会被清理"
                "（create_all 不补已存在表的新列），本会话的偶发假红请先怀疑这一点",
                ENV_SKIP,
            )
            exists = await conn.scalar(
                text("SELECT count(*) FROM information_schema.schemata WHERE schema_name = 'public'")
            )
            if not exists:
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
    # 登录内存限流器是进程级单例：跨用例累计会把后续 auth_headers 打成 429，
    # 再级联成 401（2026-10-30 CI 实测）。逐用例清空，等价独立限流库。
    from fastapi_app.core.limiter import memory_limiter

    memory_limiter.reset()
    # Redis 客户端可能绑定在上一个已关闭的事件循环上；丢弃引用让 ensure_client()
    # 在当前 loop 重建（health 用例 "Event loop is closed" 的根因）。
    redis_cache.redis_client = None
    from fastapi_app.core.redis_client import reset_async_redis_client

    reset_async_redis_client()
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
async def non_admin_headers(async_client, normal_user):
    """普通用户（零权限码）的认证头 —— 用于断言写端点对非超管真的 403。

    3.1（2026-10-17 审计 P2）：根套件的 ``auth_headers`` 只用 admin（``is_super=True``），
    绝大多数用例跑在超管身份下，**权限依赖是否正确根本不参与判定** —— 端点漏写
    ``require_permission``、或把 ``_manage`` 写成 ``_view``，根套件不会变红，而线上表现是
    「普通员工能删单 / 能改采购单」。这里的普通用户不带任何 permission，因此任何
    「带权限码依赖」的写端点都必须 403。
    """
    resp = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "testuser", "password": "test123"},
    )
    assert resp.status_code == 200, (
        f"普通用户登录失败 HTTP {resp.status_code}: {resp.text[:200]}"
    )
    # 浏览器登录把令牌放 httpOnly cookie，body 的 access_token 恒为 None（auth.py:436-438）——
    # 从 body 取会得到空串，实际发出去的是 "Authorization: Bearer "（全靠 cookie jar 才通）。
    token = async_client.cookies.get("access_token", "")
    assert token, "普通用户登录成功但 cookie jar 里没有 access_token"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_product(async_db_session):
    """每个用例创建独立产品，杜绝库存、订单和流水跨用例隐式传递。

    根集成套件会提交真实测试库事务。旧实现按固定 barcode 复用同一产品，再在
    teardown 仅恢复 current_stock，无法清理订单、出入库单和流水等关联状态。
    现在改用唯一产品/SKU：同一用例内的订单与出入库夹具仍共享该产品，不同用例
    不再共享任何可变业务行，也无需依赖 teardown 把数据库“修回”某个快照。
    """
    from fastapi_app.shared_models import DailyProductionRecord
    from fastapi_app.shared_models.product import Product

    suffix = uuid4().hex[:10]
    product = Product(
        name=f"测试产品-{suffix}",
        barcode=f"TEST-{suffix}",
        current_stock=TEST_PRODUCT_BASELINE_STOCK,
        initial_stock=TEST_PRODUCT_BASELINE_STOCK,
    )
    async_db_session.add(product)
    await async_db_session.flush()
    # 库存结余闸门要求「包装部入库 − 已出货」≥ 出货量；每个新产品都独立补足量记录。
    async_db_session.add(DailyProductionRecord(
        department='packaging', product_id=product.id,
        product_name=product.name, barcode=product.barcode or '',
        quantity=100000, production_date=datetime.now(UTC).date(),
    ))
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
    """每个用例创建独立订单，固定数量 50 但不复用状态或关联行。"""
    from fastapi_app.shared_models.order import Order

    order = Order(
        order_no=f"ORD-T-{uuid4().hex[:12]}",
        product_id=test_product.id,
        customer=test_customer.name,
        quantity=50,
        order_date=datetime.now(UTC),
        status="待备货",
    )
    async_db_session.add(order)
    await async_db_session.flush()
    return order


@pytest_asyncio.fixture
async def test_stockin(async_db_session, test_product, test_customer):
    """每个用例创建独立备货记录，不复用数量、确认状态或关联出库。"""
    from fastapi_app.shared_models.stock_in import StockIn

    stockin = StockIn(
        stockin_no=f"SI-T-{uuid4().hex[:12]}",
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
    """每个用例创建独立出库记录，不复用数量、退货量或订单绑定。"""
    from fastapi_app.shared_models.stock_out import StockOut

    stockout = StockOut(
        stockout_no=f"SO-T-{uuid4().hex[:12]}",
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
