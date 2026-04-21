
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi import Request, Response, Depends
from fastapi.responses import ORJSONResponse
from fastapi.concurrency import run_in_threadpool
from contextlib import asynccontextmanager
import time
import json
import os
import asyncio

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from fastapi_app.core.config import settings
from fastapi_app.core.logger import setup_logging, logger
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.api.v1.router import api_router
from fastapi_app.core.database import async_engine, sync_engine, dispose_async_engines
from fastapi_app.core.db_health import db_health_checker
from fastapi_app.core.metrics import (
    REQUEST_COUNT, REQUEST_LATENCY, REQUESTS_IN_PROGRESS,
    get_metrics, get_content_type, METRICS_AVAILABLE
)
from sqlalchemy import text


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI生命周期管理"""
    # 启动时执行
    setup_logging()
    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动中...")

    # 验证数据库连接并预热连接池
    if async_engine is not None:
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
            logger.info("异步数据库连接验证成功")
        except Exception as e:
            logger.error(f"异步数据库连接验证失败: {e}")
    else:
        logger.warning("异步数据库引擎未初始化（asyncmy 未安装），跳过异步连接验证")

    # 预热同步数据库连接池（避免首次请求延迟）
    try:
        from fastapi_app.core.database import sync_engine
        from fastapi.concurrency import run_in_threadpool

        def _warmup_sync_db():
            with sync_engine.connect() as conn:
                conn.execute(text("SELECT 1"))

        await run_in_threadpool(_warmup_sync_db)
        logger.info("同步数据库连接池预热成功")
    except Exception as e:
        logger.warning(f"同步数据库连接池预热失败: {e}")

    # 启动数据库连接健康检查后台任务
    await db_health_checker.start()

    # 预热同步 Redis 客户端（避免首次请求延迟）
    from fastapi_app.services.notification_service import _warmup_sync_redis
    await run_in_threadpool(_warmup_sync_redis)

    # 初始化 Redis 缓存管理器
    from utils.redis_cache import redis_cache
    try:
        redis_host = os.getenv('REDIS_HOST', 'localhost')
        redis_port = int(os.getenv('REDIS_PORT', 6379))
        redis_db = int(os.getenv('REDIS_DB', 0))
        redis_password = os.getenv('REDIS_PASSWORD')
        redis_cache.init_app(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            redis_password=redis_password
        )
        logger.info(f"Redis缓存管理器初始化完成，后端: {redis_cache.get_stats().get('backend', 'unknown')}")
    except Exception as e:
        logger.warning(f"Redis缓存初始化失败，将使用内存缓存: {e}")

    # 清除导航缓存（确保 Flask→FastAPI URL 映射生效）
    try:
        from fastapi_app.core.nav_context import invalidate_nav_cache
        await run_in_threadpool(invalidate_nav_cache)
    except Exception as e:
        logger.warning(f"导航缓存清除失败: {e}")

    # 启动 Redis Pub/Sub → WebSocket 桥梁
    from fastapi_app.services.notification_service import manager
    await manager.start_redis_listener()

    yield

    # 关闭时执行
    logger.info(f"{settings.APP_NAME} 正在关闭...")
    await manager.stop_redis_listener()
    await db_health_checker.stop()
    await dispose_async_engines()
    sync_engine.dispose()
    # 释放同步 Redis 客户端连接
    from fastapi_app.services.notification_service import _get_sync_redis_client
    _notif_redis = _get_sync_redis_client()
    if _notif_redis:
        try:
            _notif_redis.close()
        except Exception:
            pass
    # 释放缓存管理器 Redis 连接
    from utils.redis_cache import redis_cache
    if redis_cache.redis_client:
        try:
            redis_cache.redis_client.close()
        except Exception:
            pass
    logger.info("数据库连接池已关闭")


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    description="滨发协同系统 - API服务",
    version=settings.APP_VERSION,
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
    openapi_url=settings.OPENAPI_URL,
    default_response_class=ORJSONResponse,
    lifespan=lifespan
)

# 速率限制配置
# 传入 config_filename=os.devnull 阻止 slowapi 通过 starlette.config 读取 .env，
# 避免 Windows GBK 编码下 UnicodeDecodeError（python-dotenv 已在 config.py 中正确加载 .env）
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

# 统一异常处理 - 确保所有错误返回一致的JSON格式
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import RedirectResponse

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """统一HTTP异常响应格式（3xx 重定向直接透传，不转为 JSON）"""
    if 300 <= exc.status_code < 400 and exc.headers and "location" in {k.lower(): v for k, v in exc.headers.items()}:
        location = {k.lower(): v for k, v in exc.headers.items()}["location"]
        return RedirectResponse(url=location, status_code=exc.status_code)
    return Response(
        content=json.dumps({
            "success": False,
            "detail": exc.detail,
            "status_code": exc.status_code,
        }, ensure_ascii=False),
        status_code=exc.status_code,
        media_type="application/json",
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """统一请求验证错误响应格式"""
    return Response(
        content=json.dumps({
            "success": False,
            "detail": "请求参数验证失败",
            "errors": str(exc.errors()),
            "status_code": 422,
        }, ensure_ascii=False),
        status_code=422,
        media_type="application/json",
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """统一未处理异常响应格式 - 避免泄露内部错误详情"""
    logger.error(f"未处理异常: {type(exc).__name__}", exc_info=True)
    return Response(
        content=json.dumps({
            "success": False,
            "detail": "服务器内部错误，请稍后重试",
            "status_code": 500,
        }, ensure_ascii=False),
        status_code=500,
        media_type="application/json",
    )

# CSRF Cookie 中间件（Double Submit Cookie 模式）
# 替代 Flask-WTF CSRF，为浏览器端提供 CSRF 保护
# 单层 CSRF：仅使用 starlette-csrf，不叠加自定义 Origin/Referer 校验
try:
    from starlette_csrf import CSRFMiddleware
    _csrf_secure = os.getenv("CSRF_COOKIE_SECURE", "").lower() in ("true", "1", "yes")
    app.add_middleware(
        CSRFMiddleware,
        secret=settings.SECRET_KEY,
        cookie_name="fastapi_csrf_token",
        header_name="X-CSRFToken",
        cookie_path="/",
        cookie_secure=_csrf_secure,
        cookie_httponly=False,  # JS 需读取 cookie 值设置 header
        cookie_samesite="lax",
        safe_methods=("GET", "HEAD", "OPTIONS"),
    )
except ImportError:
    logger.warning("starlette-csrf 未安装，CSRF cookie 保护未启用")

# CORS中间件 - 限制允许的源和方法
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRFToken"],
)

# TrustedHost 中间件 - 拒绝 Host 头不在 ALLOWED_HOSTS 中的请求
# 防止 Host Header Injection 攻击（如密码重置投毒、缓存投毒、CSRF 绕过）
from starlette.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)

# GZip压缩中间件
app.add_middleware(GZipMiddleware, minimum_size=1000)


# 请求体大小限制中间件 (10MB)
MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024  # 10MB

@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    """限制请求体大小，防止超大请求导致内存溢出"""
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
    # HIGH-015: API版本信息响应头
    response.headers["X-API-Version"] = "v1"
    return response


# ==================== Prometheus 请求追踪中间件 ====================

@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    """记录每个请求的指标到 Prometheus"""
    if not METRICS_AVAILABLE:
        return await call_next(request)

    # 跳过不需要追踪的轻量级端点，避免无意义的标签基数
    skip_paths = {"/api/health", "/api/health/db", "/metrics", "/", "/nginx-health"}
    if request.url.path in skip_paths:
        return await call_next(request)

    method = request.method
    # 简化 endpoint 路径，避免高基数标签（如 /api/v1/orders/123 → /api/v1/orders/{id}）
    path = request.url.path
    # 将数字路径段替换为 {id}，避免指标爆炸
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

    return response

# 注册API路由
app.include_router(api_router, prefix=settings.API_PREFIX)

# 注册页面路由（不使用 API 前缀，直接挂载到根路径）
from fastapi_app.api.v1.endpoints.pages import router as pages_router
app.include_router(pages_router, tags=["页面"])

# 静态文件挂载（开发模式 / Nginx 未代理时使用）
from fastapi.staticfiles import StaticFiles
import pathlib
_static_dir = pathlib.Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ==================== WebSocket 实时通知 ====================

from fastapi import WebSocket, WebSocketDisconnect


@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket, token: str = ""):
    """
    WebSocket 实时通知端点。

    认证方式（按优先级）：
    1. Cookie-based JWT（浏览器端，httpOnly cookie，零延迟）
    2. JWT Token：首条消息发送 {"type":"auth","token":"xxx"}（移动端，推荐）
    3. JWT Token：query parameter ?token=xxx（向后兼容，不推荐）
    """
    await websocket.accept()
    user_id = None
    pending_message = None  # 首条非auth消息，需传递给主循环

    # 1. 优先 Cookie JWT 认证（浏览器端，零延迟）
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

    # 2. 从首条消息认证（移动端）
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
                    pending_message = initial_data  # 非auth消息，传递给主循环
            except Exception as e:
                logger.warning("WebSocket首条消息认证失败: %s", e)
                pending_message = initial_data  # JSON解析失败，仍可能是有效消息
        except asyncio.TimeoutError:
            logger.warning("WebSocket等待认证消息超时")

    # 3. 向后兼容：query parameter 认证（不推荐）
    if not user_id and token:
        try:
            from fastapi_app.core.deps import _decode_jwt_token
            payload = _decode_jwt_token(token)
            user_id = payload.get("sub")
            if user_id:
                user_id = int(user_id)
        except (ValueError, KeyError, HTTPException) as e:
            logger.warning("WebSocket JWT(query)认证失败: %s", e)

    if not user_id:
        await websocket.close(code=4001, reason="未认证")
        return

    # 验证用户仍存在且处于启用状态（在线程池中执行，避免阻塞事件循环）
    from fastapi_app.core.database import SyncSessionLocal
    from fastapi_app.shared_models import User as _WSUser
    from sqlalchemy import select as _ws_select

    def _check_ws_user():
        _ws_db = SyncSessionLocal()
        try:
            _ws_user = _ws_db.execute(
                _ws_select(_WSUser.id, _WSUser.status).where(_WSUser.id == user_id)
            ).first()
            return _ws_user
        finally:
            _ws_db.close()

    _ws_user = await run_in_threadpool(_check_ws_user)

    from fastapi_app.services.notification_service import manager
    manager.connect_existing(websocket, int(user_id))

    try:
        # 处理认证阶段被暂存的首条消息
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


async def _get_optional_user(request: Request) -> int | None:
    """可选认证：已认证返回user_id，未认证返回None（不拒绝请求）"""
    try:
        return await get_current_user_id(request)
    except Exception:
        return None


# 健康检查结果缓存：避免每次请求都执行 DB SELECT 1 + Redis ping，
# 缓存 TTL 内直接返回上次结果，大幅降低 health 端点延迟。
_health_cache = {"public_data": None, "internal_data": None, "cached_at": 0.0, "ttl": 10}


def _get_cached_health() -> dict | None:
    """返回缓存的健康数据（public 版本），过期则返回 None"""
    if _health_cache["public_data"] is not None and (time.time() - _health_cache["cached_at"]) < _health_cache["ttl"]:
        return _health_cache["public_data"]
    return None


def _set_cached_health(public_data: dict, internal_data: dict):
    """写入健康数据缓存，分别存储公开版和内部版"""
    _health_cache["public_data"] = public_data
    _health_cache["internal_data"] = internal_data
    _health_cache["cached_at"] = time.time()


@app.get("/api/health", tags=["健康检查"])
async def health_check(user_id: int | None = Depends(_get_optional_user)):
    """健康检查接口 - 包含数据库和Redis连通性检测（未认证时隐藏敏感详情）

    优化：健康检查结果缓存 10 秒，避免每次请求都执行 DB + Redis 探测。
    仅在缓存过期时才实际执行连通性检测。
    """
    # 尝试使用缓存
    cached_public = _get_cached_health()
    if cached_public is not None:
        # 未认证用户：直接返回预计算的公开版本（零拷贝）
        if user_id is None:
            if cached_public.get("status") == "unhealthy":
                return Response(
                    content=json.dumps(cached_public, ensure_ascii=False),
                    status_code=503,
                    media_type="application/json",
                )
            return cached_public

        # 已认证用户：基于公开版本补充实时详情
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

    # 缓存未命中：执行实际检查
    health_data = {
        "status": "healthy",
        "app": settings.APP_NAME,
    }
    overall_healthy = True

    # 数据库连通性检查（所有用户都执行，但仅已认证用户返回详情）
    try:
        if async_engine is not None:
            async with async_engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
        else:
            from fastapi_app.core.database import sync_engine
            from fastapi.concurrency import run_in_threadpool

            def _sync_db_check():
                with sync_engine.connect() as conn:
                    conn.execute(text("SELECT 1"))

            await run_in_threadpool(_sync_db_check)
    except Exception:
        overall_healthy = False

    # Redis连通性检查（复用共享连接池，仅一次ping）
    redis_ok = True
    try:
        from fastapi_app.services.notification_service import _get_sync_redis_client
        from fastapi.concurrency import run_in_threadpool

        def _sync_redis_check():
            client = _get_sync_redis_client()
            if client:
                try:
                    client.ping()
                except Exception:
                    return False
                return True
            return False

        await run_in_threadpool(_sync_redis_check)
    except Exception:
        redis_ok = False

    # 写入缓存：分别存储公开版（不含内部详情）和内部版（含 checks 详情）
    internal_checks = {
        "database": {"status": "ok"} if overall_healthy else {"status": "error"},
        "redis": {"status": "ok"} if redis_ok else {"status": "warning"},
    }
    if not overall_healthy:
        health_data["status"] = "unhealthy"
    _set_cached_health(public_data=dict(health_data), internal_data=internal_checks)

    # 仅对已认证用户暴露版本和详细检查结果
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
async def db_health_detail(user_id: int = Depends(get_current_user_id)):
    """数据库连接详细状态 - 连接池、健康检查统计、MySQL服务器变量（需认证）"""
    result = {
        "pool_status": db_health_checker.get_pool_status(),
        "health_stats": db_health_checker.get_stats(),
    }

    # 查询MySQL服务器端关键变量
    try:
        from fastapi_app.core.database import sync_engine
        from fastapi.concurrency import run_in_threadpool

        def _query_mysql_vars():
            with sync_engine.connect() as conn:
                rows = conn.execute(text(
                    "SHOW VARIABLES WHERE Variable_name IN "
                    "('wait_timeout','interactive_timeout','connect_timeout',"
                    "'max_connections','thread_cache_size','thread_handling',"
                    "'max_connect_errors','aborted_connects')"
                ))
                mysql_vars = {row[0]: row[1] for row in rows}

                # 当前连接数
                rows2 = conn.execute(text("SHOW STATUS LIKE 'Threads_connected'"))
                mysql_status = {}
                for row in rows2:
                    mysql_status[row[0]] = row[1]

                return mysql_vars, mysql_status

        mysql_vars, mysql_status = await run_in_threadpool(_query_mysql_vars)
        result["mysql_variables"] = mysql_vars
        result["mysql_status"] = mysql_status
    except Exception as e:
        result["mysql_error"] = str(e)[:200]

    return result


@app.get("/metrics", tags=["监控"])
async def metrics():
    """Prometheus 指标端点"""
    return Response(content=get_metrics(), media_type=get_content_type())


@app.get("/", tags=["根路径"])
async def root():
    """根路径重定向到文档"""
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
