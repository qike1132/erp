"""
中间件注册模块

从 main.py 提取，包含：
- 请求 ID
- CSRF 保护
- CORS 配置
- TrustedHost
- GZip 压缩
- 请求体大小限制（10MB）
- Prometheus 请求追踪
- 安全响应头

中间件执行顺序（请求进入时，由外到内；Starlette 中后注册的位于外层）：
1. 安全响应头
2. Prometheus 请求指标采集
3. 请求体大小限制（10MB）
4. GZip 响应压缩（>1000 bytes）
5. TrustedHost 主机头校验
6. CORS 跨域处理
7. CSRF token 校验（非 GET/HEAD 请求，豁免登录/登出）
8. 请求 ID 注入

注：2026-10-17 审计 P2-25 修正——此前 docstring 写的是注册顺序且漏列
request_id/security_headers，与实际执行顺序几乎相反。
"""

import logging
import os
import re
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

# ---------------------------------------------------------------------------
# 安全降级登记（P0-10）
# 生产环境的安全能力缺失必须可观测、不静默：登记降级原因，由 /api/health 以
# degraded / security_degraded 字段暴露（保持既有状态码语义，不把整体误判为 503）。
# 注：原 CSRF/itsdangerous 触发点经逐字节核查不可达（try 内只 import ipaddress /
# secrets，均为标准库），常量与 except 分支已于 2026-10-01 按裁决删除，见 _setup_csrf。
# ---------------------------------------------------------------------------
_DEGRADED_REASONS: list[str] = []


def record_degradation(reason: str) -> None:
    """登记一条安全降级原因（幂等，进程级）。"""
    if reason not in _DEGRADED_REASONS:
        _DEGRADED_REASONS.append(reason)


def degraded_reasons() -> list[str]:
    """当前生效的安全降级原因（空列表 = 无降级）。"""
    return list(_DEGRADED_REASONS)


def clear_degradations() -> None:
    """清空降级登记（仅供测试重置进程级状态）。"""
    _DEGRADED_REASONS.clear()

# H-2（2026-09-29）：路径级请求体上限。全局 10MB 会把业务侧**已经声明支持**的更大
# 上传一并挡死（备份 500MB、Excel 导入 50MB），上线后首次整库还原/大导入即 413。
# 放宽只为让请求抵达端点，体积的真正校验仍由端点内的常量负责：
#   * 备份  -> services/backup/_constants.py::MAX_BACKUP_FILE_SIZE
#   * 导入  -> api/v1/endpoints/tasks.py::MAX_IMPORT_FILE_SIZE
# core 层不能 import services/backup（会与 backup 域形成循环依赖），故此处用常量 +
# 环境变量覆盖；tests/test_request_body_limit_paths.py 的 parity 用例锁住
# 「中间件上限 >= 业务声明上限」，防止两处漂移。
# ⚠️ 边缘 nginx 也要同步放行，见部署文件 config/nginx-windows.conf（**不是** config/nginx.conf）。
_BACKUP_UPLOAD_BODY_LIMIT = int(os.environ.get('MAX_BACKUP_UPLOAD_BYTES', str(512 * 1024 * 1024)))
_IMPORT_UPLOAD_BODY_LIMIT = int(os.environ.get('MAX_IMPORT_UPLOAD_BYTES', str(64 * 1024 * 1024)))

_PATH_BODY_LIMITS: tuple[tuple[str, int], ...] = (
    ('/api/v1/backup/', _BACKUP_UPLOAD_BODY_LIMIT),
    ('/api/v1/tasks/import-', _IMPORT_UPLOAD_BODY_LIMIT),
)


def max_body_size_for_path(path: str) -> int:
    """返回该请求路径允许的最大请求体字节数。

    只有业务侧已声明上限的路径放宽，其余路径维持全局 10MB。
    """
    for prefix, limit in _PATH_BODY_LIMITS:
        if path.startswith(prefix):
            return limit
    return MAX_REQUEST_BODY_SIZE


def _body_too_large_response(limit: int) -> Response:
    mb = limit // 1024 // 1024
    return Response(
        content=f'{{"detail":"请求体过大，最大允许{mb}MB"}}',
        status_code=413,
        media_type="application/json",
    )

