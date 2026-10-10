"""
数据库会话管理 - 全异步模式

异步引擎：asyncpg（FastAPI 运行时）
同步引擎：psycopg3（Alembic 迁移专用）

仅支持 PostgreSQL。
"""

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.config import settings
from fastapi_app.core.exceptions import run_post_commit_callbacks


def _get_pool_config() -> dict:
    """根据 Worker 数动态计算连接池大小，防止超出 PostgreSQL max_connections。

    PgBouncer 启用时（PGBOUNCER_ENABLED=true），应用侧连接池显著缩小：
    PgBouncer 负责连接复用，应用侧只需少量连接到 PgBouncer 即可，
    避免应用侧连接池与 PgBouncer 连接池叠加导致连接数膨胀。
    """
    workers = int(os.getenv("UVICORN_WORKERS", "4"))
    # 确保: workers × (pool_size + max_overflow) < PG max_connections (默认100)
    # 留 20 连接给 ARQ/迁移/管理工具
    available = int(os.getenv("DB_MAX_CONNECTIONS", "100")) - 20

    # PgBouncer 启用时减小应用侧连接池（PgBouncer 负责连接复用）
    pgbouncer_enabled = os.getenv("PGBOUNCER_ENABLED", "false").lower() in ("true", "1", "yes")
    if pgbouncer_enabled:
        # PgBouncer transaction 模式下，应用侧每个 worker 只需少量连接
        # 除数更大（workers*4 / workers*6），使单 worker 连接数更少
        pool_size = max(3, available // (workers * 4))
        max_overflow = max(2, available // (workers * 6))
    else:
        pool_size = max(5, available // (workers * 2))
        max_overflow = max(3, available // (workers * 3))

    config: dict[str, Any] = {
        "pool_size": pool_size,
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        # 连接最长存活秒数：到期回收重建，避免复用坏连接。
        # 必须 < 服务器 idle_session_timeout，否则池中连接被服务器杀掉后仍被应用取用
        # → asyncpg 抛 "cannot switch to state 15; another operation (2) is in progress"
        # （state 2 = PROTOCOL_ERROR_CONSUME；曾致物化视图刷新任务间歇失败，2026-10-07）。
        # 服务器现值 idle_session_timeout='30min'（同日由 5min 调大），故取 1500s（25min，留 5min 余量）。
        # 守卫：tests/test_pool_recycle_vs_idle_timeout.py。
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "1500")),
        "max_overflow": max_overflow,
        "pool_pre_ping": True,
        "pool_use_lifo": True,  # LIFO 策略，减少空闲连接
    }
    if pgbouncer_enabled:
        # 第十轮落地：PgBouncer transaction 模式下，同一客户端连接的事务会被
        # 分摊到不同服务器连接，asyncpg 默认的预备语句（prepared statement）跨
        # 事务复用会报 `prepared statement ... does not exist`。标准做法是关掉
        # 客户端语句缓存（用简单查询协议），对 ORM 生成的短查询性能影响可忽略。
        config["connect_args"] = {"statement_cache_size": 0}
    return config


_pool_config = _get_pool_config()

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker | None = None
async_engine: AsyncEngine | None = None
_rebuild_lock = asyncio.Lock()

# 引擎连接池所属的事件循环。asyncpg 连接绑定在创建它的 loop 上；
# pytest-asyncio 为每个测试新建 loop，若跨 loop 复用池中连接，
# 会在检出/清理阶段报 "Event loop is closed" 或
# "'NoneType' object has no attribute 'send'"。生产环境 loop 与进程同寿命，
# 此守卫在生产中恒为 no-op（见 ensure_engine_for_current_loop）。
_engine_loop: asyncio.AbstractEventLoop | None = None


async def ensure_engine_for_current_loop() -> None:
    """确保异步引擎连接池运行在当前事件循环上。

    检测到 running loop 与建池 loop 不一致（仅测试环境会出现）时，
    丢弃旧引擎并重建。旧池中连接属于已关闭的旧 loop，无法优雅关闭，
    因此以 close=False 丢弃，避免清理阶段产生
    "Exception terminating connection ... Event loop is closed" 噪声日志。
    """
    global _engine_loop, _async_engine, _AsyncSessionLocal, async_engine
    global _read_engine, _ReadSessionLocal

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        return  # 同步上下文调用，无法判定 loop，交由首个异步入口处理

    if _engine_loop is running and _async_engine is not None:
        return

    stale = _async_engine
    stale_read = _read_engine
    # 同步完成换库，避免并发协程在 await 点交错时重复重建
    _async_engine = None
    _AsyncSessionLocal = None
    async_engine = None
    _read_engine = None
    _ReadSessionLocal = None
    _engine_loop = running
    _init_async_engine()

    if stale is not None:
        try:
            from fastapi_app.core.slow_query import setup_slow_query_listener

            assert _async_engine is not None  # noqa: S101
            setup_slow_query_listener(_async_engine.sync_engine)
        except ImportError as e:
            logger.warning('慢查询监听器初始化失败: %s', e)
        try:
            await stale.dispose(close=False)
        except Exception:  # defensive: 旧 loop 引擎清理失败不应影响当前请求
            logger.debug('旧事件循环引擎清理失败（已忽略）', exc_info=True)
        if stale_read is not None:
            try:
                await stale_read.dispose(close=False)
            except Exception:  # defensive: 同上，尽力而为
                logger.debug('旧事件循环只读引擎清理失败（已忽略）', exc_info=True)


def _init_async_engine():
    global _async_engine, _AsyncSessionLocal, async_engine
    if _async_engine is not None:
        return

    _async_engine = create_async_engine(
        settings.ASYNC_DATABASE_URL,
        **_pool_config,
        echo=False,
    )
    _AsyncSessionLocal = async_sessionmaker(
        bind=_async_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    async_engine = _async_engine


# TODO(P3): 副作用导入 - _init_async_engine() 在模块导入时自动执行，属于隐式副作用。
# 理想方案是在 main.py lifespan 中显式调用 _init_async_engine()，但当前许多模块
# 依赖 `from fastapi_app.core.database import async_engine` 时引擎已初始化，
# 直接移除会导致数据库连接不建立。保留自动调用以保证兼容性，后续重构应在
# main.py lifespan 启动入口先调用 _init_async_engine()。
_init_async_engine()

try:
    from fastapi_app.core.slow_query import setup_slow_query_listener
    assert _async_engine is not None  # noqa: S101
    setup_slow_query_listener(_async_engine.sync_engine)
except ImportError as e:
    logger.warning('慢查询监听器初始化失败: %s', e)


def _register_slow_listener_for_read_engine():
    """为只读引擎注册慢查询监听器（延迟执行，确保引擎已创建）"""
    if _read_engine is not None:
        try:
            from fastapi_app.core.slow_query import setup_slow_query_listener
            setup_slow_query_listener(_read_engine.sync_engine)
            logger.debug("只读引擎慢查询监听器已注册")
        except (ImportError, Exception) as e:  # broad-except: 数据库连接容错，初始化失败不应阻断启动
            logger.warning('只读引擎慢查询监听器注册失败: %s', e)


_sync_engine: Engine | None = None
_SyncSessionLocal: sessionmaker | None = None


def _init_sync_engine():
    global _sync_engine, _SyncSessionLocal
    if _sync_engine is not None:
        return

    _sync_engine = create_engine(
        settings.DATABASE_URL,
        **_pool_config,
        echo=False,
    )
    _SyncSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=_sync_engine
    )


def get_sync_engine():
    _init_sync_engine()
    return _sync_engine


def SyncSession():  # noqa: N802 - 兼容遗留调用方（utils.audit 等）依赖的公开 API 名称
    """获取同步数据库会话（兼容历史 API 名称，lazy 初始化）。

    用法：with SyncSession() as session: ...（返回 SQLAlchemy Session 实例，
    支持上下文管理器语义，自动关闭连接）。
    此名称为 utils.audit 等遗留调用方依赖的公开接口。
    """
    _init_sync_engine()
    if _SyncSessionLocal is None:
        raise RuntimeError('同步数据库引擎初始化失败')
    return _SyncSessionLocal()


# 提交失败计数器的惰性缓存（见 _commit_failure_counter()）
_COMMIT_FAILURE_COUNTER = None


def _commit_failure_counter():
    """获取「事务提交失败」计数器（惰性初始化，避免 metrics ↔ database 循环导入）。

    名称遵循仓库既有约定（*_total，如 domain_event_publish_failures_total）；
    注册走 core.metrics 的 _get_or_create_counter，热重载时不会重复注册。
    prometheus_client 缺失时 core.metrics 返回空实现，此处无需分支。
    """
    global _COMMIT_FAILURE_COUNTER
    if _COMMIT_FAILURE_COUNTER is None:
        from fastapi_app.core.metrics import _get_or_create_counter

        _COMMIT_FAILURE_COUNTER = _get_or_create_counter(
            "db_commit_failures_total",
            "事务提交失败次数（响应已发送但数据未落库，静默丢失风险）",
        )
    return _COMMIT_FAILURE_COUNTER


async def get_async_db(request: Request = None):  # type: ignore[assignment]
    """异步数据库会话依赖（Unit of Work 模式）

    - 请求成功时自动 commit
    - 请求异常时自动 rollback
    - 服务层应使用 flush() 而非 commit()，由本依赖统一控制事务边界

    注意：备份恢复操作（psql 路径）会 DROP+CREATE 数据库，导致当前 session
    的连接失效。此依赖对 commit/rollback 错误进行宽容处理，避免恢复成功后
    因 session 失效而返回 500 错误。
    """
    await ensure_engine_for_current_loop()
    if _AsyncSessionLocal is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_async_engine()")
    async with _AsyncSessionLocal() as session:
        try:
            yield session
        except (RuntimeError, OSError, ValueError, SQLAlchemyError):
            try:
                await session.rollback()
            except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                logger.warning("Session rollback failed (may be broken after psql restore)", exc_info=True)
            raise
        # FastAPI 0.106+ 语义：依赖收尾在响应发送之后执行，commit 失败时客户端已收到
        # 成功响应。此处显式 ERROR 告警 + 指标计数（监控可对关键字段告警），防止静默数据丢失。
        try:
            await session.commit()
        except (RuntimeError, OSError, ValueError, SQLAlchemyError):
            # request_id 由 request_id_middleware 写入 request.state；db_name 与
            # config._build_database_uri() 同源（Settings 未声明 DB_NAME 字段，
            # 写 settings.DB_NAME 会 AttributeError，故直接读环境变量）。
            request_id = getattr(getattr(request, "state", None), "request_id", None)
            path = getattr(getattr(request, "url", None), "path", None)
            db_name = os.getenv("DB_NAME", "erp_system")
            _commit_failure_counter().inc()
            logger.error(
                "事务提交失败：响应已发送但数据未落库（静默丢失风险） "
                "request_id=%s db_name=%s path=%s",
                request_id,
                db_name,
                path,
                exc_info=True,
                extra={"request_id": request_id, "db_name": db_name, "path": path},
            )
            try:
                await session.rollback()
            except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                logger.warning("Session rollback failed (may be broken after psql restore)", exc_info=True)
            raise
        # 提交成功后执行服务层注册的 post-commit 回调（缓存失效、事件广播等）。
        # 此前只有 db_transaction 会跑回调；走 Unit-of-Work 路径的端点（batch 导入、
        # order 删除等十余个）注册的回调被静默丢弃 —— run_post_commit_callbacks 的
        # docstring 明说这类入口「必须在提交后显式调用」。回调失败不影响响应
        # （内部已兜底），且此时业务数据已提交，绝不能因回调失败而 raise。
        try:
            await run_post_commit_callbacks(session)
        except (RuntimeError, OSError, ValueError, SQLAlchemyError) as exc:
            logger.warning("post-commit 回调执行失败（不影响已提交事务）: %s", exc, exc_info=True)


from contextlib import asynccontextmanager, suppress


@asynccontextmanager
async def get_async_db_context():
    """异步数据库会话上下文管理器（用于 ARQ 任务等非请求场景）

    注意：备份恢复操作（psql 路径）会 DROP+CREATE 数据库，导致当前 session
    的连接失效。此上下文管理器对 commit/rollback 错误进行宽容处理，避免恢复
    成功后因 session 失效而抛出异常。
    """
    await ensure_engine_for_current_loop()
    if _AsyncSessionLocal is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_async_engine()")
    async with _AsyncSessionLocal() as session:
        try:
            yield session
        except (RuntimeError, OSError, ValueError, SQLAlchemyError):
            try:
                await session.rollback()
            except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                logger.warning("Session rollback failed (may be broken after psql restore)", exc_info=True)
            raise
        try:
            await session.commit()
        except (RuntimeError, OSError, ValueError, SQLAlchemyError):
            logger.error("事务提交失败（ARQ 任务上下文）：任务将按异常处理", exc_info=True)
            try:
                await session.rollback()
            except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                logger.warning("Session rollback failed (may be broken after psql restore)", exc_info=True)
            raise
        # 提交成功后执行 post-commit 回调（与 get_async_db 同款）：ARQ 任务等
        # 非请求场景注册的缓存失效/领域事件回调此前被静默丢弃。回调失败不影响
        # 已提交事务（run_post_commit_callbacks 内部已兜底）。
        try:
            await run_post_commit_callbacks(session)
        except (RuntimeError, OSError, ValueError, SQLAlchemyError) as exc:
            logger.warning("post-commit 回调执行失败（不影响已提交事务）: %s", exc, exc_info=True)


def require_async_session_local() -> async_sessionmaker:
    """返回已初始化的异步会话工厂；未初始化时抛出可操作的错误。

    为什么需要它：直接写 `_AsyncSessionLocal()` 时，若引擎尚未初始化会得到

        TypeError: 'NoneType' object is not callable

    —— 信息量极低，排查成本高。本函数把它转成明确的 RuntimeError，
    与 `get_async_db` / `get_async_db_context` 的口径保持一致。

    同时这也让 mypy 能完成类型收窄（`_AsyncSessionLocal` 声明为
    `async_sessionmaker | None`，直接调用会报 `"None" not callable`）。
    """
    if _AsyncSessionLocal is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_async_engine()")
    return _AsyncSessionLocal


# ==================== 只读副本（读写分离） ====================

_read_engine = None
_ReadSessionLocal = None


def _init_read_engine():
    """初始化只读副本引擎（延迟加载，未配置时回退到主库）"""
    global _read_engine, _ReadSessionLocal
    if _read_engine is not None:
        return

    replica_url = settings.ASYNC_DATABASE_REPLICA_URL
    if not replica_url:
        logger.info("未配置只读副本，读取操作将使用主库")
        return

    # 副本池在主池基础上减半（评审 2026-10-10 P0-3）：主池+副本池若各用一份
    # pool_config，峰值 2×(pool_size+max_overflow)×workers 会超 PG
    # max_connections。副本侧已有 1s 快速失败 + 熔断降级主库（见下方常量），
    # 池减半不损可用性。
    read_pool_config = dict(_pool_config)
    read_pool_config["pool_size"] = max(2, _pool_config["pool_size"] // 2)
    read_pool_config["max_overflow"] = max(1, _pool_config["max_overflow"] // 2)

    _read_engine = create_async_engine(
        replica_url,
        **read_pool_config,
        echo=False,
    )
    _ReadSessionLocal = async_sessionmaker(
        bind=_read_engine,
        class_=AsyncSession,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    logger.info("只读副本引擎初始化成功: %s", replica_url.split("@")[-1] if "@" in replica_url else replica_url)
    _register_slow_listener_for_read_engine()
    _reset_read_replica_circuit()  # 新建/重建副本引擎 → 熔断状态重新判定


# 只读副本快速失败阈值（秒）：副本不可达/连接池耗尽/断连时，超过该阈值即降级主库
# （pool_timeout 默认 30s）。正常往返在毫秒级，1s 预算足够宽裕又能在真故障时快速失败。
_READ_REPLICA_CHECKOUT_TIMEOUT = 1.0
# 连续失败达到该次数即熔断，冷却期内不再逐请求探测副本，直接走主库。
_READ_REPLICA_FAIL_THRESHOLD = 3
# 熔断冷却时长（秒）：到期后放行一次探测，成功则复位。
_READ_REPLICA_COOLDOWN_SECONDS = 60.0

# 熔断状态（进程内；UVICORN_WORKERS 各 worker 独立判定，可接受）
_read_replica_fail_count = 0
_read_replica_circuit_open_until = 0.0  # 以 time.monotonic() 为基准


def _read_replica_circuit_is_open() -> bool:
    """熔断是否处于打开（冷却）状态"""
    return time.monotonic() < _read_replica_circuit_open_until


def _record_read_replica_failure() -> None:
    """记一次副本探测失败；连续失败达阈值即进入冷却。"""
    global _read_replica_fail_count, _read_replica_circuit_open_until
    _read_replica_fail_count += 1
    if _read_replica_fail_count >= _READ_REPLICA_FAIL_THRESHOLD:
        _read_replica_circuit_open_until = time.monotonic() + _READ_REPLICA_COOLDOWN_SECONDS
        logger.warning(
            "只读副本连续失败 %d 次，熔断 %.0fs：期间读操作直接走主库",
            _read_replica_fail_count, _READ_REPLICA_COOLDOWN_SECONDS,
        )


def _reset_read_replica_circuit() -> None:
    """副本探测成功（或连接池重建）后复位熔断状态。"""
    global _read_replica_fail_count, _read_replica_circuit_open_until
    _read_replica_fail_count = 0
    _read_replica_circuit_open_until = 0.0


async def get_async_read_db():
    """只读数据库会话依赖（用于报表/列表查询，走只读副本）

    - 未配置副本时自动回退到主库
    - 副本连接在阈值内未就绪（不可达/池耗尽/断连）时快速降级主库，
      防止副本故障把请求拖入数秒级等待
    - 连续失败达阈值即熔断：冷却期内不再逐请求探测副本，直接走主库，
      避免副本长期亚健康时每个读请求都固定等满超时（2026-10-09：实测
      每请求固定付出约 2s，一天触发 25 次）
    - 无 commit/rollback（只读操作无需事务控制）
    """
    _init_read_engine()

    if _ReadSessionLocal is None:
        # 未配置副本：回退到主库
        async for session in get_async_db():
            yield session
        return

    if _read_replica_circuit_is_open():
        # 已熔断：跳过探测，直接主库
        async for primary_session in get_async_db():
            yield primary_session
        return

    session = _ReadSessionLocal()
    try:
        # 主动触发连接检出（含 pool_pre_ping）并施加快速失败超时
        async with asyncio.timeout(_READ_REPLICA_CHECKOUT_TIMEOUT):
            await session.execute(text("SELECT 1"))
    except (TimeoutError, SQLAlchemyError, OSError) as e:
        _record_read_replica_failure()
        logger.warning("只读副本连接不可用（%.1fs），降级到主库: %s", _READ_REPLICA_CHECKOUT_TIMEOUT, e)
        # 超时/断连的连接必须作废，不能原样放回池里——否则后续请求会继续
        # 检出这条坏连接，把一次故障放大成每个请求都等满超时。invalidate/close
        # 本身含 rollback I/O，也套超时：黑洞式故障（TCP 挂着不响应）时
        # 清理段不能成为第二个无限等待点。清理尽力而为，失败不影响降级路径。
        with suppress(TimeoutError, RuntimeError, OSError, ValueError, SQLAlchemyError):
            async with asyncio.timeout(_READ_REPLICA_CHECKOUT_TIMEOUT):
                await session.invalidate()
        with suppress(TimeoutError, RuntimeError, OSError, ValueError, SQLAlchemyError):
            async with asyncio.timeout(_READ_REPLICA_CHECKOUT_TIMEOUT):
                await session.close()
        async for primary_session in get_async_db():
            yield primary_session
        return
    _reset_read_replica_circuit()
    try:
        yield session
    finally:
        await session.close()


async def dispose_async_engines():
    global _async_engine, _AsyncSessionLocal, async_engine, _engine_loop
    global _read_engine, _ReadSessionLocal
    if _async_engine is not None:
        try:
            await _async_engine.dispose()
        except (OperationalError, DisconnectionError) as e:
            logger.warning("异步引擎释放异常（可能已关闭）: %s", e)
    _async_engine = None
    _AsyncSessionLocal = None
    async_engine = None
    _engine_loop = None
    # 只读副本引擎一并释放（评审 2026-10-10 P2-12）：与 rebuild_pool 口径对称，
    # 否则关停时副本池连接只能靠进程退出兜底。
    if _read_engine is not None:
        try:
            await _read_engine.dispose()
        except (OperationalError, DisconnectionError) as e:
            logger.warning("只读副本引擎释放异常（可能已关闭）: %s", e)
    _read_engine = None
    _ReadSessionLocal = None


async def rebuild_pool() -> bool:
    """重建全部数据库连接池（备份恢复后调用，REV-25）

    使用 asyncio.Lock 防止并发重建。依次释放异步主库引擎、
    只读副本引擎，然后重新初始化。

    Returns:
        True  -- 重建成功

    Raises:
        RuntimeError -- 重新初始化失败时抛出
    """
    global _async_engine, _AsyncSessionLocal, async_engine
    global _read_engine, _ReadSessionLocal

    async with _rebuild_lock:
        # ---- 释放现有引擎 ----
        if _async_engine is not None:
            try:
                await _async_engine.dispose()
            except (OperationalError, DisconnectionError) as e:
                logger.warning("异步主库引擎释放异常: %s", e)

        if _read_engine is not None:
            try:
                await _read_engine.dispose()
            except (OperationalError, DisconnectionError) as e:
                logger.warning("只读副本引擎释放异常: %s", e)

        # ---- 清空全局引用 ----
        _async_engine = None
        _AsyncSessionLocal = None
        async_engine = None
        _read_engine = None
        _ReadSessionLocal = None
        _engine_loop = None

        # ---- 重新初始化 ----
        try:
            _init_async_engine()
            _init_read_engine()
            _engine_loop = asyncio.get_running_loop()

            from fastapi_app.core.slow_query import setup_slow_query_listener
            assert _async_engine is not None  # noqa: S101
            setup_slow_query_listener(_async_engine.sync_engine)
            _register_slow_listener_for_read_engine()
            logger.info("慢查询监听器已重新注册")
        except SQLAlchemyError as e:
            logger.error("数据库连接池重建失败: %s", e)
            raise RuntimeError(f"数据库连接池重建失败: {e}") from e

    logger.info("数据库连接池重建成功")
    return True


async def verify_db_connectivity() -> bool:
    """验证数据库连接可用性，返回 True/False"""
    from sqlalchemy import text
    await ensure_engine_for_current_loop()
    try:
        assert _async_engine is not None  # noqa: S101
        async with _async_engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
        return True
    except (OperationalError, DisconnectionError):
        return False


import warnings


def __getattr__(name):
    if name == "sync_engine":
        warnings.warn(
            "sync_engine 已废弃，请使用 get_sync_engine()。"
            "psycopg2 已移除，现在使用 psycopg3 同步驱动。",
            DeprecationWarning,
            stacklevel=2,
        )
        return get_sync_engine()

    if name == "SyncSessionLocal":
        warnings.warn(
            "SyncSessionLocal 已废弃，请使用 get_async_db()。",
            DeprecationWarning,
            stacklevel=2,
        )
        _init_sync_engine()
        return _SyncSessionLocal

    if name == "get_sync_db":
        warnings.warn(
            "get_sync_db 已废弃，请使用 get_async_db()。",
            DeprecationWarning,
            stacklevel=2,
        )
        from collections.abc import Generator

        from sqlalchemy.orm import Session

        def get_sync_db() -> Generator[Session]:
            _init_sync_engine()
            assert _SyncSessionLocal is not None  # noqa: S101
            db = _SyncSessionLocal()
            try:
                yield db
            finally:
                db.close()
        return get_sync_db

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
