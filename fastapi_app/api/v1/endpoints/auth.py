"""
认证与文件上传接口
"""
import os
import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import create_access_token, get_current_user
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
    user_id: int = Depends(get_current_user),
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
    user_id: int = Depends(get_current_user),
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
    data: LoginRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """AJAX登录API（JWT模式）

    返回JWT Token，前端应存储到localStorage并在后续请求中
    通过 Authorization: Bearer <token> 传递。
    登录接口限速5次/分钟，防止暴力破解。
    """
    # 手动限速检查：登录接口5次/分钟
    from limits import parse
    from slowapi.util import get_remote_address

    limiter = request.app.state.limiter
    key = get_remote_address(request)
    item = parse("5/minute")
    if not limiter._limiter.hit(item, key, "auth/login"):
        logger.warning(f"[Login] 登录尝试过于频繁: IP={key}")
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请稍后再试"
        )

    from werkzeug.security import check_password_hash

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
    if not check_password_hash(user.password, password):
        logger.warning(f"[Login] 登录失败: 密码错误, IP={key}, username={username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 生成JWT Token
    from fastapi_app.core.config import settings
    permissions = [p.code for p in user.permissions] if user.permissions else []
    token_data = {
        "sub": str(user.id),
        "username": user.username,
        "is_super": user.is_super,
        "permissions": permissions,
    }
    access_token = create_access_token(token_data)

    logger.info(f"[Login] 登录成功: IP={key}, username={username}, user_id={user.id}")

    return LoginResponse(
        success=True,
        message="登录成功",
        access_token=access_token,
        token_type="bearer",
    )


# ==================== 文件上传 ====================

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user),
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

