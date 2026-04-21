"""密码哈希与验证工具

使用 bcrypt 作为主哈希方案，兼容旧 werkzeug pbkdf2/scrypt 哈希。
旧格式哈希验证成功后，调用方可通过 needs_rehash() 检测并触发自动迁移。
"""

import logging

import bcrypt as _bcrypt

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码

    bcrypt 自动处理 salt 生成，rounds=12 提供 ~250ms 延迟（兼顾安全与性能）。
    """
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode("utf-8")


def needs_rehash(password_hash: str) -> bool:
    """检查哈希是否需要升级到 bcrypt（用于旧 werkzeug 哈希自动迁移）"""
    return not password_hash.startswith(("$2b$", "$2a$", "$2y$"))


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码

    支持 bcrypt 哈希（$2b$/$2a$/$2y$）和旧 werkzeug 哈希（pbkdf2/scrypt）。
    旧格式哈希验证成功后，调用方应通过 needs_rehash() 检测并触发自动迁移。

    注意: werkzeug 的 scrypt/pbkdf2 哈希使用自定义 ab64 编码，
    直接用 base64 解码会失败，因此回退到 werkzeug.check_password_hash。
    """
    # bcrypt 哈希（当前格式）
    if password_hash.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            return _bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
        except Exception:
            return False

    # werkzeug 哈希（旧格式，使用 werkzeug 原生验证以保证兼容性）
    if password_hash.startswith(("pbkdf2:", "scrypt:")):
        try:
            from werkzeug.security import check_password_hash
            result = check_password_hash(password_hash, password)
            if result:
                logger.info("werkzeug 哈希验证成功，建议迁移到 bcrypt")
            return result
        except Exception:
            return False

    return False
