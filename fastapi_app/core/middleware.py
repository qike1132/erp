"""
中间件注册模块

从 main.py 提取，包含：
- CSRF 保护
- CORS 配置
- TrustedHost
- GZip 压缩
- 请求体大小限制（10MB）
- Prometheus 请求追踪

中间件执行顺序（自上而下）：
1. CSRF token 校验（非 GET/HEAD 请求，豁免登录/登出）
2. CORS 跨域处理
3. TrustedHost 主机头校验
4. GZip 响应压缩（>1000 bytes）
5. 请求体大小限制（10MB）
6. Prometheus 请求指标采集
"""

import logging
import os
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fastapi_app.core.config import settings

logger = logging.getLogger(__name__)

MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024


def setup_middleware(app: FastAPI) -> None:
    """注册所有中间件到 FastAPI 应用"""

    _setup_csrf(app)
    _setup_cors(app)
    _setup_trusted_host(app)
    _setup_gzip(app)
    _setup_body_size_limit(app)
    _setup_prometheus(app)
    _setup_security_headers(app)


def _setup_csrf(app: FastAPI) -> None:
    try:
        import secrets

        _csrf_secure = os.getenv("CSRF_COOKIE_SECURE", "").lower() in ("true", "1", "yes")

        @app.middleware("http")
        async def conditional_csrf_middleware(request: Request, call_next):
            is_login_endpoint = request.url.path == "/api/v1/auth/login"
            is_logout_endpoint = request.url.path == "/api/v1/auth/logout"
            is_exempt_endpoint = is_login_endpoint or is_logout_endpoint

            if not is_exempt_endpoint and request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
                _has_bearer = request.headers.get("authorization", "").startswith("Bearer ")
                if _has_bearer:
                    pass
                else:
                    csrf_cookie = request.cookies.get("fastapi_csrf_token")
                    csrf_header = request.headers.get("X-CSRF-Token")
                    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "CSRF token 验证失败"},
                        )

            response = await call_next(request)

            csrf_token = secrets.token_urlsafe(32)
            _csrf_samesite = "lax"
            _has_bearer_resp = request.headers.get("authorization", "").startswith("Bearer ")
            _csrf_sec = False if _has_bearer_resp else _csrf_secure
            response.set_cookie(
                key="fastapi_csrf_token",
                value=csrf_token,
                max_age=86400,
                httponly=False,
                samesite=_csrf_samesite,
                secure=_csrf_sec,
                path="/",
            )
            if _has_bearer_resp:
                response.headers["X-CSRF-Token"] = csrf_token

            return response

        logger.info("CSRF 配置：API 变更请求需验证 CSRF token")
    except ImportError:
        logger.warning("itsdangerous 未安装，CSRF cookie 保护未启用")


def _setup_security_headers(app: FastAPI) -> None:
    """安全响应头中间件

    CSP 策略说明：
    - 生产环境移除 'unsafe-eval'（仅 Vite HMR 需要）
    - 'unsafe-inline' 保留用于 Vue 内联样式，后续迁移到 nonce 方案
    - frame-ancestors 'none' 防止点击劫持
    """
    is_production = os.getenv("APP_ENV") == "production"

    if is_production:
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self' wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    else:
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response

    mode_label = "生产（无 unsafe-eval/ws:）" if is_production else "开发（含 unsafe-eval/ws:）"
    logger.info("安全头部已配置（CSP 模式: %s）", mode_label)


def _setup_cors(app: FastAPI) -> None:
    is_dev = os.getenv("APP_ENV") != "production"
    if is_dev:
        _dev_origins = [
            "http://localhost",
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3002",
            "http://localhost:3003",
            "http://localhost:3004",
            "http://localhost:3005",
            "http://localhost:5002",
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:8000",
            "http://localhost:8080",
            "http://localhost:8090",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://127.0.0.1:3005",
            "http://127.0.0.1:5002",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
            "http://127.0.0.1:8080",
        ]
        # 额外开发环境 origin 可通过环境变量 DEV_CORS_ORIGINS 添加（逗号分隔）
        extra_origins = os.getenv('DEV_CORS_ORIGINS', '')
        if extra_origins:
            _dev_origins.extend(o.strip() for o in extra_origins.split(',') if o.strip())
        app.add_middleware(
            CORSMiddleware,
            allow_origins=_dev_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["X-CSRF-Token"],
        )
    else:
        # 生产环境 CORS 源通过 CORS_ORIGINS 环境变量配置
        # Capacitor 移动端如需 null 源，需显式添加: CORS_ORIGINS=https://erp.example.com,null
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
            expose_headers=["X-CSRF-Token"],
        )


def _setup_trusted_host(app: FastAPI) -> None:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS,
    )


def _setup_gzip(app: FastAPI) -> None:
    # 生产环境由 Nginx 统一处理 GZip 压缩，避免双重压缩
    if os.getenv("APP_ENV") == "production":
        logger.info("GZip 压缩由 Nginx 处理（生产环境）")
        return
    app.add_middleware(GZipMiddleware, minimum_size=1000)


def _setup_body_size_limit(app: FastAPI) -> None:
    @app.middleware("http")
    async def limit_request_body_size(request: Request, call_next):
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
            else:
                body = b""
                async for chunk in request.stream():
                    body += chunk
                    if len(body) > MAX_REQUEST_BODY_SIZE:
                        return Response(
                            content='{"detail":"请求体过大，最大允许10MB"}',
                            status_code=413,
                            media_type="application/json",
                        )
                request._body = body
        response = await call_next(request)
        response.headers["X-API-Version"] = "v1"
        return response


def _setup_prometheus(app: FastAPI) -> None:
    try:
        from fastapi_app.core.metrics import (
            METRICS_AVAILABLE,
            REQUEST_COUNT,
            REQUEST_LATENCY,
            REQUESTS_IN_PROGRESS,
        )
    except ImportError:
        return

    if not METRICS_AVAILABLE:
        return

    @app.middleware("http")
    async def prometheus_middleware(request: Request, call_next):
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
