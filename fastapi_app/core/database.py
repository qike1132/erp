"""
数据库会话管理 - 全异步模式

异步引擎：asyncpg（FastAPI 运行时）
同步引擎：psycopg3（Alembic 迁移专用）

仅支持 PostgreSQL。
"""

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DisconnectionError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.config import settings


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

    return {
        "pool_size": pool_size,
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        "max_overflow": max_overflow,
        "pool_pre_ping": True,
        "pool_use_lifo": True,  # LIFO 策略，减少空闲连接
    }


_pool_config = _get_pool_config()

_async_engine: AsyncEngine | None = None
_AsyncSessionLocal: async_sessionmaker | None = None
async_engine: AsyncEngine | None = None
_rebuild_lock = asyncio.Lock()


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


async def get_async_db():
    """异步数据库会话依赖（Unit of Work 模式）

    - 请求成功时自动 commit
    - 请求异常时自动 rollback
    - 服务层应使用 flush() 而非 commit()，由本依赖统一控制事务边界

    注意：备份恢复操作（psql 路径）会 DROP+CREATE 数据库，导致当前 session
    的连接失效。此依赖对 commit/rollback 错误进行宽容处理，避免恢复成功后
    因 session 失效而返回 500 错误。
    """
    if _AsyncSessionLocal is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_async_engine()")
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except (RuntimeError, OSError, ValueError, SQLAlchemyError):
            try:
                await session.rollback()
            except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                logger.warning("Session rollback failed (may be broken after psql restore)", exc_info=True)
            raise


from contextlib import asynccontextmanager, suppress


@asynccontextmanager
async def get_async_db_context():
    """异步数据库会话上下文管理器（用于 ARQ 任务等非请求场景）

    注意：备份恢复操作（psql 路径）会 DROP+CREATE 数据库，导致当前 session
    的连接失效。此上下文管理器对 commit/rollback 错误进行宽容处理，避免恢复
    成功后因 session 失效而抛出异常。
    """
    if _AsyncSessionLocal is None:
        raise RuntimeError("数据库引擎未初始化，请先调用 init_async_engine()")
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except (RuntimeError, OSError, ValueError, SQLAlchemyError):
            try:
                await session.rollback()
            except (RuntimeError, OSError, ValueError, SQLAlchemyError):
                logger.warning("Session rollback failed (may be broken after psql restore)", exc_info=True)
            raise


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

    _read_engine = create_async_engine(
        replica_url,
        **_pool_config,
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


# 只读副本连接快速失败阈值（秒）：副本不可达/连接池耗尽/断连时，
# 超过该阈值即降级主库，避免请求因副本故障长时间阻塞（pool_timeout 默认 30s）
_READ_REPLICA_CHECKOUT_TIMEOUT = 2.0


async def get_async_read_db():
    """只读数据库会话依赖（用于报表/列表查询，走只读副本）

    - 未配置副本时自动回退到主库
    - 副本连接在阈值内未就绪（不可达/池耗尽/断连）时快速降级主库，
      防止副本故障把请求拖入数秒级等待
    - 无 commit/rollback（只读操作无需事务控制）
    """
    _init_read_engine()

    if _ReadSessionLocal is None:
        # 未配置副本：回退到主库
        async for session in get_async_db():
            yield session
        return

    session = _ReadSessionLocal()
    try:
        # 主动触发连接检出（含 pool_pre_ping）并施加快速失败超时
        async with asyncio.timeout(_READ_REPLICA_CHECKOUT_TIMEOUT):
            await session.execute(text("SELECT 1"))
    except (TimeoutError, SQLAlchemyError, OSError) as e:
        logger.warning("只读副本连接不可用（%.1fs），降级到主库: %s", _READ_REPLICA_CHECKOUT_TIMEOUT, e)
        # 资源清理尽力而为：关闭失败不影响降级路径
        with suppress(RuntimeError, OSError, ValueError, SQLAlchemyError):
            await session.close()
        async for primary_session in get_async_db():
            yield primary_session
        return
    try:
        yield session
    finally:
        await session.close()


async def dispose_async_engines():
    global _async_engine, _AsyncSessionLocal, async_engine
    if _async_engine is not None:
        try:
            await _async_engine.dispose()
        except (OperationalError, DisconnectionError) as e:
            logger.warning("异步引擎释放异常（可能已关闭）: %s", e)
    _async_engine = None
    _AsyncSessionLocal = None
    async_engine = None


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

        # ---- 重新初始化 ----
        try:
            _init_async_engine()
            _init_read_engine()

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

        def get_sync_db() -> Generator[Session, None, None]:
            _init_sync_engine()
            assert _SyncSessionLocal is not None  # noqa: S101
            db = _SyncSessionLocal()
            try:
                yield db
            finally:
                db.close()
        return get_sync_db

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
