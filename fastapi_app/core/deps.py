"""
FastAPI 依赖注入

认证和权限检查：支持两种认证方式（优先级从高到低）：
1. JWT Bearer Token（Authorization: Bearer <token>）— 用于API客户端/移动端
2. Cookie-based JWT（httpOnly cookie）— 用于浏览器Web端

已迁移到全异步数据库操作，移除同步引擎依赖。
"""
import asyncio
import contextlib
import logging
import time
from collections import OrderedDict

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.auth.blacklist import is_token_revoked, revoke_token
from fastapi_app.core.auth.token import (
    _decode_jwt_token,
    create_access_token,
    create_refresh_token,
)
from fastapi_app.core.database import get_async_db
from fastapi_app.shared_models import Permission, User

logger = logging.getLogger(__name__)


class _TTLCache:
    """异步安全的 LRU TTL 缓存，替代 dict 避免并发竞态"""

    def __init__(self, ttl: float = 30, maxsize: int = 500):
        self._ttl = ttl
        self._maxsize = maxsize
        self._lock = asyncio.Lock()
        self._data: OrderedDict[int, tuple[float, object]] = OrderedDict()

    async def get(self, key: int) -> object | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            cached_at, value = entry
            if time.monotonic() - cached_at > self._ttl:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    async def set(self, key: int, value: object) -> None:
        async with self._lock:
            self._data[key] = (time.monotonic(), value)
            self._data.move_to_end(key)
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    async def pop(self, key: int) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()


_PERMISSION_CACHE = _TTLCache(ttl=5, maxsize=500)

async def _get_cached_user(user_id: int) -> User | None:
    cached = await _PERMISSION_CACHE.get(user_id)
    try:
        from fastapi_app.core.metrics import PERM_CACHE_HITS, PERM_CACHE_MISSES
        if cached is not None:
            PERM_CACHE_HITS.inc()
        else:
            PERM_CACHE_MISSES.inc()
    except ImportError:
        pass  # defensive: 可选依赖未安装,优雅降级
    return cached  # type: ignore[return-value]


async def _set_cached_user(user_id: int, user: User) -> None:
    await _PERMISSION_CACHE.set(user_id, user)
    try:
        from fastapi_app.core.metrics import PERM_CACHE_SIZE
        PERM_CACHE_SIZE.set(len(_PERMISSION_CACHE._data))
    except ImportError:
        pass  # defensive: 可选依赖未安装,优雅降级


async def invalidate_user_permission_cache(user_id: int | None=None) -> None:
    if user_id is not None:
        await _PERMISSION_CACHE.pop(user_id)
        with contextlib.suppress(KeyError, AttributeError):
            await _USER_ACTIVE_CACHE.pop(user_id)
    else:
        await _PERMISSION_CACHE.clear()
        with contextlib.suppress(AttributeError):
            await _USER_ACTIVE_CACHE.clear()
__all__ = ['create_access_token', 'create_refresh_token', 'get_async_db', 'get_current_user_id', 'get_current_user_id_strict', 'get_current_user_strict', 'get_user_identity', 'is_token_revoked', 'require_permission', 'require_superuser', 'revoke_token']


def get_user_identity(user: User) -> tuple[str, str]:
    """从User对象提取(session_id, username)，用于审计和暂存区"""
    return str(user.id), user.username


