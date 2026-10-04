"""
认证与文件上传接口

支持两种认证模式：
1. JWT Bearer Token（移动端/API客户端）
2. Cookie-based JWT（浏览器Web端）— 登录后设置 httpOnly cookie
"""
import logging
import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import create_access_token, create_refresh_token, get_current_user_id
from fastapi_app.core.limiter import limiter, memory_limiter, rate_limit_key
from fastapi_app.core.response import success_response
from fastapi_app.core.validators import require_upload_magic

logger = logging.getLogger(__name__)

router = APIRouter()

# 登录限流常量（内网折中：足以拦截脚本暴力破解，又不误伤同 IP 多个人工用户）
LOGIN_BURST_LIMIT = 30         # 1 分钟内最大尝试次数
LOGIN_BURST_WINDOW = 60        # 突发窗口（秒）
LOGIN_ATTEMPT_LIMIT = 100      # 5 分钟内最大尝试次数
LOGIN_ATTEMPT_WINDOW = 300     # 持续窗口（秒）


# ==================== Schemas ====================

class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    remember: bool = False

class UserInfoResponse(BaseModel):
    user_id: int
    username: str
    is_super: bool
    factory: str | None = None
    permissions: list[str]


class LoginResponse(BaseModel):
    success: bool
    message: str = ""
    error: str = ""
    access_token: str = ""
    token_type: str = ""
    user: UserInfoResponse | None = None


class FrontendErrorLogRequest(BaseModel):
    timestamp: str
    error: str
    stack: str = ""
    context: dict = {}
    url: str = ""
    userAgent: str = ""


class LoginCheckResponse(BaseModel):
    success: bool = True
    message: str = ""
    user_id: int = 0


class FrontendErrorLogResponse(BaseModel):
    success: bool = True
    message: str = ""


class FileUploadResponse(BaseModel):
    success: bool = True
    url: str = ""
    filename: str = ""
    file_id: int | None = None


# ==================== 登录状态检查 ====================

@router.get("/check", response_model=LoginCheckResponse)
async def check_login_status(
    user_id: int = Depends(get_current_user_id),
):
    """检查登录状态接口

    前端每5分钟调用一次此接口检查登录是否有效。
    返回200表示登录有效，401表示需要重新登录。
    """
    return success_response(**{
        "message": "登录状态有效",
        "user_id": user_id})


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """获取当前登录用户信息（含权限列表）

    前端在初始化时调用此接口获取用户详情和权限，
    用于前端路由守卫和导航菜单渲染。
    """
    from fastapi_app.services import user_service

    user = await user_service.get_user_with_permissions_by_id(db, user_id)
    if not user or not user.status:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    return UserInfoResponse(
        user_id=user.id,
        username=user.username,
        is_super=user.is_super,
        factory=user.factory,
        permissions=[p.code for p in user.permissions] if user.permissions else [],
    )


# ==================== 前端错误日志 ====================

