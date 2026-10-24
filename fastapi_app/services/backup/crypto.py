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


def resolve_encryption_decision(
    encrypt: bool | None,
    explicit_password: str | None = None,
    *,
    degrade_when_missing: bool,
) -> tuple[bool, str | None]:
    """备份加密唯一决策点（Z05-R5）。

    总开关 ``BACKUP_ENCRYPTION_ENABLED=false`` 时一律不加密（忽略调用方 encrypt）。

    - ``encrypt=False`` → 不加密；
    - ``encrypt=True`` 且有密码 → 加密；
    - ``encrypt=True`` 但无密码：
        - ``degrade_when_missing=True``（手动端点/任务）→ 降级明文并告警；
        - ``False``（服务层全量备份）→ 抛 BackupError（宁可失败不可产出打不开的包）；
    - ``encrypt=None``（服务层默认）且加密已启用但无密码 → fail-closed 抛错；
    - ``encrypt=None`` 且开关关闭 → 明文。

    Returns:
        ``(是否实际加密, 使用的密码)``。
    """
    if not is_encryption_enabled():
        if encrypt:
            logger.warning(
                'BACKUP_ENCRYPTION_ENABLED=false，已忽略 encrypt=True 请求，本次不加密'
            )
        return False, None
    if encrypt is False:
        return False, None

    effective = explicit_password or get_backup_encryption_password()
    if effective:
        return True, effective
    if encrypt is None:
        from .exceptions import BackupError
        raise BackupError(
            '备份加密已启用（BACKUP_ENCRYPTION_ENABLED=true）但未配置可用的 '
            'BACKUP_ENCRYPTION_PASSWORD / BACKUP_ENCRYPTION_KEY，拒绝产出不加密备份'
        )
    if degrade_when_missing:
        logger.warning(
            '请求加密备份但未配置密码（参数/请求头/环境变量均无），本次降级为不加密'
        )
        return False, None
    from .exceptions import BackupError
    raise BackupError(
        '请求加密全量备份但未配置密码（encrypt_password 参数 / '
        'BACKUP_ENCRYPTION_PASSWORD 环境变量均未提供）'
    )


def is_encryption_enabled() -> bool:
    """备份加密是否已启用。

    供调用方在「无密码需降级为明文」前判断：若已启用加密却拿不到密码，
    应 fail-closed（拒绝产出不加密备份），而非静默降级（AGENTS.md 红线#4）。
    """
    return bool(BACKUP_ENCRYPTION_ENABLED)


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

    # B2-10（2026-10-24 审计）：原文案「备份将不加密」与唯一决策点
    # resolve_encryption_decision 的 fail-closed 行为矛盾（该请求随后即抛
    # BackupError），排障会被引向错误方向。
    logger.warning("备份加密已启用但未配置加密密码，降级/失败由 resolve_encryption_decision 决定")
    return None
