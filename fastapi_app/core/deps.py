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
import threading
import time
import uuid
from collections import OrderedDict
from datetime import UTC

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.core.config import settings
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


_PERMISSION_CACHE = _TTLCache(ttl=30, maxsize=500)

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

_signing_key_cache = None
_verify_key_cache = None

def _get_signing_key() -> str:
    """获取 JWT 签名密钥（支持 HS256 / RS256 / ES256）"""
    global _signing_key_cache
    if _signing_key_cache is not None:
        return _signing_key_cache
    if settings.ALGORITHM in ("RS256", "ES256"):
        if not settings.JWT_PRIVATE_KEY_PATH:
            raise RuntimeError(f'{settings.ALGORITHM} 模式必须设置 JWT_PRIVATE_KEY_PATH 环境变量')
        with open(settings.JWT_PRIVATE_KEY_PATH) as f:
            _signing_key_cache = f.read()
            return _signing_key_cache
    _signing_key_cache = settings.SECRET_KEY
    return _signing_key_cache

def _get_verify_key() -> str:
    """获取 JWT 验证密钥（支持 HS256 / RS256 / ES256）"""
    global _verify_key_cache
    if _verify_key_cache is not None:
        return _verify_key_cache
    if settings.ALGORITHM in ("RS256", "ES256"):
        if not settings.JWT_PUBLIC_KEY_PATH:
            raise RuntimeError(f'{settings.ALGORITHM} 模式必须设置 JWT_PUBLIC_KEY_PATH 环境变量')
        with open(settings.JWT_PUBLIC_KEY_PATH) as f:
            _verify_key_cache = f.read()
            return _verify_key_cache
    _verify_key_cache = settings.SECRET_KEY
    return _verify_key_cache

def create_access_token(data: dict, expires_delta=None) -> str:
    """生成JWT Token（支持 HS256 / RS256）

    在 payload 中注入 jti（唯一标识），用于 token 撤销/黑名单。
    """
    from datetime import datetime, timedelta

    import jwt
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode['exp'] = expire
    to_encode['jti'] = uuid.uuid4().hex
    to_encode['type'] = 'access'
    return jwt.encode(to_encode, _get_signing_key(), algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """生成刷新令牌（有效期较长，仅用于获取新的 access token）

    刷新令牌不包含权限信息，仅包含用户标识。
    """
    from datetime import datetime, timedelta

    import jwt
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode['exp'] = expire
    to_encode['jti'] = uuid.uuid4().hex
    to_encode['type'] = 'refresh'
    return jwt.encode(to_encode, _get_signing_key(), algorithm=settings.ALGORITHM)

def _decode_jwt_token(token: str, expected_type: str | None = None) -> dict:
    """解码并验证JWT Token，返回payload或抛出异常

    expected_type 不为 None 时额外校验 payload 的 type claim，
    防止 refresh token（长效）被当作 access token 用于请求认证，或反向混用。
    """
    import jwt
    try:
        payload = jwt.decode(token, _get_verify_key(), algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token已过期') from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token无效') from None
    if expected_type is not None and payload.get('type') != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token类型错误')
    return payload


class _LRUSet:
    """进程级 LRU 集合，用于 token 黑名单的本地降级缓存

    多 worker 间不共享，仅作为 Redis 故障时的降级方案。
    使用 threading.Lock 保护 OrderedDict 操作，确保多线程安全。
    """

    def __init__(self, maxsize: int = 1000):
        self._maxsize = maxsize
        self._data: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, key: str) -> None:
        with self._lock:
            self._data[key] = None
            self._data.move_to_end(key)
            if len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def contains(self, key: str) -> bool:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return True
            return False


_LOCAL_REVOKED_JTIS = _LRUSet(maxsize=1000)


