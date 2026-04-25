"""
FastAPI 应用主入口 - 全异步模式

已迁移到全异步数据库操作，移除同步引擎依赖。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi import Request, Response, Depends
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import time
import json
import os
import asyncio

import msgspec


class MsgspecResponse(JSONResponse):
    """使用 msgspec 高性能 JSON 编码器替代 orjson"""

    def render(self, content: object) -> bytes:
        return msgspec.json.encode(content)

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from fastapi_app.core.config import settings
from fastapi_app.core.logger import setup_logging, logger

# Sentry 错误追踪（仅在 SENTRY_DSN 设置时启用）
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
    except Exception:
        pass  # sentry-sdk 未安装或 DSN 无效时静默跳过

from fastapi_app.core.deps import get_current_user_id
from fastapi_app.api.v1.router import api_router
from fastapi_app.core.database import async_engine, dispose_async_engines
from fastapi_app.core.db_health import db_health_checker
from fastapi_app.core.metrics import (
    REQUEST_COUNT, REQUEST_LATENCY, REQUESTS_IN_PROGRESS,
    get_metrics, get_content_type, METRICS_AVAILABLE
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi_app.core.database import get_async_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI生命周期管理 - 全异步模式"""
    # 启动时执行
    setup_logging()
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动中...")

    # 验证数据库连接并预热连接池（异步）
    if async_engine is not None:
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
            # 预热连接池：创建 5 个初始连接
            pool = async_engine.pool
            warmup_count = min(5, pool.size())
            for _ in range(warmup_count):
                async with async_engine.connect() as conn:
                    await conn.execute(text('SELECT 1'))
            logger.info("异步数据库连接验证成功，连接池预热完成 (%d 个连接)", warmup_count)
        except Exception as e:
            logger.error(f"异步数据库连接验证失败: {e}")
    else:
        logger.error("异步数据库引擎未初始化，无法启动")
        raise RuntimeError("异步数据库引擎未初始化")

    # 启动数据库连接健康检查后台任务
    await db_health_checker.start()

    # 初始化 OpenTelemetry（可选，需 OTEL_ENABLED=true）
    from fastapi_app.core.telemetry import setup_telemetry
    setup_telemetry(app)

    # 预热异步 Redis 客户端
    from fastapi_app.services.notification_service import _warmup_async_redis
    await _warmup_async_redis()

    # 初始化 Redis 缓存管理器（异步）
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
            redis_password=redis_password
        )
        stats = await redis_cache.get_stats()
        logger.info("Redis缓存管理器初始化完成，后端: %s", stats.get('backend', 'unknown'))
    except Exception as e:
        logger.warning("Redis缓存初始化失败，将使用内存缓存: %s", e)

    # 清除导航缓存
    try:
        from fastapi_app.core.nav_context import invalidate_nav_cache
        await invalidate_nav_cache()
    except Exception as e:
        logger.warning("导航缓存清除失败: %s", e)

    # 启动 Redis Pub/Sub → WebSocket 桥梁
    from fastapi_app.services.notification_service import manager
    await manager.start_redis_listener()

    yield

    # 关闭时执行
    logger.info(f"{settings.APP_NAME} 正在关闭...")
    await manager.stop_redis_listener()
    await db_health_checker.stop()
    from fastapi_app.core.telemetry import shutdown_telemetry
    shutdown_telemetry()
    await dispose_async_engines()
    # 释放异步 Redis 客户端连接
    from fastapi_app.services.notification_service import _get_async_redis_client
    _notif_redis = await _get_async_redis_client()
    if _notif_redis:
        try:
            await _notif_redis.aclose()
        except Exception:
            pass
    # 释放缓存管理器 Redis 连接
    from utils.redis_cache import redis_cache
    await redis_cache.close()
    logger.info("数据库连接池已关闭")


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    description="滨发协同系统 - API服务",
    version=settings.APP_VERSION,
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
    openapi_url=settings.OPENAPI_URL,
    default_response_class=MsgspecResponse,
    lifespan=lifespan
)

