"""
数据库会话管理

FastAPI 与 Flask 共享同一数据库，使用独立的 SQLAlchemy 引擎和会话。
同步引擎始终可用；异步引擎在 aiomysql 已安装时启用。
连接池参数从环境变量/Settings读取，与Flask侧保持一致。
"""

import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from fastapi_app.core.config import settings


def _get_pool_config() -> dict:
    """从环境变量读取连接池配置，提供合理默认值"""
    return {
        "pool_size": int(os.getenv("DB_POOL_SIZE", "10")),
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE", "3600")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT", "30")),
        "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "5")),
        "pool_pre_ping": True,  # 自动检测断开的连接
    }


# ========== 同步引擎（始终可用） ==========
_pool_config = _get_pool_config()
sync_engine = create_engine(
    settings.DATABASE_URL,
    **_pool_config,
    echo=False,
)

SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def get_sync_db() -> Generator[Session, None, None]:
    """获取同步数据库会话（用于导出等同步查询场景）"""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ========== 异步引擎（统一单例，模块加载时即初始化） ==========
_async_engine = None
_AsyncSessionLocal = None
# 模块级变量，供 main.py 的 lifespan / health_check 引用
# 与 _async_engine 始终指向同一实例，避免双连接池泄漏
async_engine = None


def _init_async_engine():
    """初始化异步引擎（仅在 aiomysql 可用时）

    同时设置模块级 async_engine，确保 lifespan / health_check
    和 get_async_db() 共用同一个引擎实例。
    """
    global _async_engine, _AsyncSessionLocal, async_engine
    if _async_engine is not None:
        return
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

        _async_db_url = settings.ASYNC_DATABASE_URL
        _async_engine = create_async_engine(
            _async_db_url,
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
        # 统一：lifespan / health_check 和 get_async_db() 共用同一引擎
        async_engine = _async_engine
        assert async_engine is _async_engine, (
            "async_engine 与 _async_engine 必须为同一实例，否则会泄漏连接池"
        )
    except ImportError:
        pass


# 模块加载时立即初始化，确保 lifespan startup 可验证数据库连接
_init_async_engine()


async def get_async_db():
    """FastAPI 依赖：获取异步数据库会话"""
    _init_async_engine()
    if _AsyncSessionLocal is None:
        raise RuntimeError("异步数据库引擎未初始化（aiomysql 未安装），请使用 get_sync_db")
    async with _AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def dispose_async_engines():
    """释放所有异步引擎的连接池，供 lifespan shutdown 调用

    解决原先只释放 async_engine 而遗漏 _async_engine 导致
    aiomysql 连接在 Event loop 关闭后才触发 __del__ 报
    RuntimeError: Event loop is closed 的问题。
    """
    global _async_engine, _AsyncSessionLocal, async_engine
    engines = []
    if _async_engine is not None:
        engines.append(_async_engine)
    # 防御：如果 async_engine 与 _async_engine 不是同一个实例
    if async_engine is not None and async_engine is not _async_engine:
        engines.append(async_engine)
    for eng in engines:
        try:
            await eng.dispose()
        except Exception:
            pass
    _async_engine = None
    _AsyncSessionLocal = None
    async_engine = None
