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


def get_backup_encryption_password() -> str | None:  # log-context: internal helper 无请求上下文
    """获取备份加密密码（仅环境变量链，P0-1 起不再生成随机密钥）

    优先级：
    1. BACKUP_ENCRYPTION_PASSWORD 环境变量
    2. BACKUP_ENCRYPTION_KEY 环境变量
    3. 返回 None（由调用方决定降级为不加密或显式报错）

    历史:曾支持 FALLBACK_TO_GENERATED 随机密钥回退,但随机密钥只输出预览+摘要、
    无人能找回完整值,等价于把备份销毁。P0-1(2026-08-23) 移除该分支;
    FALLBACK_TO_GENERATED 显式设 true 时仅记录告警,不再生效。
    """
    if BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED:
        logger.warning(
            "BACKUP_ENCRYPTION_FALLBACK_TO_GENERATED 已被弃用并忽略：随机密钥无法找回，"
            "请配置 BACKUP_ENCRYPTION_PASSWORD 或接受不加密备份"
        )

    if not BACKUP_ENCRYPTION_ENABLED:
        return None

    if BACKUP_ENCRYPTION_PASSWORD:
        logger.info("使用环境变量 BACKUP_ENCRYPTION_PASSWORD 进行备份加密")
        return BACKUP_ENCRYPTION_PASSWORD

    if BACKUP_ENCRYPTION_KEY:
        logger.info("使用环境变量 BACKUP_ENCRYPTION_KEY 进行备份加密")
        return BACKUP_ENCRYPTION_KEY

    logger.warning("备份加密已启用但未配置加密密码，备份将不加密")
    return None