# 速率限制配置
import warnings
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

# 统一异常处理
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import RedirectResponse

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """统一HTTP异常响应格式（msgspec 编码）"""
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
    """统一请求验证错误响应格式（msgspec 编码）"""
    return MsgspecResponse(
        content={
            "success": False,
            "detail": "请求参数验证失败",
            "errors": str(exc.errors()),
            "status_code": 422,
        },
        status_code=422,
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """统一未处理异常响应格式（msgspec 编码）"""
    logger.error("未处理异常: %s", type(exc).__name__, exc_info=True)
    return MsgspecResponse(
        content={
            "success": False,
            "detail": "服务器内部错误，请稍后重试",
            "status_code": 500,
        },
        status_code=500,
    )

# CSRF 保护
try:
    from starlette_csrf import CSRFMiddleware
    _csrf_secure = os.getenv("CSRF_COOKIE_SECURE", "").lower() in ("true", "1", "yes")
    
    @app.middleware("http")
    async def conditional_csrf_middleware(request: Request, call_next):
        """条件性 CSRF 检查：API 端点跳过 CSRF 检查"""
        if request.url.path.startswith("/api/"):
            return await call_next(request)
        
        response = await call_next(request)
        
        from itsdangerous import URLSafeSerializer
        csrf_token = URLSafeSerializer(settings.SECRET_KEY).dumps("csrf_token")
        response.set_cookie(
            key="fastapi_csrf_token",
            value=csrf_token,
            max_age=86400,
            httponly=False,
            samesite="lax",
            secure=_csrf_secure,
            path="/",
        )
        return response
    
    logger.info("CSRF 配置：API 端点已跳过 CSRF 检查")
except ImportError:
    logger.warning("starlette-csrf 未安装，CSRF cookie 保护未启用")

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRFToken"],
)

# TrustedHost 中间件
from starlette.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)

# GZip压缩中间件
app.add_middleware(GZipMiddleware, minimum_size=1000)


# 请求体大小限制中间件
MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024  # 10MB

@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    """限制请求体大小"""
    if request.method in ("POST", "PUT", "PATCH"):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BODY_SIZE:
                    return Response(
                        content='{"detail":"请求体过大，最大允许10MB"}',
                        status_code=413,
                        media_type="application/json",
                    )
            except ValueError:
                return Response(
                    content='{"detail":"无效的Content-Length"}',
                    status_code=400,
                    media_type="application/json",
                )
    response = await call_next(request)
    response.headers["X-API-Version"] = "v1"
    return response


# Prometheus 请求追踪中间件
@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """记录每个请求的指标到 Prometheus"""
    if not METRICS_AVAILABLE:
        return await call_next(request)

    skip_paths = {"/api/health", "/api/health/db", "/metrics", "/", "/nginx-health"}
    if request.url.path in skip_paths:
        return await call_next(request)

    method = request.method
    path = request.url.path
    parts = path.rstrip("/").split("/")
    normalized_parts = []
    for part in parts:
        if part.isdigit():
            normalized_parts.append("{id}")
        else:
            normalized_parts.append(part)
    endpoint = "/".join(normalized_parts)

    REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()
    start_time = time.time()

    try:
        response = await call_next(request)
        status = response.status_code
    except Exception:
        status = 500
        raise
    finally:
        elapsed = time.time() - start_time
        REQUEST_COUNT.labels(method=method, endpoint=endpoint, status=status).inc()
        REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(elapsed)
        REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).dec()
        if elapsed > 3.0:
            logger.warning(
                "慢请求: %s %s → %s (%.2fs)",
                method, endpoint, status, elapsed,
            )

    return response

# 注册API路由
app.include_router(api_router, prefix=settings.API_PREFIX)

# 注册页面路由
from fastapi_app.api.v1.endpoints.pages import router as pages_router
app.include_router(pages_router)