def _get_user_id_from_jwt(request: Request) -> int | None:
    """
    尝试从 Authorization: Bearer <token> 中获取用户ID。
    如果没有Bearer Token或解码失败，返回None（不抛异常，降级到cookie方式）。
    成功解码时将 payload 暂存到 request.state._jwt_payload（L1 优化：避免同请求重复解码）。
    """
    auth_header = request.headers.get('authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    token = auth_header[7:]
    if not token:
        return None
    try:
        payload = _decode_jwt_token(token, expected_type='access')
        request.state._jwt_payload = payload
        user_id = payload.get('sub')
        if user_id:
            return int(user_id)
    except (HTTPException, ValueError):
        pass  # defensive: 异常静默处理,不影响主流程
    return None

def _get_user_id_from_cookie(request: Request) -> int | None:
    """
    从 httpOnly cookie 中获取当前登录用户 ID（cookie-based JWT）。

    浏览器登录后，FastAPI 在 httpOnly cookie 中设置 JWT token，
    此函数解码该 cookie 中的 JWT 获取用户信息。
    成功解码时同样暂存 payload（L1 优化）。
    """
    cookie_token = request.cookies.get('access_token')
    if not cookie_token:
        return None
    try:
        payload = _decode_jwt_token(cookie_token, expected_type='access')
        request.state._jwt_payload = payload
        user_id = payload.get('sub')
        if user_id:
            return int(user_id)
    except (HTTPException, ValueError):
        pass  # defensive: 异常静默处理,不影响主流程
    return None

def _resolve_user_id(request: Request) -> int | None:
    """从 JWT Bearer 或 Cookie JWT 中提取用户ID（纯内存操作，无DB查询）"""
    user_id = _get_user_id_from_jwt(request)
    if user_id is None:
        user_id = _get_user_id_from_cookie(request)
    return user_id


def _resolve_token_jti(request: Request) -> str | None:
    """从 JWT Bearer 或 Cookie JWT 中提取 jti（用于黑名单检查）"""
    auth_header = request.headers.get('authorization', '')
    bearer_token = auth_header[7:] if auth_header.startswith('Bearer ') else ''
    cookie_token = request.cookies.get('access_token', '')
    token = bearer_token or cookie_token
    if not token:
        return None
    try:
        payload = _decode_jwt_token(token, expected_type='access')
        return payload.get('jti')
    except HTTPException:
        return None
_USER_ACTIVE_CACHE = _TTLCache(ttl=10, maxsize=500)

async def _verify_user_active(user_id: int, db: AsyncSession) -> bool:
    """验证用户仍存在且处于启用状态（带 L1 缓存，TTL 10s）"""
    cached = await _USER_ACTIVE_CACHE.get(user_id)
    if cached is not None:
        return cached  # type: ignore[return-value]
    result = await db.execute(select(User.id, User.status).where(User.id == user_id))
    user = result.first()
    is_active = user is not None and bool(user.status)
    await _USER_ACTIVE_CACHE.set(user_id, is_active)
    return is_active

async def _authenticate_user_id(request: Request, db: AsyncSession, *, fail_closed: bool = False) -> int:
    """认证并返回当前用户ID，get_current_user_id / get_current_user_id_strict 的内部实现

    校验 token 类型必须为 access，用户仍存在且处于启用状态，token 未被撤销（黑名单）。
    fail_closed=True 时，黑名单校验在 Redis 故障且本地缓存未命中的情况下拒绝请求。
    """
    cached_payload = getattr(request.state, '_jwt_payload', None)
    if cached_payload is not None:
        user_id = cached_payload.get('sub')
        if user_id:
            return int(user_id)

    user_id = _resolve_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='未登录')

    # L1 优化：_resolve_user_id 已成功解码并暂存 payload，此处直接复用，
    # 不再对同一 token 做第二次/第三次解码（原实现每请求最多解码 3 次）。
    payload = getattr(request.state, '_jwt_payload', None)
    if payload is not None:
        jti = payload.get('jti')
    else:
        # 罕见边界（如 state 被中间件重置）：退回独立解析
        jti = _resolve_token_jti(request)

    if await is_token_revoked(jti, fail_closed=fail_closed):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Token已失效')

    if not await _verify_user_active(user_id, db):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='用户不存在或已被禁用')
    return user_id


async def get_current_user_id(request: Request, db: AsyncSession=Depends(get_async_db)) -> int:
    """
    获取当前用户ID（双认证模式）。

    优先级：
    1. Authorization: Bearer <token>（JWT方式，适用于API客户端）
    2. httpOnly cookie 中的 access_token（浏览器Web端）

    验证 token 类型为 access、用户仍存在且处于启用状态、token 未被撤销（黑名单）。
    返回 user_id: int。
    """
    return await _authenticate_user_id(request, db)


async def get_current_user_id_strict(request: Request, db: AsyncSession=Depends(get_async_db)) -> int:
    """
    严格版 get_current_user_id：token 黑名单校验 fail-closed。

    Redis 故障且本地 LRU 缓存未命中时直接拒绝（401），供敏感端点使用，
    防止已撤销的 token 在 Redis 故障期间被放行。
    """
    return await _authenticate_user_id(request, db, fail_closed=True)