@router.post("/logs/frontend-error", response_model=FrontendErrorLogResponse)
async def log_frontend_error(
    data: FrontendErrorLogRequest,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    """记录前端错误日志（需登录，防止日志洪泛攻击）

    前端在发生错误时调用此接口记录错误信息，
    便于后续分析和优化。
    """

    client_ip = request.client.host if request.client else "unknown"

    safe_url = data.url.replace('\n', '\\n').replace('\r', '\\r')
    safe_error = data.error.replace('\n', '\\n').replace('\r', '\\r')
    safe_ua = data.userAgent.replace('\n', '\\n').replace('\r', '\\r')
    safe_stack = data.stack.replace('\n', '\\n').replace('\r', '\\r') if data.stack else ""

    logger.warning(
        "[Frontend Error] IP=%s, URL=%s, Error=%s, Timestamp=%s, UserAgent=%s",
        client_ip, safe_url, safe_error, data.timestamp, safe_ua,
    )

    if safe_stack:
        logger.debug("[Frontend Error Stack] %s", safe_stack)

    return success_response(**{
        "message": "错误日志已记录"})


# ==================== 登录 ====================

async def _check_login_rate_limit(key: str) -> None:
    """分层限流：Redis burst + window 双计数器，不可用时降级到进程内存滑动窗口"""
    _login_rate_limit_key = f"login_attempt:{key}"
    _login_burst_key = f"login_burst:{key}"
    try:
        from fastapi_app.core.redis_wrapper import get_client, note_command_failure, note_command_success

        _redis = get_client()
        if _redis:
            # 第十四轮：incr 与 expire 必须同一 pipeline —— 原实现 `_attempts == 1`
            # 后单独 await expire，若此时连接断开/worker 崩溃，计数 key 永不过期
            # （Redis 默认无 TTL），该 IP 永久 429。pipeline 里的 expire 与 incr
            # 同批原子提交；对已存在但无 TTL 的 key（历史脏数据）由下方 expire
            # 兜底重设（重复设置无害）。
            _pipe = _redis.pipeline()
            _pipe.incr(_login_burst_key)
            _pipe.expire(_login_burst_key, LOGIN_BURST_WINDOW)
            _pipe.incr(_login_rate_limit_key)
            _pipe.expire(_login_rate_limit_key, LOGIN_ATTEMPT_WINDOW)
            _burst, _, _attempts, _ = await _pipe.execute()
            note_command_success()
            if _burst > LOGIN_BURST_LIMIT:
                logger.warning("[Login] 登录尝试过快，1分钟内超过%d次: IP=%s", LOGIN_BURST_LIMIT, key)
                raise HTTPException(status_code=429, detail="登录尝试过于频繁，请1分钟后重试", headers={"Retry-After": str(LOGIN_BURST_WINDOW)})
            if _attempts > LOGIN_ATTEMPT_LIMIT:
                logger.warning("[Login] 登录尝试过多，暂时锁定: IP=%s", key)
                raise HTTPException(status_code=429, detail="登录尝试过多，请5分钟后重试", headers={"Retry-After": str(LOGIN_ATTEMPT_WINDOW)})
    except HTTPException:
        raise
    except Exception as e:  # defensive: Redis限流不可用时降级到进程内存滑动窗口限流
        # 告知缓存管理器：连接类错误会降级并对后续请求短路（裸客户端路径不经过包装方法）
        note_command_failure(e)
        if not memory_limiter.hit(f"login_burst:{key}", LOGIN_BURST_WINDOW, LOGIN_BURST_LIMIT):
            logger.warning("[Login] 登录尝试过快（内存限流），1分钟内超过%d次: IP=%s", LOGIN_BURST_LIMIT, key)
            raise HTTPException(status_code=429, detail="登录尝试过于频繁，请1分钟后重试", headers={"Retry-After": str(LOGIN_BURST_WINDOW)}) from None
        if not memory_limiter.hit(f"login_attempt:{key}", LOGIN_ATTEMPT_WINDOW, LOGIN_ATTEMPT_LIMIT):
            logger.warning("[Login] 登录尝试过多（内存限流），暂时锁定: IP=%s", key)
            raise HTTPException(status_code=429, detail="登录尝试过多，请5分钟后重试", headers={"Retry-After": str(LOGIN_ATTEMPT_WINDOW)}) from None
        logger.warning("[Login] Redis 限流不可用，已降级为进程内存限流: IP=%s", key)


def _set_login_cookies(  # log-context: internal helper 无请求上下文
    response: Response, request: Request,
    access_token: str, refresh_token: str,
    token_max_age: int, refresh_max_age: int,
) -> None:
    """设置 httpOnly cookie（浏览器 Web 端自动携带），根据 HTTPS/Capacitor 自适应 SameSite/Secure"""
    _is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    _is_capacitor = request.headers.get("x-client-type") == "capacitor" or request.headers.get("origin", "").startswith("http://localhost")
    _samesite: Literal['lax', 'strict', 'none']
    if _is_capacitor and not _is_https:
        _samesite, _secure = "lax", False
    elif _is_https:
        _samesite, _secure = "none", True
    else:
        _samesite, _secure = "lax", False
    response.set_cookie(key="access_token", value=access_token, max_age=token_max_age, httponly=True, samesite=_samesite, secure=_secure, path="/")
    response.set_cookie(key="refresh_token", value=refresh_token, max_age=refresh_max_age, httponly=True, samesite=_samesite, secure=_secure, path="/")


@router.post("/login", response_model=LoginResponse)
@limiter.limit("100/minute", key_func=rate_limit_key)  # 内网宽松：登录接口取消严格限流；P0-6(d) 显式绑键
async def api_login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """AJAX登录API（JWT + Cookie双模式）

    返回JWT Token（移动端通过 Authorization: Bearer <token> 使用），
    同时设置 httpOnly cookie（浏览器自动携带）。
    """
    from slowapi.util import get_remote_address

    from fastapi_app.services.auth_service import authenticate_login

    key = get_remote_address(request)
    await _check_login_rate_limit(key)

    username = data.username.strip()
    password = data.password

    if not username or not password:
        logger.info(f"[Login] 登录失败: 用户名或密码为空, IP={key}")
        raise HTTPException(status_code=400, detail="请输入用户名和密码")

    if len(password) > 128:
        logger.info(f"[Login] 登录失败: 密码过长, IP={key}")
        raise HTTPException(status_code=400, detail="密码长度不能超过128位")

    result = await authenticate_login(db, username, password, data.remember, key)
    user = result['user']

    _set_login_cookies(
        response, request,
        result['access_token'], result['refresh_token'],
        result['token_max_age'], result['refresh_max_age'],
    )

    logger.info("[Login] 登录成功: IP=%s, user_id=%s", key, user.id)

    return LoginResponse(
        success=True,
        message="登录成功",
        access_token=result['access_token'],
        token_type="bearer",  # nosec  # noqa: S106  # OAuth2 token type, not a password
        user=UserInfoResponse(
            user_id=user.id,
            username=user.username,
            is_super=user.is_super,
            factory=user.factory,
            permissions=[p.code for p in user.permissions] if user.permissions else [],
        ),
    )


@router.post("/logout")
async def api_logout(request: Request):
    """登出接口 — 撤销 token 并清除 httpOnly cookie（允许未认证调用以清理过期session）"""
    # 尝试撤销当前 token（加入黑名单）
    try:
        from fastapi_app.core.deps import _decode_jwt_token, revoke_token
        cookie_token = request.cookies.get('access_token')
        if cookie_token:
            payload = _decode_jwt_token(cookie_token)
            jti = payload.get('jti')
            exp = payload.get('exp')
            if jti and exp:
                await revoke_token(jti, exp)
        # 撤销刷新令牌
        refresh_cookie = request.cookies.get('refresh_token')
        if refresh_cookie:
            try:
                r_payload = _decode_jwt_token(refresh_cookie)
                r_jti = r_payload.get('jti')
                r_exp = r_payload.get('exp')
                if r_jti and r_exp:
                    await revoke_token(r_jti, r_exp)
            except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                logger.warning("[Logout] 撤销刷新令牌失败（不影响登出）: %s", e)
        # Bearer token 也尝试撤销
        auth_header = request.headers.get('authorization', '')
        if auth_header.startswith('Bearer '):
            bearer_token = auth_header[7:]
            if bearer_token and bearer_token != cookie_token:
                payload = _decode_jwt_token(bearer_token)
                jti = payload.get('jti')
                exp = payload.get('exp')
                if jti and exp:
                    await revoke_token(jti, exp)
    except Exception as e:  # defensive: token撤销失败不影响登出流程
        logger.warning("[Logout] token 撤销流程异常（不影响登出）: %s", e)

    # 浏览器表单POST提交时，返回重定向而非JSON
    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    if "text/html" in accept or content_type.startswith("application/x-www-form-urlencoded"):
        from starlette.responses import RedirectResponse
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie(key="access_token", path="/")
        resp.delete_cookie(key="refresh_token", path="/")
        return resp
    # API 调用：返回 JSON
    import json

    from fastapi.responses import Response
    json_resp = Response(
        content=json.dumps(success_response(message="已登出"), ensure_ascii=False),
        media_type="application/json",
    )
    json_resp.delete_cookie(key="access_token", path="/")
    json_resp.delete_cookie(key="refresh_token", path="/")
    return json_resp


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


# refresh token 轮换（P1-3）
# ---------------------------
# 此前 /auth/refresh 只签发新的 access token，被窃的 refresh token 可用满
# REFRESH_TOKEN_EXPIRE_DAYS（7 天）。轮换后它在下一次正常刷新时即失效。
#
# grace 窗口:前端 401 单飞是**每个标签页各自**的（api/request.ts），ERP 用户常开多页,
# 同一 refresh token 被并发使用是常态。窗口内用旧 token 重放时，用**同一个新 jti**
# 重新签发,使各页拿到等价凭据,而不是被后到者踢成 401。
# 只存 jti(不是 token):jti 不能用于认证,落 Redis 无额外暴露。
REFRESH_ROTATION_GRACE_SECONDS = 30.0
_REFRESH_ROTATION_KEY = 'refresh_rot:{}'  # 旧 jti -> 新 jti


async def _remember_rotation(old_jti: str | None, new_jti: str) -> None:
    """记下「旧 jti → 新 jti」，供 grace 窗口内的并发重放使用。"""
    if REFRESH_ROTATION_GRACE_SECONDS <= 0 or not old_jti:
        return
    from fastapi_app.core.redis_wrapper import safe_set
    # 至少 1 秒：配置成 (0,1) 会被 int() 截断成 0，SETEX 0 会抛 ResponseError，
    # 而它被 safe_set 吞掉 → grace 静默失效（配置被无声忽略）。
    ttl = max(1, int(REFRESH_ROTATION_GRACE_SECONDS))
    await safe_set(
        _REFRESH_ROTATION_KEY.format(old_jti), new_jti,
        timeout=ttl, context='refresh 轮换',
    )


async def _rotation_grace_jti(old_jti: str | None) -> str | None:
    """grace 窗口内返回该旧 token 对应的新 jti；窗口外（或 Redis 不可用）返回 None。"""
    if REFRESH_ROTATION_GRACE_SECONDS <= 0 or not old_jti:
        return None
    from fastapi_app.core.redis_wrapper import safe_get
    value = await safe_get(_REFRESH_ROTATION_KEY.format(old_jti), context='refresh 轮换')
    return value if isinstance(value, str) and value else None


@router.post("/refresh")
async def api_refresh_token(
    request: Request,
    response: Response,
    data: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_async_db),
):
    """刷新访问令牌 — 使用刷新令牌获取新的 access token

    刷新令牌来源优先级：
    1. 请求体中的 refresh_token（移动端/Capacitor）
    2. httpOnly cookie 中的 refresh_token（浏览器Web端）
    """
    from fastapi_app.core.deps import _decode_jwt_token, is_token_revoked

    refresh_token = None
    if data and data.refresh_token:
        refresh_token = data.refresh_token
    else:
        refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(status_code=401, detail="缺少刷新令牌")

    try:
        # 类型校验（type == 'refresh'）由 _decode_jwt_token 的 expected_type 参数统一处理
        payload = _decode_jwt_token(refresh_token, expected_type='refresh')
    except HTTPException:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期") from None

    jti = payload.get("jti")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="刷新令牌无效")

    # 并发重放（多标签页各自单飞）→ grace 窗口内用同一个新 jti 重新签发，
    # 各标签页拿到等价凭据，而不是被后到者踢成 401。窗口外一律 401。
    grace_jti = None
    if await is_token_revoked(jti):
        grace_jti = await _rotation_grace_jti(jti)
        # ⚠️ 必须**复查新 jti 是否已被吊销**：它可能在这 30 秒内被吊销（最典型的是
        # 用户已登出）。漏掉这一句，持有旧 refresh token 的人就能在登出后再换到
        # 一枚仍然有效的 access token —— 登出后最长 ACCESS_TOKEN_EXPIRE_MINUTES
        # 的未授权访问窗口（安全复审 2026-09-28 指出）。
        if grace_jti is None or await is_token_revoked(grace_jti):
            raise HTTPException(status_code=401, detail="刷新令牌已失效")
        # grace 命中即记录：这既是"多标签页并发"的正常信号，也可能是攻击者
        # 在窗口内抢用旧 token —— 两种情况都需要可见，便于事后判读。
        logger.warning(
            "[Refresh] grace 窗口内重放旧 refresh token: user_id=%s old_jti=%s", user_id, jti,
        )

    from fastapi_app.services import user_service

    user_row = await user_service.get_user_auth_row_by_id(db, int(user_id))
    if not user_row or not user_row.status:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    token_data = {"sub": str(user_id), "username": user_row.username}
    token_max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    access_token = create_access_token(
        token_data,
        expires_delta=timedelta(seconds=token_max_age),
    )

    if grace_jti is not None:
        new_refresh_token = create_refresh_token(token_data, jti=grace_jti)
    else:
        # 轮换：签发新 refresh token，吊销旧的，并记下映射供 grace 窗口内重放
        new_jti = uuid.uuid4().hex
        new_refresh_token = create_refresh_token(token_data, jti=new_jti)
        await _remember_rotation(jti, new_jti)
        from fastapi_app.core.deps import revoke_token
        exp = payload.get("exp")
        if jti and exp:
            await revoke_token(jti, exp)

    _is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    _samesite: Literal['lax', 'strict', 'none'] = "none" if _is_https else "lax"
    _secure = _is_https
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=token_max_age,
        httponly=True,
        samesite=_samesite,
        secure=_secure,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        samesite=_samesite,
        secure=_secure,
        path="/",
    )

    logger.info("[Refresh] 令牌刷新成功（refresh 已轮换）: user_id=%s", user_id)
    if data and data.refresh_token:
        # 请求体传 refresh token 的客户端（移动端/API）读不到 httpOnly cookie，
        # 必须把轮换后的新 token 回传 —— 否则它仍持旧 token，grace 窗口过后必然 401。
        return success_response(
            access_token=access_token, refresh_token=new_refresh_token,
            # token_type 是 OAuth2 令牌类型标识（RFC 6749），非口令 —— S106 误报
            token_type="bearer",  # noqa: S106
        )
    # token_type 是 OAuth2 令牌类型标识（RFC 6749），非口令 —— S106 误报
    return success_response(access_token=access_token, token_type="bearer")  # noqa: S106


# ==================== 文件上传 ====================

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """图片上传API（限制5MB，需登录）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="没有选择文件")

    # 检查文件类型
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    # 读取文件内容并检查大小：只读 MAX_UPLOAD_SIZE + 1 字节，超限即拒，
    # 避免恶意超大文件先全量读入内存再判断（内存耗尽 DoS）。
    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过{MAX_UPLOAD_SIZE // 1024 // 1024}MB限制")

    # P0-12：统一走公共魔数层（失败记录文件签名并返回 400，语义不变）
    require_upload_magic(
        content,
        ext,
        filename=file.filename,
        detail="文件内容与扩展名不匹配，可能不是有效的图片文件",
    )

    # 使用对象存储服务保存文件，数据库存储元数据
    from fastapi_app.services.storage_service import save_upload
    result = await save_upload(
        content=content,
        original_filename=file.filename,
        db=db,
        uploader_id=user_id,
    )
    return success_response(url=result["url"], filename=result["storage_key"], file_id=result["id"])

