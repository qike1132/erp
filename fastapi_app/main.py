"""
FastAPI 应用主入口 - 全异步模式

中间件 → core/middleware.py
健康检查 → core/health.py
WebSocket → api/ws.py
"""

# 1. 标准库
import asyncio
import os
import pathlib
from contextlib import asynccontextmanager, suppress

# 2. 第三方库
import msgspec
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

# 3. 项目内部
from fastapi_app.api.v1.router import api_router
from fastapi_app.api.v2.router import router as api_v2_router
from fastapi_app.api.ws import register_websocket
from fastapi_app.core.config import settings
from fastapi_app.core.database import async_engine, dispose_async_engines
from fastapi_app.core.limiter import limiter
from fastapi_app.core.db_health import db_health_checker
from fastapi_app.core.exceptions import AppError, current_iso_timestamp, new_request_id
from fastapi_app.core.health import register_health_routes
from fastapi_app.core.deps import _resolve_user_id
from fastapi_app.core.logger import logger, setup_logging
from fastapi_app.core.middleware import setup_middleware


class MsgspecResponse(JSONResponse):
    """使用 msgspec 高性能 JSON 编码器替代 orjson"""

    def render(self, content: object) -> bytes:
        return msgspec.json.encode(content)


_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=_sentry_dsn,
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.1")),
            profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_RATE", "0.1")),
            environment=os.getenv("APP_ENV", "development"),
            release=f"binfa-erp@{settings.APP_VERSION}",
            enable_tracing=True,
        )
    except (ValueError, ImportError):
        pass


async def _setup_database():
    """数据库连接验证与连接池预热"""
    if async_engine is None:
        return
    from fastapi_app.core.database import verify_db_connectivity
    if not await verify_db_connectivity():
        logger.error("异步数据库连接验证失败")
        raise RuntimeError("异步数据库引擎无法连接数据库")
    pool = async_engine.pool
    warmup_count = min(5, pool.size())
    from sqlalchemy import text as warmup_text
    for _ in range(warmup_count):
        async with async_engine.connect() as warmup_conn:
            await warmup_conn.execute(warmup_text('SELECT 1'))
    logger.info("异步数据库连接验证成功，连接池预热完成 (%d 个连接)", warmup_count)


async def _setup_redis_caches():
    """Redis 预热与缓存初始化"""
    from fastapi_app.services.notification_service import _warmup_async_redis
    try:
        await _warmup_async_redis()
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning("异步 Redis 客户端预热失败: %s", e)

    from utils.redis_cache import redis_cache
    try:
        redis_url = (
            getattr(settings, 'REDIS_CACHE_URL', None)
            or os.getenv('REDIS_CACHE_URL')
            or os.getenv('REDIS_URL')
        )
        if redis_url:
            await redis_cache.init_app(redis_url=redis_url)
        else:
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            redis_db = int(os.getenv('REDIS_DB', 0))
            redis_password = os.getenv('REDIS_PASSWORD')
            await redis_cache.init_app(
                redis_host=redis_host,
                redis_port=redis_port,
                redis_db=redis_db,
                redis_password=redis_password,
            )
        stats = await redis_cache.get_stats()
        logger.info("Redis缓存管理器初始化完成: %s", stats.get('backend', 'unknown'))
    except (OSError, ValueError) as e:
        logger.warning("Redis缓存初始化失败: %s", e)

    from fastapi_app.core.nav_context import invalidate_nav_cache
    try:
        await invalidate_nav_cache()
    except (OSError, ValueError) as e:
        logger.warning("导航缓存清除失败: %s", e)


async def _warm_inventory_cache():
    """启动时预热库存缓存，确保首次请求命中缓存"""
    await asyncio.sleep(2)  # 等待数据库连接池就绪
    try:
        from fastapi_app.core.database import get_async_db
        from fastapi_app.services.stock_service import get_inventory_paginated
        async for db in get_async_db():
            await get_inventory_paginated(db, page=1, per_page=20)
            logger.info("库存缓存预热完成")
            break
    except Exception as e:  # defensive: startup cache warmup failure must not block application boot
        logger.warning("库存缓存预热失败: %s", e)


