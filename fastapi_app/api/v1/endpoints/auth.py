"""
认证与文件上传接口

支持两种认证模式：
1. JWT Bearer Token（移动端/API客户端）
2. Cookie-based JWT（浏览器Web端）— 登录后设置 httpOnly cookie
"""
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import create_access_token, get_current_user_id
from fastapi_app.core.limiter import limiter, memory_limiter
from fastapi_app.core.response import success_response

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
        from fastapi_app.core.redis_wrapper import get_client
        _redis = get_client()
        if _redis:
            _pipe = _redis.pipeline()
            _pipe.incr(_login_burst_key)
            _pipe.incr(_login_rate_limit_key)
            _burst, _attempts = await _pipe.execute()
            if _burst == 1:
                await _redis.expire(_login_burst_key, LOGIN_BURST_WINDOW)
            if _burst > LOGIN_BURST_LIMIT:
                logger.warning("[Login] 登录尝试过快，1分钟内超过%d次: IP=%s", LOGIN_BURST_LIMIT, key)
                raise HTTPException(status_code=429, detail="登录尝试过于频繁，请1分钟后重试", headers={"Retry-After": str(LOGIN_BURST_WINDOW)})
            if _attempts == 1:
                await _redis.expire(_login_rate_limit_key, LOGIN_ATTEMPT_WINDOW)
            if _attempts > LOGIN_ATTEMPT_LIMIT:
                logger.warning("[Login] 登录尝试过多，暂时锁定: IP=%s", key)
                raise HTTPException(status_code=429, detail="登录尝试过多，请5分钟后重试", headers={"Retry-After": str(LOGIN_ATTEMPT_WINDOW)})
    except HTTPException:
        raise
    except Exception:  # defensive: Redis限流不可用时降级到进程内存滑动窗口限流
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
    if _is_capacitor and not _is_https:
        _samesite, _secure = "lax", False
    elif _is_https:
        _samesite, _secure = "none", True
    else:
        _samesite, _secure = "lax", False
    response.set_cookie(key="access_token", value=access_token, max_age=token_max_age, httponly=True, samesite=_samesite, secure=_secure, path="/")
    response.set_cookie(key="refresh_token", value=refresh_token, max_age=refresh_max_age, httponly=True, samesite=_samesite, secure=_secure, path="/")


@router.post("/login", response_model=LoginResponse)
@limiter.limit("100/minute")  # 内网宽松：登录接口取消严格限流
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
    resp = Response(
        content=json.dumps(success_response(message="已登出"), ensure_ascii=False),
        media_type="application/json",
    )
    resp.delete_cookie(key="access_token", path="/")
    resp.delete_cookie(key="refresh_token", path="/")
    return resp


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


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
    if await is_token_revoked(jti):
        raise HTTPException(status_code=401, detail="刷新令牌已失效")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="刷新令牌无效")

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

    _is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    _samesite = "none" if _is_https else "lax"
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

    logger.info("[Refresh] 令牌刷新成功: user_id=%s", user_id)
    return success_response(access_token=access_token, token_type="bearer")


# ==================== 文件上传 ====================

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB
IMAGE_SIGNATURES = {
    b'\x89PNG\r\n\x1a\n': 'png',
    b'\xff\xd8\xff': 'jpg',
    b'GIF87a': 'gif',
    b'GIF89a': 'gif',
    b'RIFF': 'webp',
}


def _validate_image_content(content: bytes, ext: str) -> bool:
    for sig, sig_ext in IMAGE_SIGNATURES.items():
        if content[:len(sig)] == sig:
            if sig_ext == 'jpg' and ext in ('jpg', 'jpeg'):
                return True
            if sig_ext == ext:
                return True
    return False


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

    if not _validate_image_content(content, ext):
        raise HTTPException(status_code=400, detail="文件内容与扩展名不匹配，可能不是有效的图片文件")

    # 使用对象存储服务保存文件，数据库存储元数据
    from fastapi_app.services.storage_service import save_upload
    result = await save_upload(
        content=content,
        original_filename=file.filename,
        db=db,
        uploader_id=user_id,
    )
    return success_response(url=result["url"], filename=result["storage_key"], file_id=result["id"])