# 静态文件挂载（仅提供 files/ 和 uploads/ 子目录，不再暴露已删除的旧前端资源）
from fastapi.staticfiles import StaticFiles
import pathlib
_static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    _files_dir = _static_dir / "files"
    if _files_dir.is_dir():
        app.mount("/static/files", StaticFiles(directory=str(_files_dir)), name="static-files")
    _uploads_dir = _static_dir / "uploads"
    if _uploads_dir.is_dir():
        app.mount("/static/uploads", StaticFiles(directory=str(_uploads_dir)), name="static-uploads")


# WebSocket 实时通知
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    """WebSocket 实时通知端点 - 全异步模式

    支持两种认证方式：
    1. Cookie JWT（浏览器自动携带）
    2. 首条消息认证（移动端/API客户端发送 {"type":"auth","token":"xxx"}）
    """
    await websocket.accept()
    user_id = None
    pending_message = None

    # 1. Cookie JWT 认证
    cookie_token = websocket.cookies.get("access_token")
    if cookie_token:
        try:
            from fastapi_app.core.deps import _decode_jwt_token
            payload = _decode_jwt_token(cookie_token)
            user_id = payload.get("sub")
            if user_id:
                user_id = int(user_id)
        except Exception as e:
            logger.warning("WebSocket Cookie认证失败: %s", e)

    # 2. 首条消息认证
    if not user_id:
        try:
            import json as _json
            initial_data = await asyncio.wait_for(websocket.receive_text(), timeout=5)
            try:
                msg = _json.loads(initial_data)
                if msg.get("type") == "auth" and msg.get("token"):
                    from fastapi_app.core.deps import _decode_jwt_token
                    payload = _decode_jwt_token(msg["token"])
                    user_id = payload.get("sub")
                    if user_id:
                        user_id = int(user_id)
                else:
                    pending_message = initial_data
            except Exception as e:
                logger.warning("WebSocket首条消息认证失败: %s", e)
                pending_message = initial_data
        except asyncio.TimeoutError:
            logger.warning("WebSocket等待认证消息超时")

    if not user_id:
        await websocket.close(code=4001, reason="未认证")
        return

    # 验证用户状态（异步）
    from fastapi_app.shared_models import User as _WSUser
    from sqlalchemy import select as _ws_select
    
    async with async_engine.connect() as conn:
        result = await conn.execute(
            _ws_select(_WSUser.id, _WSUser.status).where(_WSUser.id == user_id)
        )
        _ws_user = result.first()
    
    if not _ws_user or not _ws_user[1]:
        await websocket.close(code=4001, reason="用户不存在或已禁用")
        return

    from fastapi_app.services.notification_service import manager
    manager.connect_existing(websocket, int(user_id))

    try:
        if pending_message:
            if pending_message == "ping":
                await websocket.send_text("pong")

        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, int(user_id))
    except Exception:
        logger.warning("WebSocket 连接异常断开: user_id=%s", user_id, exc_info=False)
        manager.disconnect(websocket, int(user_id))


async def _get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_async_db)
) -> int | None:
    """可选认证：已认证返回user_id，未认证返回None"""
    try:
        return await get_current_user_id(request, db)
    except Exception:
        return None


# 健康检查缓存
_health_cache = {"public_data": None, "internal_data": None, "cached_at": 0.0, "ttl": 10}


def _get_cached_health() -> dict | None:
    if _health_cache["public_data"] is not None and (time.time() - _health_cache["cached_at"]) < _health_cache["ttl"]:
        return _health_cache["public_data"]
    return None


def _set_cached_health(public_data: dict, internal_data: dict):
    _health_cache["public_data"] = public_data
    _health_cache["internal_data"] = internal_data
    _health_cache["cached_at"] = time.time()