# Prometheus endpoint 归一化：纯数字 ID / UUID / 长 hex token 统一折叠为 {id}，
# 防止订单号等非数字动态路径段造成指标 label 基数爆炸
_PATH_ID_SEGMENT_RE = re.compile(
    r'^(?:\d+'
    r'|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
    r'|[0-9a-fA-F]{16,})$'
)


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
    # P0-10(a)（2026-10-01 裁决）：此处原有 except ImportError 降级分支经逐字节核查不可达
    # （try 内只 import ipaddress / secrets，均为标准库；CSRF token 由
    # secrets.token_urlsafe 生成，本模块从未 import itsdangerous），已删除 try/except 包裹。
    # 安全降级登记机制（record_degradation / degraded_reasons）本身保留，
    # /api/health 仍暴露 degraded / security_degraded 标记。
    import ipaddress
    import secrets

    def _csrf_secure() -> bool:
        # 运行时判定，而非 import 时固化：测试进程会先设 APP_ENV=test 再 import
        # main.py，若此处固化则 monkeypatch APP_ENV=production 后 HTTPS 分支仍
        # 读不到「生产默认 true」，导致 CSRF cookie 的 Secure 属性回归测试假失败。
        # 语义：显式 CSRF_COOKIE_SECURE 优先，否则生产默认 true、非生产 false。
        return os.getenv(
            "CSRF_COOKIE_SECURE",
            "true" if settings.is_production else "",
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
        is_production = settings.is_production
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
        _is_production = settings.is_production

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
            else:
                # 2026-10-17 审计 F-BE-CORE-07：同时带 Bearer 头与 Cookie 的请求
                # 原先两支都不进（无 else）→ CSRF 与 Origin 双双不校验，而 deps 的
                # 认证链在 Bearer 解码失败时会静默回落 Cookie —— 攻击者以
                # credentials:'include' + 伪 Bearer 头即可借受害者 Cookie 认证。
                # 只按「存在会话 cookie」（access_token/refresh_token，即 deps.py
                # 回落读取的那两个键）收口；不能按「任意 cookie」判定——本中间件
                # 每次响应都下发 fastapi_csrf_token，按任意 cookie 判会让带 cookie
                # jar 的 Bearer 客户端（e2e 写路径用例、contract_snapshot、外部
                # 集成）从第二个写请求起被一律 403。
                if request.cookies.get("access_token") or request.cookies.get("refresh_token"):
                    csrf_cookie = request.cookies.get("fastapi_csrf_token")
                    csrf_header = request.headers.get("X-CSRF-Token")
                    if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "CSRF token 验证失败"},
                        )

        response = await call_next(request)

        # 仅在请求未携带有效 CSRF cookie 时才生成新 token。此前每次响应（含 GET）
        # 都轮换 cookie，浏览器多标签/并发请求下旧 cookie 会被新值覆盖，导致
        # 基于 cookie 的 CSRF 校验偶发 403。复用已有 cookie 可避免该竞态。
        csrf_token = request.cookies.get("fastapi_csrf_token")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
        # ⚠️ `Secure` 必须随「实际请求 scheme」判定，不能只看全局 is_production：
        # 浏览器只对**可信来源**（https / localhost / 127.0.0.1）接受 Secure cookie，
        # 局域网明文 HTTP（如 http://192.168.0.95:3000）会**直接丢弃**该 cookie
        # ⇒ 前端 document.cookie 读不到 token ⇒ double-submit 永远失败
        # ⇒ 该 origin 下所有 POST/PUT/DELETE 一律 403「CSRF token 验证失败」。
        # 同一套判定见 api/v1/endpoints/auth.py::_set_login_cookies（登录 cookie 早已按
        # scheme 自适应，所以现象是「能登录、但写不了」）。
        # 注：CSRF_COOKIE_SECURE 的语义是「https 下是否打 Secure」——置 false 可在 HTTPS
        # 上主动关闭；但**不具备**「在明文 HTTP 上强制开启」的能力（第 193 行对 _is_https
        # 硬门控）。这是刻意的：Secure cookie 在非可信来源会被浏览器直接丢弃，
        # 强制开启只会复现本次「读不到 token ⇒ 写请求全 403」的故障。
        _is_https = (
            request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
        )
        _csrf_samesite = "lax"
        _has_bearer_resp = request.headers.get("authorization", "").startswith("Bearer ")
        _csrf_sec = _csrf_secure() if (_is_https and not _has_bearer_resp) else False
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


def _setup_security_headers(app: FastAPI) -> None:
    """安全响应头中间件

    CSP 策略说明：
    - 生产环境移除 'unsafe-eval'（仅 Vite HMR 需要）
    - 生产环境 style-src 使用 per-request nonce 替代 'unsafe-inline'（防 XSS 注入）
    - 开发环境保留 'unsafe-inline'（Vue 内联样式 + HMR 需要）
    - frame-ancestors 'none' 防止点击劫持
    """
    is_production = settings.is_production

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
    is_dev = not settings.is_production
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
    """启用 GZip 压缩（默认始终开启，由显式环境变量关闸）。

    此前按 `settings.is_production` 推断「生产环境由 Nginx 统一压缩」，把「谁能
    压缩」这个**运行时事实**硬编码成了环境名推断。实测（2026-09-17）nginx 缺席时
    全站零压缩：/metrics 从 gzip 后约 2.5KB 膨胀到 18.7KB，传输浪费约 86%。
    所谓「双重压缩」担忧不成立——nginx 对**已带 Content-Encoding 的**上游响应
    不会二次压缩；反之漏压缩是 3-8 倍传输浪费的实打实损失。
    确需关闸时用显式环境变量 APP_GZIP_DISABLED=true，而非靠环境名推断。
    """
    if os.getenv("APP_GZIP_DISABLED", "").strip().lower() in ("true", "1", "yes"):
        logger.info("GZip 压缩已被 APP_GZIP_DISABLED 显式关闭")
        return
    app.add_middleware(GZipMiddleware, minimum_size=1000)


def _setup_body_size_limit(app: FastAPI) -> None:
    @app.middleware("http")
    async def limit_request_body_size(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            limit = max_body_size_for_path(request.url.path)
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > limit:
                        return _body_too_large_response(limit)
                except ValueError:
                    return Response(
                        content='{"detail":"无效的Content-Length"}',
                        status_code=400,
                        media_type="application/json",
                    )
            else:
                # 无 Content-Length（chunked/流式上传）：累积计数器边读边判，一旦超限立刻
                # 413 并停止累积；否则 512MB 分块上传会把内存放大到同一量级（P0-12）。
                received = 0
                chunks: list[bytes] = []
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > limit:
                        return _body_too_large_response(limit)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
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
            if _PATH_ID_SEGMENT_RE.match(part):
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
