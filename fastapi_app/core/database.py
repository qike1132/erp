"""
数据库会话管理 - 全异步模式

异步引擎：asyncpg（FastAPI 运行时）
同步引擎：psycopg3（Alembic 迁移专用）

仅支持 PostgreSQL。
"""

import os
import logging

logger = logging.getLogger(__name__)

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.config import settings


def _get_pool_config() -> dict:
    return {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "30")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "20")),
        "pool_pre_ping": True,
        "pool_use_lifo": True,  # LIFO 策略，减少空闲连接
    }


_pool_config = _get_pool_config()

_async_engine = None
_AsyncSessionLocal = None
async_engine = None


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
    setup_slow_query_listener(_async_engine.sync_engine)
except ImportError as e:
    logger.warning('慢查询监听器初始化失败: %s', e)


_sync_engine = None
_SyncSessionLocal = None


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


async def get_async_db():
    """异步数据库会话依赖（Unit of Work 模式）

    - 请求成功时自动 commit
    - 请求异常时自动 rollback
    - 服务层应使用 flush() 而非 commit()，由本依赖统一控制事务边界
    """
    async with _AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
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


async def get_async_read_db():
    """只读数据库会话依赖（用于报表/列表查询，走只读副本）

    - 未配置副本时自动回退到主库
    - 无 commit/rollback（只读操作无需事务控制）
    """
    _init_read_engine()

    if _ReadSessionLocal is not None:
        async with _ReadSessionLocal() as session:
            try:
                yield session
            finally:
                await session.close()
    else:
        # 回退到主库
        async for session in get_async_db():
            yield session


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
        from typing import Generator
        from sqlalchemy.orm import Session

        def get_sync_db() -> Generator[Session, None, None]:
            _init_sync_engine()
            db = _SyncSessionLocal()
            try:
                yield db
            finally:
                db.close()
        return get_sync_db

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