@asynccontextmanager
async def lifespan(application: FastAPI):
    setup_logging()
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动中...")

    await _setup_database()
    await db_health_checker.start()

    from fastapi_app.core.telemetry import setup_telemetry
    setup_telemetry(application)

    await _setup_redis_caches()

    from fastapi_app.services.notification_service import manager
    await manager.start_redis_listener()

    from fastapi_app.core.purchase_cache import start_purchase_cache_listener
    await start_purchase_cache_listener()

    # L1 缓存跨 worker 失效广播（开关默认关，由 CACHE_L1_BROADCAST_ENABLED 启用）
    from fastapi_app.core.cache import start_l1_broadcast_listener
    await start_l1_broadcast_listener()

    # 预热库存缓存（后台执行，不阻塞启动）
    background_tasks = []
    task = asyncio.create_task(_warm_inventory_cache())
    background_tasks.append(task)

    from fastapi_app.core.audit_middleware import _audit_flush_loop
    task = asyncio.create_task(_audit_flush_loop())
    background_tasks.append(task)

    from utils.redis_cache import warmup_cache
    task = asyncio.create_task(warmup_cache())
    background_tasks.append(task)

    yield

    # 优雅关闭：提取为独立协程，配合超时保护
    async def _perform_shutdown():
        # 先刷写审计日志缓冲区，防止关闭时丢失数据
        try:
            from fastapi_app.core.audit_middleware import flush_audit_buffer
            await flush_audit_buffer()
        except Exception as e:  # defensive: shutdown audit flush failure must not block graceful shutdown
            logger.warning("审计缓冲区刷写失败: %s", e)

        # 再取消后台任务
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)

        logger.info(f"{settings.APP_NAME} 正在关闭...")
        await manager.stop_redis_listener()
        from fastapi_app.core.purchase_cache import stop_purchase_cache_listener
        await stop_purchase_cache_listener()
        from fastapi_app.core.cache import stop_l1_broadcast_listener
        await stop_l1_broadcast_listener()
        await db_health_checker.stop()
        from fastapi_app.core.telemetry import shutdown_telemetry
        shutdown_telemetry()
        await dispose_async_engines()

        from fastapi_app.services.notification_service import _get_async_redis_client
        _notif_redis = await _get_async_redis_client()
        if _notif_redis:
            with suppress(OSError, RuntimeError):
                await _notif_redis.aclose()

        from utils.redis_cache import redis_cache
        with suppress(OSError, RuntimeError):
            await redis_cache.close()
        logger.info("数据库连接池已关闭")

    # 关闭超时保护：防止某步骤 hang 导致整个关闭阻塞
    try:
        await asyncio.wait_for(_perform_shutdown(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.error("优雅关闭超时（15s），强制退出")


app = FastAPI(
    title=settings.APP_NAME,
    description="滨发协同系统 - API服务",
    version=settings.APP_VERSION,
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
    openapi_url=settings.OPENAPI_URL,
    default_response_class=MsgspecResponse,
    lifespan=lifespan,
)

def _rate_limit_key(request: Request) -> str:
    """限流键：已登录用户按 user_id，未登录按 IP。

    从 JWT Bearer 或 Cookie JWT 中提取 sub（用户ID），纯内存操作无 DB 查询。
    无法解析时降级到客户端 IP，保证登录/公共端点仍有基本防护。
    """
    user_id = _resolve_user_id(request)
    if user_id is not None:
        return f"user:{user_id}"
    return get_remote_address(request)


# limiter 单例由 fastapi_app.core.limiter 提供（避免循环导入）。
# 此处覆盖 key_func：已登录用户按 user_id 限流，避免内网多用户共享出口 IP 导致误限流。
# 装饰器在请求时才调用 key_func，故覆盖后所有端点立即生效。
limiter.key_func = _rate_limit_key
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    return MsgspecResponse(
        content={
            "success": False,
            "detail": "请求过于频繁，请稍后再试",
            "status_code": 429,
            "code": "RATE_LIMIT_EXCEEDED",
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=429,
        headers={"Retry-After": "60"},
    )


app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    logger.warning(
        "业务异常: code=%s status=%d request_id=%s path=%s msg=%s",
        exc.code, exc.status_code, request_id, request.url.path, exc.message,
    )
    return MsgspecResponse(
        content={
            "success": False,
            "detail": exc.message,
            "code": exc.code,
            "status_code": exc.status_code,
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=exc.status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if 300 <= exc.status_code < 400 and exc.headers and "location" in {k.lower(): v for k, v in exc.headers.items()}:
        location = {k.lower(): v for k, v in exc.headers.items()}["location"]
        return RedirectResponse(url=location, status_code=exc.status_code)
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    logger.warning(
        "HTTP异常: status=%d request_id=%s path=%s detail=%s",
        exc.status_code, request_id, request.url.path, exc.detail,
    )
    return MsgspecResponse(
        content={
            "success": False,
            "detail": exc.detail,
            "status_code": exc.status_code,
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if os.getenv("APP_ENV") == "production":
        detail = "请求参数验证失败"
    else:
        detail = f"请求参数验证失败: {exc.errors()}"
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    return MsgspecResponse(
        content={
            "success": False,
            "detail": detail,
            "status_code": 422,
            "code": "VALIDATION_ERROR",
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=422,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, 'request_id', None) or new_request_id()
    logger.error(
        "未处理异常: request_id=%s type=%s path=%s",
        request_id, type(exc).__name__, request.url.path, exc_info=exc,
    )
    return MsgspecResponse(
        content={
            "success": False,
            "detail": "服务器内部错误，请稍后重试",
            "status_code": 500,
            "code": "INTERNAL_ERROR",
            "request_id": request_id,
            "timestamp": current_iso_timestamp(),
        },
        status_code=500,
    )


setup_middleware(app)

from fastapi_app.core.audit_middleware import AuditLogMiddleware
app.add_middleware(AuditLogMiddleware)

register_health_routes(app)
register_websocket(app)

app.include_router(api_router, prefix=settings.API_PREFIX)
app.include_router(api_v2_router, prefix="/api")

_static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"

# 确保 static 子目录存在并挂载，避免因目录未预创建导致静态文件 404
# static/ 不存在时创建并挂载 uploads/releases/files
if not _static_dir.is_dir():
    _static_dir.mkdir(parents=True, exist_ok=True)

_uploads_dir = _static_dir / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(_uploads_dir)), name="static-uploads")

_files_dir = _static_dir / "files"
_files_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/files", StaticFiles(directory=str(_files_dir)), name="static-files")

_releases_dir = _static_dir / "releases"
_releases_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/releases", StaticFiles(directory=str(_releases_dir)), name="static-releases")


@app.get("/", tags=["根路径"])
async def root():
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": settings.DOCS_URL,
    }


if __name__ == "__main__":
    uvicorn.run(
        "fastapi_app.main:app",
        host="0.0.0.0",
        port=5002,
        reload=settings.FASTAPI_DEBUG,
    )
