"""文件存储恢复。"""
from __future__ import annotations

import logging
import zipfile

from ._constants import (
    CONFIG_DIR,
    UPLOADS_DIR,
    _SENSITIVE_AND_EXCLUDED_FILES,
)

logger = logging.getLogger(__name__)


def should_exclude_file(file_path, relative_path: str) -> bool:
    """检查文件是否应该被排除在备份之外

    Args:
        file_path: 文件的完整路径
        relative_path: 相对于配置目录或上传目录的相对路径

    Returns:
        True 如果文件应该被排除，否则 False
    """
    # 检查是否为敏感配置文件
    if relative_path in _SENSITIVE_AND_EXCLUDED_FILES:
        logger.debug(f"排除敏感/排除文件: {relative_path}")
        return True

    # 检查文件扩展名是否在排除列表中
    excluded_extensions = {'.log', '.tmp', '.temp', '.cache', '.swp', '.swo'}
    if file_path.suffix.lower() in excluded_extensions:
        logger.debug(f"排除临时文件: {relative_path}")
        return True

    # 检查文件大小（可选，排除过大文件）
    max_file_size = 100 * 1024 * 1024  # 100MB
    try:
        if file_path.stat().st_size > max_file_size:
            logger.warning(f"文件过大，跳过备份: {relative_path} ({file_path.stat().st_size} bytes)")
            return True
    except OSError:
        pass

    return False


def restore_filestore(zf: zipfile.ZipFile) -> dict:
    """恢复附件文件到 static/uploads/"""
    restored = 0
    errors = []
    for name in zf.namelist():
        if not name.startswith('filestore/') or name.endswith('/'):
            continue
        rel_path = name[len('filestore/'):]
        if '..' in rel_path or rel_path.startswith('/') or rel_path.startswith('\\'):
            errors.append(f'{rel_path}: 路径不安全，已跳过')
            continue
        target = UPLOADS_DIR / rel_path
        try:
            target.resolve().relative_to(UPLOADS_DIR.resolve())
        except ValueError:
            errors.append(f'{rel_path}: 路径越界，已跳过')
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            restored += 1
        except (OSError, ValueError) as e:
            errors.append(f'{rel_path}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}


def restore_config(zf: zipfile.ZipFile, confirm_sensitive: bool = False) -> dict:
    """恢复配置文件到 config/ 目录（REV-09: 敏感文件白名单校验）"""
    restored = []
    errors = []
    skipped_sensitive = []
    for name in zf.namelist():
        if not name.startswith('config/') or name.endswith('/'):
            continue
        rel_path = name[len('config/'):]
        if '..' in rel_path or rel_path.startswith('/') or rel_path.startswith('\\'):
            errors.append(f'{rel_path}: 路径不安全，已跳过')
            continue
        # REV-09: 敏感文件恢复需二次确认
        if rel_path in _SENSITIVE_AND_EXCLUDED_FILES and not confirm_sensitive:
            skipped_sensitive.append(rel_path)
            logger.warning(f"跳过敏感文件恢复（需要确认）: {rel_path}")
            continue
        target = CONFIG_DIR / rel_path
        try:
            target.resolve().relative_to(CONFIG_DIR.resolve())
        except ValueError:
            errors.append(f'{rel_path}: 路径越界，已跳过')
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))
            restored.append(rel_path)
        except (OSError, ValueError) as e:
            errors.append(f'{rel_path}: {e}')
    result = {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}
    if skipped_sensitive:
        result['skipped_sensitive'] = skipped_sensitive
        result['status'] = 'partial'
    return result