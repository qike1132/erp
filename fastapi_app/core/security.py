"""密码哈希与验证工具

使用 Argon2id 作为唯一哈希方案（OWASP 2026 推荐）。
支持旧格式哈希的向后兼容验证（bcrypt/pbkdf2/scrypt）。
"""

import hashlib
import hmac
import logging

import argon2

from fastapi_app.core.metrics import _get_or_create_counter

_argon2_hasher = argon2.PasswordHasher(
    type=argon2.Type.ID,
    memory_cost=19456,
    time_cost=2,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

logger = logging.getLogger(__name__)

_BCRYPT_MISSING_COUNTER = ("password_bcrypt_missing_total",
                           "登录时遇到 bcrypt 哈希但 bcrypt 库未安装的次数")


def _bcrypt_missing_counter():
    return _get_or_create_counter(*_BCRYPT_MISSING_COUNTER)


_MAX_PASSWORD_LENGTH = 1024


def hash_password(password: str) -> str:
    """使用 Argon2id 哈希密码

    Argon2id 是 OWASP 2026 推荐的密码哈希算法，
    内存硬特性使其对 GPU/ASIC 暴力破解具有更强抵抗力。
    """
    if len(password) > _MAX_PASSWORD_LENGTH:
        raise ValueError(f"密码长度不能超过 {_MAX_PASSWORD_LENGTH} 个字符")
    return _argon2_hasher.hash(password)


def _verify_bcrypt(password: str, password_hash: str) -> bool:
    """验证 bcrypt 哈希密码"""
    try:
        import bcrypt
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except ImportError:
        # N3 评审（2026-10-11）：缺 bcrypt 时旧哈希用户登录静默失败（返回 False
        # 而非 5xx），运维无从发现。加 metric + error 级日志使故障可观测。
        _bcrypt_missing_counter().inc()
        logger.error("bcrypt 未安装：旧格式（$2b$/$2a$/$2y$）密码哈希无法验证，"
                     "相关用户登录将持续失败。请安装：pip install -r requirements/base.txt")
        return False
    except (ValueError, TypeError) as e:
        logger.debug(f"bcrypt 验证失败: {e}")
        return False


def _verify_legacy_pbkdf2(password: str, password_hash: str) -> bool:
    try:
        method, salt, expected = password_hash.split("$", 2)
        _, digest_name, iterations_text = method.split(":", 2)
        iterations = int(iterations_text)
        if iterations > 1_000_000:
            logger.warning("pbkdf2 iterations 超过上限，拒绝验证: %d", iterations)
            return False
        derived = hashlib.pbkdf2_hmac(
            digest_name,
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        ).hex()
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError) as e:
        logger.debug("pbkdf2 验证失败: %s", e)
        return False


_MAX_SCRYPT_MAXMEM = 256 * 1024 * 1024


def _verify_legacy_scrypt(password: str, password_hash: str) -> bool:
    try:
        method, salt, expected = password_hash.split("$", 2)
        _, n_text, r_text, p_text = method.split(":", 3)
        n = int(n_text)
        r = int(r_text)
        p = int(p_text)
        required_mem = 128 * n * r * p * 2
        if required_mem > _MAX_SCRYPT_MAXMEM:
            logger.warning("scrypt maxmem 超过上限，拒绝验证: n=%d r=%d p=%d", n, r, p)
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=n,
            r=r,
            p=p,
            maxmem=max(0, required_mem),
        ).hex()
        return hmac.compare_digest(derived, expected)
    except (ValueError, TypeError) as e:
        logger.debug("scrypt 验证失败: %s", e)
        return False


def _verify_werkzeug(password: str, password_hash: str) -> bool:
    """验证旧 werkzeug pbkdf2/scrypt 哈希密码"""
    if password_hash.startswith("pbkdf2:"):
        return _verify_legacy_pbkdf2(password, password_hash)
    if password_hash.startswith("scrypt:"):
        return _verify_legacy_scrypt(password, password_hash)
    return False


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码哈希（支持多种格式）

    支持的哈希格式：
    - Argon2id: $argon2id$...
    - bcrypt: $2b$, $2a$, $2y$
    - pbkdf2: pbkdf2:...（向后兼容）
    - scrypt: scrypt:...（向后兼容）

    返回：
        bool: 验证成功返回 True，失败返回 False
    """
    if not password_hash:
        return False
    if len(password) > _MAX_PASSWORD_LENGTH:
        return False

    if password_hash.startswith("$argon2id$"):
        try:
            return _argon2_hasher.verify(password_hash, password)
        except argon2.exceptions.VerifyMismatchError:
            return False
        except argon2.exceptions.VerificationError:
            return False
        except argon2.exceptions.InvalidHashError:
            logger.warning("Argon2 哈希格式无效")
            return False

    if password_hash.startswith(("$2b$", "$2a$", "$2y$")):
        return _verify_bcrypt(password, password_hash)

    if password_hash.startswith(("pbkdf2:", "scrypt:")):
        return _verify_werkzeug(password, password_hash)

    logger.warning("未知的密码哈希格式 (前缀不匹配已知算法)")
    return False


def check_needs_rehash(password_hash: str) -> bool:
    """检查 Argon2 哈希是否因参数变更需要重新哈希"""
    if not password_hash or not password_hash.startswith("$argon2id$"):
        return False
    try:
        return _argon2_hasher.check_needs_rehash(password_hash)
    except argon2.exceptions.InvalidHashError:
        return True


def needs_migration(password_hash: str) -> bool:
    """检查密码哈希是否需要迁移到 Argon2id"""
    if not password_hash:
        return False
    return not password_hash.startswith("$argon2id$")
