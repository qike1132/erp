"""
认证与文件上传接口

支持两种认证模式：
1. JWT Bearer Token（移动端/API客户端）
2. Cookie-based JWT（浏览器Web端）— 登录后设置 httpOnly cookie
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import create_access_token, get_current_user_id
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Schemas ====================

class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    remember: bool = False

class LoginResponse(BaseModel):
    success: bool
    message: str = ""
    error: str = ""
    access_token: str = ""
    token_type: str = ""

class FrontendErrorLogRequest(BaseModel):
    timestamp: str
    error: str
    stack: str = ""
    context: dict = {}
    url: str = ""
    userAgent: str = ""

class UserInfoResponse(BaseModel):
    user_id: int
    username: str
    is_super: bool
    permissions: list[str]


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


# ==================== 登录状态检查 ====================

@router.get("/check", response_model=LoginCheckResponse)
async def check_login_status(
    user_id: int = Depends(get_current_user_id),
):
    """检查登录状态接口

    前端每5分钟调用一次此接口检查登录是否有效。
    返回200表示登录有效，401表示需要重新登录。
    """
    return {
        "success": True,
        "message": "登录状态有效",
        "user_id": user_id
    }


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取当前登录用户信息（含权限列表）

    前端在初始化时调用此接口获取用户详情和权限，
    用于前端路由守卫和导航菜单渲染。
    """
    result = await db.execute(
        select(User).options(selectinload(User.permissions)).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user or not user.status:
        raise HTTPException(status_code=401, detail="用户不存在或已禁用")

    return UserInfoResponse(
        user_id=user.id,
        username=user.username,
        is_super=user.is_super,
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

    return {
        "success": True,
        "message": "错误日志已记录"
    }


# ==================== 登录 ====================

@router.post("/login", response_model=LoginResponse)
async def api_login(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """AJAX登录API（JWT + Cookie双模式）

    返回JWT Token（移动端通过 Authorization: Bearer <token> 使用），
    同时设置 httpOnly cookie（浏览器自动携带，替代 Flask session）。
    """
    from fastapi_app.core.security import check_needs_rehash, hash_password, needs_migration, verify_password
    from slowapi.util import get_remote_address

    key = get_remote_address(request)

    _login_rate_limit_key = f"login_attempt:{key}"
    try:
        from utils.redis_cache import redis_cache
        _redis = redis_cache.redis_client
        if _redis:
            _attempts = await _redis.incr(_login_rate_limit_key)
            if _attempts == 1:
                await _redis.expire(_login_rate_limit_key, 300)
            if _attempts > 10:
                logger.warning("[Login] 登录尝试过多，暂时锁定: IP=%s", key)
                raise HTTPException(status_code=429, detail="登录尝试过多，请5分钟后重试")
    except HTTPException:
        raise
    except Exception:
        logger.warning("[Login] Redis 限流不可用，降级为允许登录: IP=%s", key)

    username = data.username.strip()
    password = data.password

    if not username or not password:
        logger.info(f"[Login] 登录失败: 用户名或密码为空, IP={key}")
        raise HTTPException(status_code=400, detail="请输入用户名和密码")

    if len(password) > 128:
        logger.info(f"[Login] 登录失败: 密码过长, IP={key}")
        raise HTTPException(status_code=400, detail="密码长度不能超过128位")

    result = await db.execute(
        select(User).where(User.username == username).options(
            selectinload(User.permissions)
        )
    )
    user = result.scalar_one_or_none()

    from fastapi_app.core.security import verify_password as _vp
    dummy_hash = "$argon2id$v=19$m=47104,t=2,p=2$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    if not user:
        _vp("timing_sidechannel_dummy", dummy_hash)
        logger.warning("[Login] 登录失败: IP=%s", key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.status:
        _vp("timing_sidechannel_dummy", dummy_hash)
        logger.warning("[Login] 登录失败: IP=%s", key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(password, user.password):
        logger.warning("[Login] 登录失败: IP=%s", key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if needs_migration(user.password):
        try:
            new_hash = hash_password(password)
            user.password = new_hash
            await db.commit()
            logger.info(f"[Login] 密码哈希已迁移到 Argon2id: user_id={user.id}")
        except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
            logger.warning(f"[Login] 密码哈希迁移失败（不影响登录）: {e}")
            await db.rollback()
    elif check_needs_rehash(user.password):
        try:
            new_hash = hash_password(password)
            user.password = new_hash
            await db.commit()
            logger.info(f"[Login] 密码哈希参数已升级: user_id={user.id}")
        except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
            logger.warning(f"[Login] 密码哈希升级失败（不影响登录）: {e}")
            await db.rollback()

    # 生成JWT Token（仅存储最小必要信息，权限通过数据库实时查询）
    token_data = {
        "sub": str(user.id),
        "username": user.username,
    }

    # Cookie/JWT 有效期：记住我24小时，否则1小时
    token_max_age = 86400 if data.remember else 3600
    access_token = create_access_token(
        token_data,
        expires_delta=timedelta(seconds=token_max_age),
    )

    # 设置 httpOnly cookie（浏览器Web端自动携带）
    _is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    _is_capacitor = request.headers.get("x-client-type") == "capacitor" or request.headers.get("origin", "").startswith("http://localhost")
    if _is_capacitor and not _is_https:
        _samesite = "lax"
        _secure = False
    elif _is_https:
        _samesite = "none"
        _secure = True
    else:
        _samesite = "lax"
        _secure = False
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=token_max_age,
        httponly=True,
        samesite=_samesite,
        secure=_secure,
        path="/",
    )

    # auth_status cookie 已移除，前端请使用 GET /api/v1/auth/check 检查登录状态

    logger.info("[Login] 登录成功: IP=%s, user_id=%s", key, user.id)

    return LoginResponse(
        success=True,
        message="登录成功",
        access_token=access_token,
        token_type="bearer",  # nosec
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
    except Exception:
        pass  # token 撤销失败不影响登出流程

    # 浏览器表单POST提交时，返回重定向而非JSON
    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    if "text/html" in accept or content_type.startswith("application/x-www-form-urlencoded"):
        from starlette.responses import RedirectResponse
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie(key="access_token", path="/")
        return resp
    # API 调用：返回 JSON
    import json

    from fastapi.responses import Response
    resp = Response(
        content=json.dumps({"success": True, "message": "已登出"}, ensure_ascii=False),
        media_type="application/json",
    )
    resp.delete_cookie(key="access_token", path="/")
    return resp


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
):
    """图片上传API（限制5MB，需登录）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="没有选择文件")

    # 检查文件类型
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    # 读取文件内容并检查大小
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过{MAX_UPLOAD_SIZE // 1024 // 1024}MB限制")

    if not _validate_image_content(content, ext):
        raise HTTPException(status_code=400, detail="文件内容与扩展名不匹配，可能不是有效的图片文件")

    # 生成唯一文件名
    new_filename = f"{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex}.{ext}"

    # 确保上传目录存在（与 main.py 中 StaticFiles 挂载路径一致：项目根目录/static/uploads）
    upload_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))), "static", "uploads")
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, new_filename)

    def _write_file():
        with open(file_path, "wb") as f:
            f.write(content)

    await asyncio.to_thread(_write_file)

    file_url = f"/static/uploads/{new_filename}"
    return {"success": True, "url": file_url, "filename": new_filename}

