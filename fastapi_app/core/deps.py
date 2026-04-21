"""
FastAPI 依赖注入

认证和权限检查：支持两种认证方式（优先级从高到低）：
1. JWT Bearer Token（Authorization: Bearer <token>）— 用于API客户端/移动端
2. Cookie-based JWT（httpOnly cookie）— 用于浏览器Web端
"""

from fastapi import Depends, HTTPException, status, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
import logging

from fastapi_app.core.config import settings
from fastapi_app.shared_models import User, Permission

logger = logging.getLogger(__name__)


def create_access_token(data: dict, expires_delta=None) -> str:
    """生成JWT Token"""
    from datetime import datetime, timedelta, timezone
    import jwt

    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_jwt_token(token: str) -> dict:
    """解码并验证JWT Token，返回payload或抛出异常"""
    import jwt

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT Token已过期",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT Token无效",
        )


def _get_user_id_from_jwt(request: Request) -> int | None:
    """
    尝试从 Authorization: Bearer <token> 中获取用户ID。
    如果没有Bearer Token或解码失败，返回None（不抛异常，降级到cookie方式）。
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]  # 去掉 "Bearer " 前缀
    if not token:
        return None

    try:
        payload = _decode_jwt_token(token)
        user_id = payload.get("sub")
        if user_id:
            return int(user_id)
    except (HTTPException, ValueError):
        pass
    return None


def _get_user_id_from_cookie(request: Request) -> int | None:
    """
    从 httpOnly cookie 中获取当前登录用户 ID（cookie-based JWT）。

    浏览器登录后，FastAPI 在 httpOnly cookie 中设置 JWT token，
    此函数解码该 cookie 中的 JWT 获取用户信息。
    """
    cookie_token = request.cookies.get("access_token")
    if not cookie_token:
        return None

    try:
        payload = _decode_jwt_token(cookie_token)
        user_id = payload.get("sub")
        if user_id:
            return int(user_id)
    except (HTTPException, ValueError):
        pass
    return None


def _resolve_user_id(request: Request) -> int | None:
    """从 JWT Bearer 或 Cookie JWT 中提取用户ID（纯内存操作，无DB查询）"""
    user_id = _get_user_id_from_jwt(request)
    if user_id is None:
        user_id = _get_user_id_from_cookie(request)
    return user_id


async def _verify_user_active(user_id: int) -> bool:
    """验证用户仍存在且处于启用状态（在线程池中执行同步DB查询，不阻塞事件循环）"""
    from fastapi_app.core.database import SyncSessionLocal

    def _check():
        db = SyncSessionLocal()
        try:
            user = db.execute(
                select(User.id, User.status).where(User.id == user_id)
            ).first()
            return user is not None and bool(user.status)
        finally:
            db.close()

    return await run_in_threadpool(_check)


async def get_current_user_id(request: Request) -> int:
    """
    获取当前用户ID（双认证模式）。

    优先级：
    1. Authorization: Bearer <token>（JWT方式，适用于API客户端）
    2. httpOnly cookie 中的 access_token（浏览器Web端）

    验证用户仍存在且处于启用状态，防止已禁用/删除用户的token继续有效。
    返回 user_id: int。
    """
    user_id = _resolve_user_id(request)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
        )

    if not await _verify_user_active(user_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )

    return user_id


async def _get_user_with_permissions(request: Request) -> User:
    """
    解析认证信息并从数据库查询用户，同时预加载权限列表。

    使用 run_in_threadpool 包装同步 DB 查询，避免阻塞事件循环。
    expunge 使 User 对象可在任何上下文安全使用。
    """
    user_id = await get_current_user_id(request)

    from fastapi_app.core.database import SyncSessionLocal

    def _fetch():
        db = SyncSessionLocal()
        try:
            result = db.execute(
                select(User)
                .options(joinedload(User.permissions).selectinload(Permission.children))
                .where(User.id == user_id)
            )
            user = result.unique().scalar_one_or_none()
            if user:
                db.expunge(user)
            return user
        finally:
            db.close()

    user = await run_in_threadpool(_fetch)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )
    return user


def require_permission(permission_name: str):
    """
    权限检查依赖工厂。

    用法：
        @router.post("/...")
        async def endpoint(user: User = Depends(require_permission("batch_import"))):
            ...
    """
    async def permission_checker(
        current_user: User = Depends(_get_user_with_permissions),
    ) -> User:
        if not current_user.has_permission(permission_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user
    return permission_checker
