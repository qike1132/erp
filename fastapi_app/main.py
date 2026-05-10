"""
FastAPI 应用主入口 - 全异步模式

中间件 → core/middleware.py
健康检查 → core/health.py
WebSocket → api/ws.py
"""

# 1. 标准库
import os
import pathlib
import warnings
from contextlib import asynccontextmanager, suppress

# 2. 第三方库
import msgspec
import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

# 3. 项目内部
from fastapi_app.api.v1.router import api_router
from fastapi_app.api.ws import register_websocket
from fastapi_app.core.config import settings
from fastapi_app.core.database import async_engine, dispose_async_engines
from fastapi_app.core.db_health import db_health_checker
from fastapi_app.core.exceptions import AppError
from fastapi_app.core.health import register_health_routes
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

    yield

    logger.info(f"{settings.APP_NAME} 正在关闭...")
    await manager.stop_redis_listener()
    from fastapi_app.core.purchase_cache import stop_purchase_cache_listener
    await stop_purchase_cache_listener()
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

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Config file .* not found")
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["60/minute"],
        enabled=True,
        config_filename=os.devnull,
    )
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return MsgspecResponse(
        content={
            "success": False,
            "detail": exc.message,
            "code": exc.code,
            "status_code": exc.status_code,
        },
        status_code=exc.status_code,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if 300 <= exc.status_code < 400 and exc.headers and "location" in {k.lower(): v for k, v in exc.headers.items()}:
        location = {k.lower(): v for k, v in exc.headers.items()}["location"]
        return RedirectResponse(url=location, status_code=exc.status_code)
    return MsgspecResponse(
        content={
            "success": False,
            "detail": exc.detail,
            "status_code": exc.status_code,
        },
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 生产环境不暴露字段名和类型详情，仅返回通用提示
    if os.getenv("APP_ENV") == "production":
        detail = "请求参数验证失败"
    else:
        detail = f"请求参数验证失败: {exc.errors()}"
    return MsgspecResponse(
        content={
            "success": False,
            "detail": detail,
            "status_code": 422,
        },
        status_code=422,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("未处理异常: %s", type(exc).__name__, exc_info=True)
    return MsgspecResponse(
        content={
            "success": False,
            "detail": "服务器内部错误，请稍后重试",
            "status_code": 500,
        },
        status_code=500,
    )


setup_middleware(app)
register_health_routes(app)
register_websocket(app)

app.include_router(api_router, prefix=settings.API_PREFIX)

_static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    _files_dir = _static_dir / "files"
    if _files_dir.is_dir():
        app.mount("/static/files", StaticFiles(directory=str(_files_dir)), name="static-files")
    _uploads_dir = _static_dir / "uploads"
    if _uploads_dir.is_dir():
        app.mount("/static/uploads", StaticFiles(directory=str(_uploads_dir)), name="static-uploads")
    _releases_dir = _static_dir / "releases"
    if _releases_dir.is_dir():
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
