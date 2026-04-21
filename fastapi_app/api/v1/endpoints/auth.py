"""
认证与文件上传接口

支持两种认证模式：
1. JWT Bearer Token（移动端/API客户端）
2. Cookie-based JWT（浏览器Web端）— 登录后设置 httpOnly cookie
"""
import os
import uuid
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import create_access_token, get_current_user_id
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Schemas ====================

class LoginRequest(BaseModel):
    username: str
    password: str
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


# ==================== 登录状态检查 ====================

@router.get("/check")
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


# ==================== 前端错误日志 ====================

@router.post("/logs/frontend-error")
async def log_frontend_error(
    data: FrontendErrorLogRequest,
    request: Request,
    user_id: int = Depends(get_current_user_id),
):
    """记录前端错误日志（需登录，防止日志洪泛攻击）

    前端在发生错误时调用此接口记录错误信息，
    便于后续分析和优化。
    """
    from fastapi_app.core.logger import get_logger
    
    # 获取客户端IP
    client_ip = request.client.host if request.client else "unknown"
    
    # 记录到日志文件
    logger.warning(
        f"[Frontend Error] IP={client_ip}, URL={data.url}, "
        f"Error={data.error}, Timestamp={data.timestamp}, "
        f"UserAgent={data.userAgent}, Context={data.context}"
    )
    
    # 如果有堆栈信息，也记录下来
    if data.stack:
        logger.debug(f"[Frontend Error Stack] {data.stack}")
    
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
    登录接口限速5次/分钟，防止暴力破解。
    """
    # 手动限速检查：登录接口5次/分钟
    from limits import parse
    from slowapi.util import get_remote_address

    limiter = request.app.state.limiter
    key = get_remote_address(request)
    item = parse("5/minute")
    if not limiter.limiter.hit(item, key, "auth/login"):
        logger.warning(f"[Login] 登录尝试过于频繁: IP={key}")
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请稍后再试"
        )

    from fastapi_app.core.security import verify_password
    from fastapi_app.core.config import settings

    username = data.username.strip()
    password = data.password

    if not username or not password:
        logger.info(f"[Login] 登录失败: 用户名或密码为空, IP={key}")
        raise HTTPException(status_code=400, detail="请输入用户名和密码")

    if len(password) > 128:
        logger.info(f"[Login] 登录失败: 密码过长, IP={key}, username={username}")
        raise HTTPException(status_code=400, detail="密码长度不能超过128位")

    result = await db.execute(
        select(User).where(User.username == username).options(
            selectinload(User.permissions)
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        logger.warning(f"[Login] 登录失败: 用户不存在, IP={key}, username={username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.status:
        logger.warning(f"[Login] 登录失败: 账号已禁用, IP={key}, username={username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(password, user.password):
        logger.warning(f"[Login] 登录失败: 密码错误, IP={key}, username={username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 旧哈希自动迁移：werkzeug pbkdf2/scrypt → bcrypt
    from fastapi_app.core.security import needs_rehash, hash_password as _hash_password
    if needs_rehash(user.password):
        try:
            new_hash = _hash_password(password)
            user.password = new_hash
            await db.flush()
            logger.info(f"[Login] 哈希自动迁移: username={username}, user_id={user.id}")
        except Exception as e:
            logger.warning(f"[Login] 哈希自动迁移失败(不影响登录): {e}")

    # 生成JWT Token（仅存储最小必要信息，权限通过数据库实时查询）
    token_data = {
        "sub": str(user.id),
        "username": user.username,
    }

    # Cookie有效期：remember=True 时31天，否则1天
    cookie_max_age = settings.COOKIE_MAX_AGE if data.remember else 86400
    access_token = create_access_token(
        token_data,
        expires_delta=timedelta(seconds=cookie_max_age),
    )

    # 设置 httpOnly cookie（浏览器Web端自动携带）
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=cookie_max_age,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https",
        path="/",
    )

    logger.info(f"[Login] 登录成功: IP={key}, username={username}, user_id={user.id}")

    return LoginResponse(
        success=True,
        message="登录成功",
        access_token=access_token,
        token_type="bearer",
    )


@router.post("/logout")
async def api_logout(request: Request):
    """登出接口 — 清除 httpOnly cookie，浏览器表单提交时重定向到登录页"""
    # 浏览器表单POST提交时，返回重定向而非JSON
    accept = request.headers.get("accept", "")
    content_type = request.headers.get("content-type", "")
    if "text/html" in accept or content_type.startswith("application/x-www-form-urlencoded"):
        from starlette.responses import RedirectResponse
        resp = RedirectResponse(url="/login", status_code=303)
        resp.delete_cookie(key="access_token", path="/")
        return resp
    # API 调用：返回 JSON
    from fastapi.responses import Response
    import json
    resp = Response(
        content=json.dumps({"success": True, "message": "已登出"}, ensure_ascii=False),
        media_type="application/json",
    )
    resp.delete_cookie(key="access_token", path="/")
    return resp


# ==================== 文件上传 ====================

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload")
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
        raise HTTPException(status_code=400, detail="文件大小超过5MB限制")

    # 生成唯一文件名
    new_filename = f"{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}.{ext}"

    # 确保上传目录存在
    upload_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "static", "uploads")
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, new_filename)

    # 写入文件
    with open(file_path, "wb") as f:
        f.write(content)

    file_url = f"/static/uploads/{new_filename}"
    return {"success": True, "url": file_url, "filename": new_filename}

