
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi import Request, Response
from contextlib import asynccontextmanager
import time
import json
import os

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from fastapi_app.core.config import settings
from fastapi_app.core.logger import setup_logging, logger
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

    # 验证数据库连接
    if async_engine is not None:
        try:
            async with async_engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
            logger.info("异步数据库连接验证成功")
        except Exception as e:
            logger.error(f"异步数据库连接验证失败: {e}")
    else:
        logger.warning("异步数据库引擎未初始化（aiomysql 未安装），跳过异步连接验证")

    # 启动数据库连接健康检查后台任务
    await db_health_checker.start()

    yield

    # 关闭时执行
    logger.info(f"{settings.APP_NAME} 正在关闭...")
    await db_health_checker.stop()
    await dispose_async_engines()
    sync_engine.dispose()
    logger.info("数据库连接池已关闭")


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    description="滨发协同系统 - API服务",
    version=settings.APP_VERSION,
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL,
    openapi_url=settings.OPENAPI_URL,
    lifespan=lifespan
)

# 速率限制配置
# 注意: 设置 enabled=False 初始化后在 SlowAPIMiddleware 中启用，
# 避免 slowapi 自动读取 .env（Windows下GBK编码问题）
os.environ.pop("LIMITER_ENABLED", None)  # 清理可能残留的环境变量
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"], enabled=True)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# 统一异常处理 - 确保所有错误返回一致的JSON格式
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """统一HTTP异常响应格式"""
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
    logger.error(f"未处理异常: {type(exc).__name__}: {str(exc)}")
    return Response(
        content=json.dumps({
            "success": False,
            "detail": "服务器内部错误，请稍后重试",
            "status_code": 500,
        }, ensure_ascii=False),
        status_code=500,
        media_type="application/json",
    )

# CSRF保护中间件 - 验证POST/PUT/DELETE请求的Origin/Referer
@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """CSRF保护：验证修改请求的Origin头与目标一致"""
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        host = request.headers.get("host", "")

        # 允许API文档和健康检查路径跳过CSRF检查
        csrf_exempt_paths = ("/api/docs", "/api/redoc", "/api/openapi.json", "/api/health", "/metrics", "/")
        if request.url.path in csrf_exempt_paths or request.url.path.startswith("/api/docs"):
            return await call_next(request)

        # 如果有Origin头，验证它与host匹配
        if origin:
            from urllib.parse import urlparse
            parsed_origin = urlparse(origin)
            origin_host = parsed_origin.netloc
            if host and origin_host != host:
                return Response(
                    content='{"detail":"CSRF验证失败：Origin不匹配"}',
                    status_code=403,
                    media_type="application/json",
                )
        # 如果没有Origin但有Referer，验证它
        elif referer:
            from urllib.parse import urlparse
            parsed_referer = urlparse(referer)
            referer_host = parsed_referer.netloc
            if host and referer_host != host:
                return Response(
                    content='{"detail":"CSRF验证失败：Referer不匹配"}',
                    status_code=403,
                    media_type="application/json",
                )
        # 既无Origin也无Referer的状态变更请求应被拒绝（防止CSRF绕过）
        # 同源浏览器请求通常会携带Origin或Referer，缺少两者可能是CSRF攻击
        else:
            return Response(
                content='{"detail":"CSRF验证失败：缺少Origin/Referer头"}',
                status_code=403,
                media_type="application/json",
            )

    return await call_next(request)

# CORS中间件 - 限制允许的源和方法
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRFToken"],
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
        if content_length and int(content_length) > MAX_REQUEST_BODY_SIZE:
            return Response(
                content='{"detail":"请求体过大，最大允许10MB"}',
                status_code=413,
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


# ==================== WebSocket 实时通知 ====================

from fastapi import WebSocket, WebSocketDisconnect


@app.websocket("/ws/notifications")
async def websocket_notifications(websocket: WebSocket):
    """
    WebSocket 实时通知端点。

    连接时需携带认证信息（通过 query parameter 或 cookie）。
    降级方案：前端可继续使用轮询，WebSocket 是可选增强。
    """
    # 从 cookie 中提取用户身份（复用 session 认证机制）
    user_id = None
    session_cookie = websocket.cookies.get("session")
    if session_cookie:
        try:
            from flask.sessions import SecureCookieSessionInterface
            from flask import Flask as _Flask
            _app = _Flask(__name__)
            _app.config["SECRET_KEY"] = settings.SECRET_KEY
            si = SecureCookieSessionInterface()
            s = si.get_signing_serializer(_app)
            session_data = s.loads(session_cookie, max_age=3600)
            user_id = session_data.get("user_id")
        except Exception:
            pass

    if not user_id:
        await websocket.close(code=4001, reason="未认证")
        return

    from fastapi_app.services.notification_service import manager
    await manager.connect(websocket, int(user_id))

    try:
        while True:
            # 保持连接，接收客户端心跳
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, int(user_id))


@app.get("/api/health", tags=["健康检查"])
async def health_check():
    """健康检查接口 - 包含数据库和Redis连通性检测"""
    health_data = {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "app": settings.APP_NAME,
        "checks": {},
    }
    overall_healthy = True

    # 数据库连通性检查
    try:
        if async_engine is not None:
            async with async_engine.connect() as conn:
                await conn.execute(text('SELECT 1'))
            health_data["checks"]["database"] = {"status": "ok", "type": "async"}
        else:
            from fastapi_app.core.database import sync_engine
            from fastapi.concurrency import run_in_threadpool

            def _sync_db_check():
                with sync_engine.connect() as conn:
                    conn.execute(text('SELECT 1'))

            await run_in_threadpool(_sync_db_check)
            health_data["checks"]["database"] = {"status": "ok", "type": "sync"}
    except Exception as e:
        health_data["checks"]["database"] = {"status": "error", "detail": str(e)[:100]}
        overall_healthy = False

    # 数据库连接池与健康检查统计
    try:
        pool_status = db_health_checker.get_pool_status()
        health_stats = db_health_checker.get_stats()
        health_data["checks"]["db_pool"] = pool_status
        health_data["checks"]["db_health_stats"] = health_stats
    except Exception as e:
        health_data["checks"]["db_pool"] = {"error": str(e)[:100]}

    # Redis连通性检查
    try:
        from fastapi.concurrency import run_in_threadpool

        def _sync_redis_check():
            import redis as redis_lib
            r = redis_lib.from_url(
                settings.REDIS_URL,
                socket_connect_timeout=3,
            )
            r.ping()
            r.close()
            return True

        await run_in_threadpool(_sync_redis_check)
        health_data["checks"]["redis"] = {"status": "ok"}
    except Exception as e:
        health_data["checks"]["redis"] = {"status": "warning", "detail": str(e)[:100]}

    if not overall_healthy:
        health_data["status"] = "unhealthy"
        return Response(
            content=json.dumps(health_data, ensure_ascii=False),
            status_code=503,
            media_type="application/json",
        )

    return health_data


@app.get("/api/health/db", tags=["健康检查"])
async def db_health_detail():
    """数据库连接详细状态 - 连接池、健康检查统计、MySQL服务器变量"""
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