async def _load_user_with_permissions(user_id: int, db: AsyncSession) -> User:
    """按 user_id 查询用户并预加载权限列表（带 L1 缓存）"""
    cached_user = await _get_cached_user(user_id)
    if cached_user is not None:
        return cached_user
    result = await db.execute(select(User).options(joinedload(User.permissions).selectinload(Permission.children)).where(User.id == user_id))
    user = result.unique().scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='用户不存在')
    db.expunge(user)
    await _set_cached_user(user_id, user)
    return user

async def _get_user_with_permissions(request: Request, db: AsyncSession=Depends(get_async_db)) -> User:
    """
    解析认证信息并从数据库查询用户，同时预加载权限列表。

    使用 L1 进程内缓存（TTL 10s）避免每次请求都查询数据库。
    expunge 使 User 对象可在任何上下文安全使用。
    """
    user_id = await get_current_user_id(request, db)
    return await _load_user_with_permissions(user_id, db)


async def get_current_user_strict(request: Request, db: AsyncSession=Depends(get_async_db)) -> User:
    """
    严格版认证依赖：返回当前用户（含权限），token 黑名单校验 fail-closed。

    Redis 故障且本地 LRU 缓存未命中时直接拒绝（401），供敏感端点使用，
    防止已撤销的 token 在 Redis 故障期间被放行。
    """
    user_id = await get_current_user_id_strict(request, db)
    return await _load_user_with_permissions(user_id, db)

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


def require_any_permission(*permission_names: str):
    """
    权限检查依赖工厂：拥有其中任一权限即可放行。

    用于「同一批接口被多个页面共用、而各页面的导航权限码不同」的场景
    （如采购中心接口同时服务于「采购中心」「物料计算器」页面），
    避免管理员按导航勾选权限后接口仍返回 403。

    注意：调用时必须至少传一个权限码；若传了空集合，`any(())` 恒为 False，
    将拒绝所有非超管用户（fail-closed，视为误用而非放行）。

    用法：
        @router.get("/...")
        async def endpoint(user: User = Depends(require_any_permission("product_manage", "purchase_center_manage"))):
            ...
    """

    async def permission_checker(current_user: User=Depends(_get_user_with_permissions)) -> User:
        if not any(current_user.has_permission(name) for name in permission_names):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='权限不足')
        return current_user
    return permission_checker


def require_superuser(permission_name: str = 'user_manage'):
    """
    超级用户权限检查依赖工厂。

    先验证权限，再验证 is_super，消除端点中重复的 if not user.is_super 检查。

    用法：
        @router.get("/list")
        async def list_users(user: User = Depends(require_superuser()), db: AsyncSession = ...):
            ...
    """

    async def superuser_checker(current_user: User=Depends(require_permission(permission_name))) -> User:
        if not current_user.is_super:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='仅超级用户可访问')
        return current_user
    return superuser_checker


async def get_current_user_with_permissions(
    user: User = Depends(_get_user_with_permissions),
) -> User:
    """公开别名。

    `_get_user_with_permissions` 是本模块私有依赖；端点需要「当前用户 + 已加载权限」
    时通过本别名依赖，避免跨模块导入私有名字。FastAPI 会缓存依赖，与
    `resolve_production_*_scope` 同时使用时不会重复查库。
    """
    return user


async def resolve_production_view_scope(
    user: User = Depends(_get_user_with_permissions),
) -> set[str] | None:
    """生产报表可见部门范围。

    Returns:
        None 表示全部部门；否则为可见部门集合。

    Raises:
        HTTPException: 403 —— 用户在生产报表上没有任何可见部门。
            空集绝不允许退化为「不过滤」，否则未授权用户会看到全部数据。
    """
    from fastapi_app.core.production_scope import production_scope_of

    scope = production_scope_of(user, write=False)
    if scope is not None and not scope:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='权限不足')
    return scope


async def resolve_production_write_scope(
    user: User = Depends(_get_user_with_permissions),
) -> set[str] | None:
    """生产报表可写部门范围（语义同上，但只认 manage 码）。"""
    from fastapi_app.core.production_scope import production_scope_of

    scope = production_scope_of(user, write=True)
    if scope is not None and not scope:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='权限不足')
    return scope
