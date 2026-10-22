"""
JWT Token 编解码（core/deps 拆分子模块）

职责：access/refresh token 的签发与校验（HS256 / RS256 / ES256）。
不依赖认证请求上下文，纯 token 工具层。
"""
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import HTTPException, status

from fastapi_app.core.config import settings

_KEY_CACHE_TTL = 300  # 密钥轮换后最长 5 分钟生效，无需全量重启
_signing_key_cache: str | None = None
_verify_key_cache: str | None = None
_signing_key_cache_at = 0.0
_verify_key_cache_at = 0.0


def _get_signing_key() -> str:
    """获取 JWT 签名密钥（支持 HS256 / RS256 / ES256）"""
    global _signing_key_cache, _signing_key_cache_at
    if (
        _signing_key_cache is not None
        and time.monotonic() - _signing_key_cache_at < _KEY_CACHE_TTL
    ):
        return _signing_key_cache
    if settings.ALGORITHM in ("RS256", "ES256"):
        if not settings.JWT_PRIVATE_KEY_PATH:
            raise RuntimeError(f'{settings.ALGORITHM} 模式必须设置 JWT_PRIVATE_KEY_PATH 环境变量')
        with open(settings.JWT_PRIVATE_KEY_PATH) as f:
            _signing_key_cache = f.read()
            _signing_key_cache_at = time.monotonic()
            return _signing_key_cache
    _signing_key_cache = settings.SECRET_KEY
    _signing_key_cache_at = time.monotonic()
    return _signing_key_cache


def _get_verify_key() -> str:
    """获取 JWT 验证密钥（支持 HS256 / RS256 / ES256）"""
    global _verify_key_cache, _verify_key_cache_at
    if (
        _verify_key_cache is not None
        and time.monotonic() - _verify_key_cache_at < _KEY_CACHE_TTL
    ):
        return _verify_key_cache
    if settings.ALGORITHM in ("RS256", "ES256"):
        if not settings.JWT_PUBLIC_KEY_PATH:
            raise RuntimeError(f'{settings.ALGORITHM} 模式必须设置 JWT_PUBLIC_KEY_PATH 环境变量')
        with open(settings.JWT_PUBLIC_KEY_PATH) as f:
            _verify_key_cache = f.read()
            _verify_key_cache_at = time.monotonic()
            return _verify_key_cache
    _verify_key_cache = settings.SECRET_KEY
    _verify_key_cache_at = time.monotonic()
    return _verify_key_cache


def create_access_token(data: dict, expires_delta=None) -> str:
    """生成JWT Token（支持 HS256 / RS256）

    在 payload 中注入 jti（唯一标识），用于 token 撤销/黑名单。
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode['exp'] = expire
    to_encode['jti'] = uuid.uuid4().hex
    to_encode['type'] = 'access'
    return jwt.encode(to_encode, _get_signing_key(), algorithm=settings.ALGORITHM)


def create_refresh_token(data: dict, *, jti: str | None = None, expires_delta=None) -> str:
    """生成刷新令牌（有效期较长，仅用于获取新的 access token）

    刷新令牌不包含权限信息，仅包含用户标识。

    :param jti: 指定 jti。用于**轮换的幂等重放**：grace 窗口内并发使用同一个
        旧 refresh token 时（多标签页各自单飞），用同一个 jti 重新签发，
        使各标签页拿到等价凭据而不是被后到者踢成 401。
        默认 None = 随机生成，行为与改动前一致。
    :param expires_delta: 覆盖有效期，默认 ``REFRESH_TOKEN_EXPIRE_DAYS``。
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode['exp'] = expire
    to_encode['jti'] = jti or uuid.uuid4().hex
    to_encode['type'] = 'refresh'
    return jwt.encode(to_encode, _get_signing_key(), algorithm=settings.ALGORITHM)


def _decode_jwt_token(token: str, expected_type: str | None = None) -> dict:
    """解码并验证JWT Token，返回payload或抛出异常

    expected_type 不为 None 时额外校验 payload 的 type claim，
    防止 refresh token（长效）被当作 access token 用于请求认证，或反向混用。
    """
    try:
        payload = jwt.decode(token, _get_verify_key(), algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token已过期') from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token无效') from None
    if expected_type is not None and payload.get('type') != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='JWT Token类型错误')
    return payload
