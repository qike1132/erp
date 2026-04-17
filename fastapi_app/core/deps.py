"""
FastAPI 依赖注入

认证和权限检查：支持两种认证方式（优先级从高到低）：
1. JWT Bearer Token（Authorization: Bearer <token>）— 用于API客户端/移动端
2. Flask session cookie — 用于浏览器Web端（兼容模式）

由于 FastAPI 和 Flask 运行在同一域名下（Flask 作为反向代理转发 /api/v1 到 FastAPI），
浏览器会自动携带 Flask 设置的 session cookie。
"""

from fastapi import Depends, HTTPException, status, Request
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
import logging

from fastapi_app.core.config import settings
from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import User, Permission

logger = logging.getLogger(__name__)

# 缓存 Flask session 签名序列化器，避免每请求创建 Flask 实例
_flask_session_serializer = None


def _ensure_session_serializer():
    """确保 Flask session 序列化器已初始化（线程安全）"""
    global _flask_session_serializer
    if _flask_session_serializer is None:
        from flask.sessions import SecureCookieSessionInterface
        from flask import Flask as _Flask

        _app = _Flask(__name__)
        _app.config["SECRET_KEY"] = settings.SECRET_KEY
        si = SecureCookieSessionInterface()
        _flask_session_serializer = si.get_signing_serializer(_app)


def create_access_token(data: dict, expires_delta=None) -> str:
    """生成JWT Token"""
    from datetime import datetime, timedelta
    from jose import jwt

    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _decode_jwt_token(token: str) -> dict:
    """解码并验证JWT Token，返回payload或抛出异常"""
    from jose import jwt, JWTError

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT Token无效",
        )


def _get_user_id_from_jwt(request: Request) -> int | None:
    """
    尝试从 Authorization: Bearer <token> 中获取用户ID。
    如果没有Bearer Token或解码失败，返回None（不抛异常，降级到session方式）。
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


def _get_user_id_from_session(request: Request) -> int | None:
    """
    从 Flask session cookie 中获取当前登录用户 ID。

    Flask 的 session 是签名 cookie，使用 itsdangerous 库解析。
    使用 settings.SECRET_KEY（由 pydantic_settings 从 .env 读取）。
    """
    global _flask_session_serializer

    session_cookie = request.cookies.get("session")
    if not session_cookie:
        return None

    try:
        # 缓存签名序列化器，避免每请求创建 Flask 实例
        _ensure_session_serializer()

        # 设置 max_age，与 Flask PERMANENT_SESSION_LIFETIME 对齐（默认31天）
        session_data = _flask_session_serializer.loads(session_cookie, max_age=settings.SESSION_COOKIE_MAX_AGE)
    except Exception as e:
        logger.warning(f"Session cookie验证失败: {type(e).__name__}: {e}")
        return None

    user_id = session_data.get("user_id")
    if user_id:
        return int(user_id)
    return None


def get_current_user(request: Request):
    """
    获取当前用户ID（双认证模式）。

    优先级：
    1. Authorization: Bearer <token>（JWT方式，适用于API客户端）
    2. Flask session cookie（浏览器Web端兼容模式）
    """
    # 优先尝试 JWT Bearer Token
    user_id = _get_user_id_from_jwt(request)

    # 降级到 Flask session cookie
    if user_id is None:
        user_id = _get_user_id_from_session(request)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
        )

    return user_id


def _get_user_with_permissions(request: Request) -> User:
    """
    解析 session cookie 并从数据库查询用户，同时预加载权限列表。

    自管理 session 生命周期：创建 → 查询（joinedload 预加载 permissions + selectinload 预加载 children）
    → expunge（脱离 session 但保留已加载数据）→ 关闭。
    这样返回的 User 对象可在任何上下文安全使用，无需担心 lazy-load 或 session 脱离问题。
    """
    user_id = get_current_user(request)

    db = SyncSessionLocal()
    try:
        result = db.execute(
            select(User)
            .options(joinedload(User.permissions).selectinload(Permission.children))
            .where(User.id == user_id)
        )
        user = result.unique().scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户不存在",
            )
        # 预加载 permissions 后脱离 session，使 User 对象不再依赖数据库连接
        db.expunge(user)
        return user
    finally:
        db.close()


def require_permission(permission_name: str):
    """
    权限检查依赖工厂。

    用法：
        @router.post("/...")
        async def endpoint(user: User = Depends(require_permission("batch_import"))):
            ...
    """
    def permission_checker(
        current_user: User = Depends(_get_user_with_permissions),
    ) -> User:
        if not current_user.has_permission(permission_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user
    return permission_checker
