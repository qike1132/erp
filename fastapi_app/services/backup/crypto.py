"""加密/解密/密钥工具函数。"""
from __future__ import annotations

import hashlib
import logging

from ._constants import (
    BACKUP_ENCRYPTION_ENABLED,
    BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED,
    BACKUP_ENCRYPTION_KEY,
    BACKUP_ENCRYPTION_PASSWORD,
)

logger = logging.getLogger(__name__)


def sha256_bytes(data: bytes) -> str:
    """计算 bytes 的 SHA256 十六进制摘要（REV-14: 替代 MD5）"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(filepath) -> str | None:
    """计算文件的 SHA256 十六进制摘要，文件不存在返回 None"""
    if not filepath.is_file():
        return None
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def generate_encryption_key() -> str:
    """生成随机加密密钥"""
    import secrets
    return secrets.token_urlsafe(32)


def get_backup_encryption_password() -> str | None:
    """获取备份加密密码

    优先级：
    1. BACKUP_ENCRYPTION_PASSWORD 环境变量
    2. BACKUP_ENCRYPTION_KEY 环境变量
    3. 如果 BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED 为 True，则生成随机密钥
    4. 返回 None（不加密）
    """
    if not BACKUP_ENCRYPTION_ENABLED:
        return None

    if BACKUP_ENCRYPTION_PASSWORD:
        logger.info("使用环境变量 BACKUP_ENCRYPTION_PASSWORD 进行备份加密")
        return BACKUP_ENCRYPTION_PASSWORD

    if BACKUP_ENCRYPTION_KEY:
        logger.info("使用环境变量 BACKUP_ENCRYPTION_KEY 进行备份加密")
        return BACKUP_ENCRYPTION_KEY

    if BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED:
        generated_key = generate_encryption_key()
        _key_preview = generated_key[:8] + "..." if len(generated_key) > 8 else "***"
        _key_digest = hashlib.sha256(generated_key.encode()).hexdigest()[:16]
        logger.warning("备份加密密钥已生成（预览: %s, 摘要: %s），请安全保存完整密钥用于恢复", _key_preview, _key_digest)
        logger.warning("建议设置 BACKUP_ENCRYPTION_PASSWORD 环境变量以使用固定密钥")
        return generated_key

    logger.warning("备份加密已启用但未配置加密密码，且不允许生成随机密钥，备份将不加密")
    return None