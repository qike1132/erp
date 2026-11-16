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

# P2（2026-10-24）：ZIP 成员解压上限。恢复侧原先直接 zf.read(name) 把整个成员读进内存，
# 只有成员名做了穿越校验；构造一个高压缩比成员（几 KB 压成几 GB）即可让 API 进程 OOM。
# 单成员 512MB 上限，超限跳过该成员并记入 errors。
_MAX_MEMBER_BYTES = 512 * 1024 * 1024


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
            # P2：先按 ZIP 目录里的未压缩大小判上限，再解压（防高压缩比 OOM）
            _info = zf.getinfo(name)
            if _info.file_size > _MAX_MEMBER_BYTES:
                errors.append(f'{rel_path}: 成员过大（{_info.file_size} B），已跳过')
                continue
            target.write_bytes(zf.read(name))
            restored += 1
        except (OSError, ValueError, KeyError) as e:
            errors.append(f'{rel_path}: {e}')
    return {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}


#: 组件包（config/ 与 root/ 命名空间）**不允许**还原的路径特征。
#:
#: 为什么（2026-11-16 上线前审计 A-55）：``root/`` 前缀直接映射到 PROJECT_ROOT，
#: 而成员名是上传者可控的。没有这条白名单，一个组件包就能覆写工作区里的源码/脚本，
#: 下次重启即变成代码执行。超管本来就等于主机运维（他已能还原 .env 与现役私钥），
#: 所以这不是提权，但「恢复配置」没有任何理由具备改源码的能力。
_FORBIDDEN_RESTORE_SUFFIXES = (
    '.py', '.pyc', '.pyo', '.ps1', '.bat', '.cmd', '.sh', '.exe', '.dll', '.msi', '.vbs',
)
_FORBIDDEN_RESTORE_DIRS = (
    'fastapi_app/', 'frontend-vite/src/', 'server_manager/', 'migrations/',
    '.githooks/', 'scripts/', 'tests/', 'utils/',
    # .git/ 必须在列：hooks/* 是无扩展名的可执行脚本，后缀白名单拦不住；
    # 覆写 .git/hooks/pre-commit 等价于下次提交即执行（评审 F12）。
    '.git/', '.gitmodules', '.gitignore', '.gitattributes',
)


def _reject_non_config_member(rel_path: str) -> str | None:
    """返回拒绝原因；None 表示允许还原。"""
    lowered = rel_path.replace('\\', '/').lower()
    if lowered.endswith(_FORBIDDEN_RESTORE_SUFFIXES):
        return f'{rel_path}: 源码/可执行文件不在恢复范围，已跳过'
    if any(lowered.startswith(seg) or f'/{seg}' in lowered for seg in _FORBIDDEN_RESTORE_DIRS):
        return f'{rel_path}: 源码目录不在恢复范围，已跳过'
    return None


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
        non_config_reason = _reject_non_config_member(rel_path)
        if non_config_reason:
            errors.append(non_config_reason)
            logger.warning('跳过非配置成员恢复: %s', non_config_reason)
            continue
        target = root / rel_path
        try:
            target.resolve().relative_to(root.resolve())
        except ValueError:
            errors.append(f'{rel_path}: 路径越界，已跳过')
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # P2：同 _restore_filestore，先判未压缩大小再解压
            _info = zf.getinfo(name)
            if _info.file_size > _MAX_MEMBER_BYTES:
                errors.append(f'{rel_path}: 成员过大（{_info.file_size} B），已跳过')
                continue
            target.write_bytes(zf.read(name))
            restored.append(rel_path)
        except (OSError, ValueError, KeyError) as e:
            errors.append(f'{rel_path}: {e}')
    result = {'status': 'ok' if not errors else 'partial', 'restored': restored, 'errors': errors}
    if skipped_sensitive:
        result['skipped_sensitive'] = skipped_sensitive
        result['status'] = 'partial'
    return result
