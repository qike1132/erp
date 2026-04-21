"""
安全加固模块 v2.0
整改: Argon2id 密码哈希 + Cookie 安全配置
"""
import os
from datetime import datetime, timedelta
from typing import Optional
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

# Argon2id 配置（OWASP 2026 推荐）
ph = PasswordHasher(
    time_cost=3,      # 迭代次数
    memory_cost=65536,  # 64MB
    parallelism=4,    # 并行度
    hash_len=32,      # 哈希长度
    salt_len=16,      # 盐长度
)

ENV = os.getenv("ENV", "development")

# Cookie 安全配置
cookie_config = {
    "key": "access_token",
    "httponly": True,
    "secure": ENV == "production",  # 生产环境必须 HTTPS
    "samesite": "none" if ENV == "production" else "lax",  # 跨域需要 'none'
    "max_age": 3600 * 24,  # 24 小时
}


def hash_password(password: str) -> str:
    """
    使用 Argon2id 哈希密码
    
    Args:
        password: 明文密码
        
    Returns:
        哈希后的密码字符串
    """
    return ph.hash(password)


def verify_password(password: str, hash: str) -> bool:
    """
    验证密码
    
    Args:
        password: 明文密码
        hash: 哈希后的密码
        
    Returns:
        验证是否通过
    """
    try:
        ph.verify(hash, password)
        return True
    except VerifyMismatchError:
        return False


def check_password_needs_rehash(hash: str) -> bool:
    """
    检查密码是否需要重新哈希（参数升级时）
    
    Args:
        hash: 哈希后的密码
        
    Returns:
        是否需要重新哈希
    """
    return ph.check_needs_rehash(hash)


def set_auth_cookie(response, token: str):
    """
    设置认证 Cookie（支持跨域）
    
    Args:
        response: FastAPI Response 对象
        token: JWT token
    """
    response.set_cookie(
        value=token,
        **cookie_config
    )


def clear_auth_cookie(response):
    """
    清除认证 Cookie
    
    Args:
        response: FastAPI Response 对象
    """
    response.delete_cookie(
        key=cookie_config["key"],
        httponly=cookie_config["httponly"],
        secure=cookie_config["secure"],
        samesite=cookie_config["samesite"],
    )


# 兼容旧 bcrypt 密码（迁移期间使用）
def verify_legacy_password(password: str, bcrypt_hash: str) -> bool:
    """
    验证旧 bcrypt 密码（迁移期间兼容）
    
    Args:
        password: 明文密码
        bcrypt_hash: bcrypt 哈希
        
    Returns:
        验证是否通过
    """
    try:
        from passlib.hash import bcrypt
        return bcrypt.verify(password, bcrypt_hash)
    except ImportError:
        return False
