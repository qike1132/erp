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
import uuid

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

    _setup_request_id(app)
    _setup_csrf(app)
    _setup_cors(app)
    _setup_trusted_host(app)
    _setup_gzip(app)
    _setup_body_size_limit(app)
    _setup_prometheus(app)
    _setup_security_headers(app)


def _setup_request_id(app: FastAPI) -> None:
    """X-Request-ID 中间件 - 链路追踪支持

    - 从请求头 X-Request-ID 读取，无则生成 UUID 前8位
    - 保存到 request.state.request_id 供业务/审计使用
    - 注入响应头 X-Request-ID 返回给客户端
    """

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        incoming_rid = request.headers.get("X-Request-ID")
        request_id = incoming_rid or str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    logger.info("X-Request-ID 链路追踪中间件已启用")


def _setup_csrf(app: FastAPI) -> None:
    try:
        import ipaddress
        import secrets

        _csrf_secure = os.getenv(
            "CSRF_COOKIE_SECURE",
            "true" if os.getenv("APP_ENV", "dev").lower() in ("prod", "production") else "",
        ).lower() in ("true", "1", "yes")

        # 内网 IP 段：CSRF 攻击几乎不可能来自内网，直接豁免
        _LAN_NETWORKS = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
        )

        def _is_lan_ip(ip_str: str) -> bool:
            """判断 IP 是否属于内网段"""
            try:
                ip = ipaddress.ip_address(ip_str)
                return any(ip in net for net in _LAN_NETWORKS)
            except ValueError:
                return False

        def _is_allowed_origin(origin: str | None) -> bool:
            """验证请求Origin是否为允许的源（内网环境放行所有内网 origin）"""
            if not origin:
                return False
            is_production = os.getenv("APP_ENV") == "production"
            if is_production:
                allowed = settings.BACKEND_CORS_ORIGINS
                return any(origin.rstrip('/') == allowed_origin.rstrip('/') for allowed_origin in allowed)
            else:
                dev_origins = {
                    "http://localhost",
                    "http://localhost:3000",
                    "http://localhost:5173",
                    "http://localhost:4173",
                    "http://localhost:8080",
                    "http://127.0.0.1:3000",
                    "http://127.0.0.1:5173",
                    "http://127.0.0.1:8080",
                }
                extra = os.getenv('DEV_CORS_ORIGINS', '')
                if extra:
                    dev_origins.update(o.strip() for o in extra.split(',') if o.strip())
                return origin.rstrip('/') in {o.rstrip('/') for o in dev_origins}

        @app.middleware("http")
        async def conditional_csrf_middleware(request: Request, call_next):
            # CSRF 内网豁免：仅开发环境保留（纯内网直连调试场景）
            # 生产环境必须经过 Nginx/Ingress 反代，request.client.host 为真实客户端 IP，
            # 内网豁免会使所有反代请求绕过 CSRF，导致全局失效。生产环境一律执行 CSRF 校验。
            _is_production = os.getenv("APP_ENV") == "production"
            if not _is_production:
                client_ip = request.client.host if request.client else None
                if client_ip and _is_lan_ip(client_ip):
                    response = await call_next(request)
                    return response

            is_login_endpoint = request.url.path == "/api/v1/auth/login"
            is_logout_endpoint = request.url.path == "/api/v1/auth/logout"
            # web vitals 上报使用 sendBeacon，无法携带自定义 header，豁免 CSRF
            is_vitals_endpoint = request.url.path == "/api/v1/monitoring/vitals"
            is_exempt_endpoint = is_login_endpoint or is_logout_endpoint or is_vitals_endpoint

            if not is_exempt_endpoint and request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
                auth_header = request.headers.get("authorization", "")
                _has_bearer = auth_header.startswith("Bearer ")
                _has_cookie = bool(request.cookies)

                if _has_bearer and not _has_cookie:
                    origin = request.headers.get("origin") or request.headers.get("referer")
                    if not _is_allowed_origin(origin):
                        logger.warning("CSRF保护：Bearer Token请求Origin验证失败: %s", origin)
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "跨站请求被拒绝"},
                        )
                elif not _has_bearer:
                    csrf_cookie = request.cookies.get("fastapi_csrf_token")
                    csrf_header = request.headers.get("X-CSRF-Token")
                    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
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

        logger.info("CSRF 配置：API 变更请求需验证 CSRF token，Bearer Token 请求验证 Origin")
    except ImportError:
        logger.warning("itsdangerous 未安装，CSRF cookie 保护未启用")


def _setup_security_headers(app: FastAPI) -> None:
    """安全响应头中间件

    CSP 策略说明：
    - 生产环境移除 'unsafe-eval'（仅 Vite HMR 需要）
    - 生产环境 style-src 使用 per-request nonce 替代 'unsafe-inline'（防 XSS 注入）
    - 开发环境保留 'unsafe-inline'（Vue 内联样式 + HMR 需要）
    - frame-ancestors 'none' 防止点击劫持
    """
    is_production = os.getenv("APP_ENV") == "production"

    # 生产环境 WSS 域名白名单：从 WS_ALLOWED_ORIGINS 读取（逗号分隔）
    # 未配置时回退到 'wss:'（保持向后兼容，但日志告警）
    _ws_origins_raw = os.getenv("WS_ALLOWED_ORIGINS", "")
    if is_production and _ws_origins_raw:
        _ws_sources = " ".join(
            f"wss://{o.strip()}" for o in _ws_origins_raw.split(",") if o.strip()
        )
        _connect_src = f"'self' {_ws_sources}" if _ws_sources else "'self'"
    elif is_production:
        logger.warning("生产环境未配置 WS_ALLOWED_ORIGINS，CSP connect-src 回退到 wss:（建议收紧）")
        _connect_src = "'self' wss:"
    else:
        _connect_src = "'self' ws: wss:"

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        # 为每个请求生成唯一 CSP nonce
        import secrets as _secrets
        _csp_nonce = _secrets.token_urlsafe(16)
        request.state.csp_nonce = _csp_nonce

        response = await call_next(request)

        # 动态构建 CSP（包含 per-request nonce）
        if is_production:
            csp = (
                "default-src 'self'; "
                "script-src 'self'; "
                f"style-src 'self' 'nonce-{_csp_nonce}'; "
                "img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                f"connect-src {_connect_src}; "
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
                f"connect-src {_connect_src}; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )

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
            "http://localhost:5173",
            "http://localhost:4173",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
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
            allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept", "Origin", "X-CSRF-Token"],
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
        except Exception:  # defensive: record metrics for unexpected errors before re-raising
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
