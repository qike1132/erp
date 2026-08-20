"""认证业务逻辑服务

将 auth.py endpoint 中的登录核心业务逻辑（密码校验、哈希迁移、令牌生成）
下沉到此层，使 endpoint 只负责参数校验、限流、cookie 设置和响应构造。
"""
import asyncio
import logging
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from fastapi_app.core.config import settings
from fastapi_app.core.deps import create_access_token, create_refresh_token

logger = logging.getLogger(__name__)

_DUMMY_HASH = "$argon2id$v=19$m=19456,t=2,p=1$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


async def authenticate_login(
    db: AsyncSession, username: str, password: str, remember: bool, client_ip: str,
) -> dict:
    """验证用户登录凭据并生成 JWT 令牌。

    包含：用户查询、密码校验（含时序攻击防护）、哈希迁移/升级、令牌生成。

    Args:
        db: 异步数据库会话。
        username: 已清洗的用户名。
        password: 原始密码。
        remember: 是否记住我（影响令牌有效期）。
        client_ip: 客户端 IP（用于日志）。

    Returns:
        dict: 包含 access_token, refresh_token, token_max_age, refresh_max_age, user。

    Raises:
        HTTPException: 401 用户名或密码错误。
    """
    from fastapi_app.core.security import check_needs_rehash, hash_password, needs_migration, verify_password
    from fastapi_app.services import user_service

    user = await user_service.get_user_with_permissions_by_username(db, username)

    if not user:
        await run_in_threadpool(verify_password, "timing_sidechannel_dummy", _DUMMY_HASH)
        logger.warning("[Login] 登录失败: IP=%s", client_ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.status:
        await run_in_threadpool(verify_password, "timing_sidechannel_dummy", _DUMMY_HASH)
        logger.warning("[Login] 登录失败: IP=%s", client_ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not await run_in_threadpool(verify_password, password, user.password):
        logger.warning("[Login] 登录失败: IP=%s", client_ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if needs_migration(user.password):
        try:
            new_hash = await run_in_threadpool(hash_password, password)
            user.password = new_hash
            await db.commit()  # manual-tx: try/except 内显式事务控制
            logger.info(f"[Login] 密码哈希已迁移到 Argon2id: user_id={user.id}")
        except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
            logger.warning(f"[Login] 密码哈希迁移失败（不影响登录）: {e}")
            await db.rollback()  # manual-tx: try/except 内显式事务控制
    elif check_needs_rehash(user.password):
        try:
            new_hash = await run_in_threadpool(hash_password, password)
            user.password = new_hash
            await db.commit()  # manual-tx: try/except 内显式事务控制
            logger.info(f"[Login] 密码哈希参数已升级: user_id={user.id}")
        except (ValueError, TypeError, OSError, SQLAlchemyError) as e:
            logger.warning(f"[Login] 密码哈希升级失败（不影响登录）: {e}")
            await db.rollback()  # manual-tx: try/except 内显式事务控制

    # 生成JWT Token（仅存储最小必要信息，权限通过数据库实时查询）
    token_data = {
        "sub": str(user.id),
        "username": user.username,
    }

    # Cookie/JWT 有效期：记住我24小时，否则1小时
    token_max_age = 86400 if remember else 3600
    # RS256 签名是 CPU 密集的同步操作，放入线程池并行执行，避免阻塞事件循环
    # （一次登录生成 access+refresh 两个 token，若串行同步执行会卡住事件循环 ~500ms）
    access_token, refresh_token = await asyncio.gather(
        run_in_threadpool(
            create_access_token,
            token_data,
            expires_delta=timedelta(seconds=token_max_age),
        ),
        run_in_threadpool(create_refresh_token, token_data),
    )
    refresh_max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400

    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_max_age': token_max_age,
        'refresh_max_age': refresh_max_age,
        'user': user,
    }
