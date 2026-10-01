"""文件存储恢复。"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from ._constants import (
    _EXCLUDE_FILES,
    _SENSITIVE_AND_EXCLUDED_FILES,
    _SENSITIVE_CONFIG_FILES,
    CONFIG_DIR,
    PROJECT_ROOT,
    UPLOADS_DIR,
)

logger = logging.getLogger(__name__)


def _path_variants(archive_path: str) -> tuple[str, ...]:
    """同一份配置的两种写法：归档名（带 config/ 或 root/ 命名空间）与 config 内相对名。

    P0-2：归档名改为清单自带命名空间后，敏感/排除白名单（历史条目都是 config 内
    相对名，如 '.env'、'jwt/private.pem'）必须两种写法都认，否则闸门会静默失效。
    """
    normalized = archive_path.replace('\\', '/')
    for prefix in ('config/', 'root/'):
        if normalized.startswith(prefix):
            stripped = normalized[len(prefix):]
            return (normalized, stripped) if stripped else (normalized,)
    return (normalized, f'config/{normalized}')


def should_exclude_file(file_path, relative_path: str, include_sensitive: bool = False) -> bool:
    """检查文件是否应该被排除在备份之外

    Args:
        file_path: 文件的完整路径
        relative_path: 相对于配置目录或上传目录的相对路径
        include_sensitive: 本次备份是否加密。加密备份才打包敏感配置
            （jwt 私钥 / .env.production）——密钥随包分发，必须与备份加密绑定；
            明文备份仍排除，避免私钥以明文形式落盘。
            注意 BACKUP_EXCLUDE_FILES 的显式排除项始终生效，不受此开关影响。

    Returns:
        True 如果文件应该被排除，否则 False
    """
    variants = _path_variants(relative_path)

    # BACKUP_EXCLUDE_FILES 显式排除项：任何情况下都不打包
    if any(v in _EXCLUDE_FILES for v in variants):
        logger.debug(f"排除显式配置项: {relative_path}")
        return True

    # 敏感配置文件：仅加密备份打包（明文包排除，防私钥明文泄露）
    # include_sensitive 由「本次是否加密」决定（见 core.pack_config_files）
    if any(v in _SENSITIVE_CONFIG_FILES for v in variants) and not include_sensitive:
        logger.info(f"明文备份排除敏感文件: {relative_path}")
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
        pass  # defensive: 异常静默处理,不影响主流程

    return False


def restore_filestore(zf: zipfile.ZipFile) -> dict:  # log-context: internal helper 无请求上下文
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


def _restore_roots() -> tuple[tuple[str, Path], ...]:
    """归档命名空间 → 还原目标根（调用时求值，便于测试重定向）。

    `config/` 落回 CONFIG_DIR；`root/` 落回 PROJECT_ROOT —— 运行时 `.env` 归档为
    `root/.env`（H-3，2026-09-29），它不属于 config/ 目录。

    旧包兼容（P0-2）：P0-2 之前 core.py 无条件拼 'config/'，运行时 .env 在包内是
    `config/root/.env`。若按 `config/` 前缀还原，它会写成 CONFIG_DIR/root/.env
    幽灵目录、真正的项目根 .env 永不还原。故把更长前缀 `config/root/` 排在首位
    （下面用首个匹配前缀）。
    """
    return (('config/root/', PROJECT_ROOT), ('config/', CONFIG_DIR), ('root/', PROJECT_ROOT))


def restore_config(zf: zipfile.ZipFile, confirm_sensitive: bool = False) -> dict:  # log-context: internal helper 无请求上下文
    """恢复配置文件（REV-09: 敏感文件白名单校验 + 命名空间隔离）"""
    restored = []
    errors = []
    skipped_sensitive = []
    roots = _restore_roots()
    for name in zf.namelist():
        if name.endswith('/'):
            continue
        matched = next(((pfx, root) for pfx, root in roots if name.startswith(pfx)), None)
        if matched is None:
            continue
        prefix, root = matched
        rel_path = name[len(prefix):]
        if '..' in rel_path or rel_path.startswith('/') or rel_path.startswith('\\'):
            errors.append(f'{rel_path}: 路径不安全，已跳过')
            continue
        # REV-09: 敏感文件恢复需二次确认
        if rel_path in _SENSITIVE_AND_EXCLUDED_FILES and not confirm_sensitive:
            skipped_sensitive.append(rel_path)
            logger.warning(f"跳过敏感文件恢复（需要确认）: {rel_path}")
            continue
        target = root / rel_path
        try:
            target.resolve().relative_to(root.resolve())
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
