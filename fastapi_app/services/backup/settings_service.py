"""备份系统设置服务:backup_settings 读写 + 自定义路径预校验。

M1 新增模块(services/backup/settings_service.py):
- 读写 backup_settings 单行配置(备份路径/保留策略/加密模式)
- validate_path:绝对路径、盘符白名单、无 `..`、目录可写探测、
  psutil.disk_usage 空间 ≥ 阈值、系统目录黑名单

配置优先级(向后兼容):backup_settings 表 > 环境变量(_constants.BACKUP_DIR)。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import psutil  # 磁盘空间预检(模块级导入,便于测试 patch)

from ._constants import BACKUP_DIR

logger = logging.getLogger(__name__)

# 单行配置主键
_SETTINGS_ID = 1

# 盘符白名单(Windows 环境;Linux 下为根路径)
_ALLOWED_DRIVES = ('C:', 'D:', 'E:', 'F:')

# 系统目录黑名单:禁止将备份路径指向系统/程序关键目录
_BLACKLIST_SUBSTR = (
    '\\windows\\',
    '\\system32\\',
    '\\program files',
    '\\programdata\\',
    '\\appdata\\',
    '\\users\\public\\',
)

# 空间阈值:备份目录所在盘剩余空间需 ≥ 此值(GB)
_MIN_FREE_GB = 5.0

# 路径合法性:Windows 绝对路径 C:\... 或 UNC;Linux 绝对路径 /...
_WINDOWS_PATH_RE = re.compile(r'^[A-Za-z]:[\\/]')
_UNC_PATH_RE = re.compile(r'^\\\\')
_UNIX_PATH_RE = re.compile(r'^/')
# 非法字符(Windows 保留字符;冒号仅允许作为盘符分隔,由 _INVALID_COLON_RE 单独校验)
_ILLEGAL_CHARS = set('<>"|?*')
# 非法冒号:路径中出现冒号但非盘符形式(如 C:foo / D:\x:y)
_INVALID_COLON_RE = re.compile(r':(?![\\/])')


class BackupSettingsError(ValueError):
    """备份设置校验/读写错误。"""


def _resolve_backup_dir_from_settings(db: AsyncSession, settings_row) -> Path:
    """按优先级解析当前生效的备份目录:
    1. backup_settings 表已初始化(存在路径)→ 表值
    2. 否则回退到环境变量/默认值(_constants.BACKUP_DIR)
    """
    if settings_row is not None and settings_row.backup_dir:
        return Path(settings_row.backup_dir)
    return BACKUP_DIR


async def get_settings(db: AsyncSession) -> dict:
    """读取备份系统设置(单行)。表未初始化时回退环境变量默认值。"""
    from fastapi_app.shared_models.backup_settings import BackupSettings

    row = (
        await db.execute(
            select(BackupSettings).where(BackupSettings.id == _SETTINGS_ID)
        )
    ).scalar_one_or_none()

    if row is None:
        return {
            'backup_dir': str(BACKUP_DIR),
            'default_backup_dir': str(BACKUP_DIR),
            'retention_days': 30,
            'max_count': 50,
            'encryption_mode': 'env',
            'initialized': False,
        }

    return {
        'backup_dir': row.backup_dir,
        'default_backup_dir': str(BACKUP_DIR),
        'retention_days': row.retention_days,
        'max_count': row.max_count,
        'encryption_mode': row.encryption_mode,
        'updated_by': row.updated_by,
        'updated_at': row.updated_at.isoformat() if row.updated_at else None,
        'initialized': True,
    }


async def save_settings(
    db: AsyncSession,
    *,
    backup_dir: str | None = None,
    retention_days: int | None = None,
    max_count: int | None = None,
    encryption_mode: str | None = None,
    operator: str | None = None,
) -> dict:
    """保存备份系统设置(单行 upsert)。backup_dir 变更前必须已通过 validate_path。"""
    from fastapi_app.shared_models.backup_settings import BackupSettings

    row = (
        await db.execute(
            select(BackupSettings).where(BackupSettings.id == _SETTINGS_ID)
        )
    ).scalar_one_or_none()

    if row is None:
        row = BackupSettings(id=_SETTINGS_ID, backup_dir=str(BACKUP_DIR))
        db.add(row)

    if backup_dir is not None:
        if not backup_dir.strip():
            # 空字符串表示恢复默认系统路径
            row.backup_dir = str(BACKUP_DIR)
        else:
            # 写入前兜底校验(防御:调用方应已在前端/端点层校验)
            validation = validate_path(backup_dir)
            if not validation['valid']:
                raise BackupSettingsError(validation['error'])
            row.backup_dir = backup_dir
    if retention_days is not None:
        if retention_days < 1 or retention_days > 3650:
            raise BackupSettingsError('保留天数必须在 1-3650 之间')
        row.retention_days = retention_days
    if max_count is not None:
        if max_count < 1 or max_count > 10000:
            raise BackupSettingsError('最大备份数量必须在 1-10000 之间')
        row.max_count = max_count
    if encryption_mode is not None:
        if encryption_mode not in ('off', 'password', 'key', 'env'):
            raise BackupSettingsError('加密模式必须是 off/password/key/env 之一')
        row.encryption_mode = encryption_mode
    if operator:
        row.updated_by = operator

    await db.flush()
    return await get_settings(db)


def validate_path(path: str) -> dict:
    """预校验自定义备份路径,返回 {valid, error?}。

    校验项:
    1. 非空、绝对路径(Windows 盘符 / UNC / Unix 根路径)
    2. 不含 Windows 保留非法字符、不含路径穿越 `..`
    3. 不在系统目录黑名单
    4. 目录可写探测(不存在则检查最近存在的父目录)
    5. 磁盘剩余空间 ≥ 阈值(psutil.disk_usage)
    """
    if not path or not path.strip():
        return {'valid': False, 'error': '路径不能为空'}

    path = path.strip()

    # 绝对路径判断
    if not (_WINDOWS_PATH_RE.match(path) or _UNC_PATH_RE.match(path) or _UNIX_PATH_RE.match(path)):
        return {'valid': False, 'error': '必须是绝对路径(如 D:\\backups 或 /data/backups)'}

    # 非法字符
    illegal = sorted(_ILLEGAL_CHARS.intersection(path))
    if illegal:
        return {'valid': False, 'error': f'路径包含非法字符: {" ".join(illegal)}'}

    # 非法冒号:冒号后必须紧跟路径分隔符(盘符形式 C:\ 合法)
    if _INVALID_COLON_RE.search(path):
        return {'valid': False, 'error': '路径包含非法冒号(仅允许盘符形式如 D:\\ 或 D:/)'}

    # 路径穿越
    if '..' in path.split('\\') + path.split('/'):
        return {'valid': False, 'error': '路径不允许包含 ..(路径穿越)'}

    # 盘符白名单(Windows)
    if _WINDOWS_PATH_RE.match(path):
        drive = path[:2].upper()
        if drive not in _ALLOWED_DRIVES:
            return {'valid': False, 'error': f'盘符 {drive} 不在允许列表 {"/".join(_ALLOWED_DRIVES)} 中'}

    # 系统目录黑名单
    lower = path.lower()
    for banned in _BLACKLIST_SUBSTR:
        if banned in lower:
            return {'valid': False, 'error': f'不允许使用系统目录: {banned.strip(chr(92)).strip()}'}

    # 目录可写探测:向上找最近存在的父目录
    p = Path(path)
    probe = p
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    if not probe.exists():
        return {'valid': False, 'error': f'路径的上级目录不存在: {probe}'}
    if not probe.is_dir():
        return {'valid': False, 'error': f'路径的上级目录不是目录: {probe}'}
    if not _is_writable(probe):
        return {'valid': False, 'error': f'目录不可写: {probe}'}

    # 空间预检
    try:
        usage = psutil.disk_usage(str(probe.anchor if _WINDOWS_PATH_RE.match(path) else probe))
    except (ImportError, OSError, ValueError) as e:
        logger.warning('磁盘空间预检失败(跳过): %s', e)
        usage = None
    if usage is not None and usage.free < _MIN_FREE_GB * 1024 ** 3:
        free_gb = usage.free / 1024 ** 3
        return {'valid': False, 'error': f'磁盘剩余空间不足: {free_gb:.1f} GB < 阈值 {_MIN_FREE_GB:.0f} GB'}

    return {'valid': True, 'path': path, 'message': '路径可写,空间充足'}


def _is_writable(directory: Path) -> bool:
    """探测目录可写性(尽力而为,失败不阻断)。"""
    import os
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(dir=str(directory), prefix='.bfp_write_test_', delete=True) as f:
            os.write(f.fileno(), b'ok')
        return True
    except (OSError, ValueError, RuntimeError):
        return False