@app.get("/api/health", tags=["健康检查"])
async def health_check(user_id: int | None = Depends(_get_optional_user)):
    """健康检查接口 - 全异步模式"""
    cached_public = _get_cached_health()
    if cached_public is not None:
        if user_id is None:
            if cached_public.get("status") == "unhealthy":
                return Response(
                    content=json.dumps(cached_public, ensure_ascii=False),
                    status_code=503,
                    media_type="application/json",
                )
            return cached_public

        health_data = dict(cached_public)
        health_data["version"] = settings.APP_VERSION
        health_data["checks"] = dict(_health_cache["internal_data"])
        try:
            pool_status = db_health_checker.get_pool_status()
            health_stats = db_health_checker.get_stats()
            health_data["checks"]["db_pool"] = pool_status
            health_data["checks"]["db_health_stats"] = health_stats
        except Exception as e:
            health_data["checks"]["db_pool"] = {"error": str(e)[:100]}

        if cached_public.get("status") == "unhealthy":
            return Response(
                content=json.dumps(health_data, ensure_ascii=False),
                status_code=503,
                media_type="application/json",
            )
        return health_data

    health_data = {
        "status": "healthy",
        "app": settings.APP_NAME,
    }
    overall_healthy = True

    # 数据库连通性检查（异步）
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
    except Exception:
        overall_healthy = False

    # Redis连通性检查（异步）
    redis_ok = True
    try:
        from fastapi_app.services.notification_service import _get_async_redis_client
        client = await _get_async_redis_client()
        if client:
            try:
                await client.ping()
            except Exception:
                redis_ok = False
        else:
            redis_ok = False
    except Exception:
        redis_ok = False

    internal_checks = {
        "database": {"status": "ok"} if overall_healthy else {"status": "error"},
        "redis": {"status": "ok"} if redis_ok else {"status": "warning"},
    }
    if not overall_healthy:
        health_data["status"] = "unhealthy"
    _set_cached_health(public_data=dict(health_data), internal_data=internal_checks)

    if user_id is not None:
        health_data["version"] = settings.APP_VERSION
        health_data["checks"] = dict(internal_checks)
        try:
            pool_status = db_health_checker.get_pool_status()
            health_stats = db_health_checker.get_stats()
            health_data["checks"]["db_pool"] = pool_status
            health_data["checks"]["db_health_stats"] = health_stats
        except Exception as e:
            health_data["checks"]["db_pool"] = {"error": str(e)[:100]}

    if not overall_healthy:
        health_data["status"] = "unhealthy"
        return Response(
            content=json.dumps(health_data, ensure_ascii=False),
            status_code=503,
            media_type="application/json",
        )

    return health_data


@app.get("/api/health/db", tags=["健康检查"])
async def db_health_detail(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db)
):
    """数据库连接详细状态 - 全异步模式"""
    result = {
        "pool_status": db_health_checker.get_pool_status(),
        "health_stats": db_health_checker.get_stats(),
    }

    # 查询数据库服务器变量（异步）
    try:
        # PostgreSQL 配置查询
        rows = await db.execute(text(
            "SELECT name, setting FROM pg_settings WHERE name IN "
            "('listen_addresses','max_connections','shared_buffers',"
            "'effective_cache_size','work_mem','maintenance_work_mem',"
            "'checkpoint_completion_target','wal_buffers')"
        ))
        db_vars = {row[0]: row[1] for row in rows.all()}

        # 当前连接数
        rows2 = await db.execute(text(
            "SELECT state, COUNT(*) FROM pg_stat_activity GROUP BY state"
        ))
        db_status = {row[0]: str(row[1]) for row in rows2.all()}

        result["db_variables"] = db_vars
        result["db_status"] = db_status
    except Exception as e:
        result["db_error"] = str(e)[:200]

    return result


@app.get("/metrics", tags=["监控"])
async def metrics():
    """Prometheus 指标端点"""
    return Response(content=get_metrics(), media_type=get_content_type())


@app.get("/", tags=["根路径"])
async def root():
    """根路径"""
    return {
        "message": f"欢迎使用 {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": settings.DOCS_URL
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "fastapi_app.main:app",
        host="0.0.0.0",
        port=5002,
        reload=settings.FASTAPI_DEBUG
    )