async def revoke_token(jti: str, exp: int) -> None:
    """将 token 的 jti 加入 Redis 黑名单，TTL 设为 token 剩余有效期

    登出时调用，确保已签发的 token 无法继续使用。
    Redis 不可用时静默失败（token 仍会自然过期），但会同步写入本地 LRU 缓存作为降级。
    """
    from datetime import datetime
    remaining = max(exp - int(datetime.now(UTC).timestamp()), 0)
    if remaining <= 0:
        return
    # 始终写入本地 LRU 缓存（无论 Redis 是否可用），作为后续 Redis 故障时的降级依据
    _LOCAL_REVOKED_JTIS.add(jti)
    try:
        from fastapi_app.core.redis_wrapper import get_client
        redis = get_client()
        if redis:
            await redis.set(f"token_blacklist:{jti}", "1", ex=remaining)
    except Exception:  # defensive: Redis 故障时本地 LRU 缓存已写入，继续服务
        logger.debug("token 黑名单写入失败", exc_info=True)


# fail-open 降级 critical 日志的上次记录时间（monotonic），用于限频避免刷屏
_last_revocation_critical_at = 0.0
_REVOCATION_CRITICAL_INTERVAL = 60.0  # 限频时间窗（秒）


def _log_revocation_degraded(exc_info: bool = False) -> None:
    """Redis 黑名单校验降级（fail-open）时记录 critical 日志（60 秒时间窗限频）"""
    global _last_revocation_critical_at
    now = time.monotonic()
    if now - _last_revocation_critical_at < _REVOCATION_CRITICAL_INTERVAL:
        return
    _last_revocation_critical_at = now
    logger.critical(
        "Redis 黑名单校验不可用，token 撤销检查降级为本地缓存（fail-open），已撤销的 token 可能被放行",
        exc_info=exc_info,
    )


async def is_token_revoked(jti: str | None, *, fail_closed: bool = False) -> bool:
    """检查 token 是否已被撤销（在黑名单中）

    Redis 不可用时降级到本地 LRU 缓存：
    - 本地缓存命中则返回 True（已撤销）
    - 本地缓存未命中：
      - fail_closed=True（敏感端点）：抛出 401 拒绝请求（fail-closed）
      - fail_closed=False（默认）：返回 False 放行（fail-open），并记录限频 critical 日志
    本地缓存是进程级的，多 worker 间不共享，作为降级方案可接受。
    """
    if not jti:
        return False
    try:
        from fastapi_app.core.redis_wrapper import get_client
        redis = get_client()
        if redis:
            return bool(await redis.exists(f"token_blacklist:{jti}"))
        # Redis 客户端未初始化，降级到本地 LRU 缓存
        if _LOCAL_REVOKED_JTIS.contains(jti):
            return True
        if fail_closed:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='令牌状态校验不可用，请重新登录')
        _log_revocation_degraded()
        return False
    except HTTPException:
        raise
    except Exception:  # defensive: Redis 不可用时降级到本地 LRU 缓存
        # Redis 故障时降级到本地 LRU 缓存
        if _LOCAL_REVOKED_JTIS.contains(jti):
            return True
        if fail_closed:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='令牌状态校验不可用，请重新登录') from None
        _log_revocation_degraded(exc_info=True)
        return False

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
        payload = _decode_jwt_token(token, expected_type='access')
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
    """
    cookie_token = request.cookies.get('access_token')
    if not cookie_token:
        return None
    try:
        payload = _decode_jwt_token(cookie_token, expected_type='access')
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
    """验证用户仍存在且处于启用状态（带 L1 缓存，TTL 30s）"""
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

    token = request.headers.get('authorization', '')
    if token.startswith('Bearer '):
        token = token[7:]
    else:
        token = request.cookies.get('access_token', '')

    if token:
        try:
            payload = _decode_jwt_token(token, expected_type='access')
            request.state._jwt_payload = payload
            jti = payload.get('jti')
        except HTTPException:
            jti = _resolve_token_jti(request)
    else:
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
