"""
FastAPI 依赖注入

认证和权限检查：支持两种认证方式（优先级从高到低）：
1. JWT Bearer Token（Authorization: Bearer <token>）— 用于API客户端/移动端
2. Cookie-based JWT（httpOnly cookie）— 用于浏览器Web端

已迁移到全异步数据库操作，移除同步引擎依赖。
"""
import logging
import time
from datetime import UTC

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.config import settings
from fastapi_app.core.database import get_async_db
from fastapi_app.shared_models import Permission, User

logger = logging.getLogger(__name__)
_PERMISSION_CACHE: dict[int, tuple[float, User]] = {}
_PERMISSION_CACHE_TTL = 30

def _get_cached_user(user_id: int) -> User | None:
    entry = _PERMISSION_CACHE.get(user_id)
    if entry is None:
        return None
    cached_at, user = entry
    if time.monotonic() - cached_at > _PERMISSION_CACHE_TTL:
        del _PERMISSION_CACHE[user_id]
        return None
    return user

def _set_cached_user(user_id: int, user: User) -> None:
    _PERMISSION_CACHE[user_id] = (time.monotonic(), user)
    if len(_PERMISSION_CACHE) > 500:
        oldest_key = min(_PERMISSION_CACHE, key=lambda k: _PERMISSION_CACHE[k][0])
        del _PERMISSION_CACHE[oldest_key]

def invalidate_user_permission_cache(user_id: int | None=None) -> None:
    if user_id is not None:
        _PERMISSION_CACHE.pop(user_id, None)
    else:
        _PERMISSION_CACHE.clear()
__all__ = ['get_current_user_id', 'require_permission', 'create_access_token', 'get_async_db', 'get_user_identity']


def get_user_identity(user: User) -> tuple[str, str]:
    """从User对象提取(session_id, username)，用于审计和暂存区"""
    return str(user.id), user.username

def _get_signing_key() -> str:
    """获取 JWT 签名密钥（支持 HS256 和 RS256）"""
    if settings.ALGORITHM.startswith('RS'):
        if not settings.JWT_PRIVATE_KEY_PATH:
            raise RuntimeError('RS256 模式必须设置 JWT_PRIVATE_KEY_PATH 环境变量')
        with open(settings.JWT_PRIVATE_KEY_PATH) as f:
            return f.read()
    return settings.SECRET_KEY

def _get_verify_key() -> str:
    """获取 JWT 验证密钥（支持 HS256 和 RS256）"""
    if settings.ALGORITHM.startswith('RS'):
        if not settings.JWT_PUBLIC_KEY_PATH:
            raise RuntimeError('RS256 模式必须设置 JWT_PUBLIC_KEY_PATH 环境变量')
        with open(settings.JWT_PUBLIC_KEY_PATH) as f:
            return f.read()
    return settings.SECRET_KEY

def create_access_token(data: dict, expires_delta=None) -> str:
    """生成JWT Token（支持 HS256 / RS256）"""
    from datetime import datetime, timedelta

    import jwt
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode['exp'] = expire
    return jwt.encode(to_encode, _get_signing_key(), algorithm=settings.ALGORITHM)

def _decode_jwt_token(token: str) -> dict:
    """解码并验证JWT Token，返回payload或抛出异常"""
    import jwt
    try:
        payload = jwt.decode(token, _get_verify_key(), algorithms=[settings.ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token已过期') from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token无效') from None

def _get_user_id_from_jwt(request: Request) -> int | None:
    """
    尝试从 Authorization: Bearer <token> 中获取用户ID。
    如果没有Bearer Token或解码失败，返回None（不抛异常，降级到cookie方式）。
    """
    auth_header = request.headers.get('authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header[7:]
    if not token:
        return None
    try:
        payload = _decode_jwt_token(token)
        user_id = payload.get('sub')
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
    cookie_token = request.cookies.get('access_token')
    if not cookie_token:
        return None
    try:
        payload = _decode_jwt_token(cookie_token)
        user_id = payload.get('sub')
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
_USER_ACTIVE_CACHE: dict[int, tuple[float, bool]] = {}
_USER_ACTIVE_CACHE_TTL = 30

async def _verify_user_active(user_id: int, db: AsyncSession) -> bool:
    """验证用户仍存在且处于启用状态（带 L1 缓存，TTL 30s）"""
    now = time.monotonic()
    entry = _USER_ACTIVE_CACHE.get(user_id)
    if entry is not None:
        cached_at, is_active = entry
        if now - cached_at < _USER_ACTIVE_CACHE_TTL:
            return is_active
    result = await db.execute(select(User.id, User.status).where(User.id == user_id))
    user = result.first()
    is_active = user is not None and bool(user.status)
    _USER_ACTIVE_CACHE[user_id] = (now, is_active)
    if len(_USER_ACTIVE_CACHE) > 500:
        oldest_key = min(_USER_ACTIVE_CACHE, key=lambda k: _USER_ACTIVE_CACHE[k][0])
        del _USER_ACTIVE_CACHE[oldest_key]
    return is_active

async def get_current_user_id(request: Request, db: AsyncSession=Depends(get_async_db)) -> int:
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='未登录')
    if not await _verify_user_active(user_id, db):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='用户不存在或已被禁用')
    return user_id

async def _get_user_with_permissions(request: Request, db: AsyncSession=Depends(get_async_db)) -> User:
    """
    解析认证信息并从数据库查询用户，同时预加载权限列表。

    使用 L1 进程内缓存（TTL 30s）避免每次请求都查询数据库。
    expunge 使 User 对象可在任何上下文安全使用。
    """
    user_id = await get_current_user_id(request, db)
    cached_user = _get_cached_user(user_id)
    if cached_user is not None:
        return cached_user
    result = await db.execute(select(User).options(joinedload(User.permissions).selectinload(Permission.children)).where(User.id == user_id))
    user = result.unique().scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='用户不存在')
    db.expunge(user)
    _set_cached_user(user_id, user)
    return user

def require_permission(permission_name: str):
    """
    权限检查依赖工厂。

    用法：
        @router.post("/...")
        async def endpoint(user: User = Depends(require_permission("batch_import"))):
            ...
    """

    async def permission_checker(current_user: User=Depends(_get_user_with_permissions)) -> User:
        if not current_user.has_permission(permission_name):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='权限不足')
        return current_user
    return permission_checker
