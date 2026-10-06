"""还原差异预览服务（M3）。

读目标备份的 manifest（行数指纹），与当前库实时 COUNT(*) 比对，
输出表级差异与影响汇总 —— 即原型「还原向导第 2 步」的数据源。
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.backup._constants import BACKUP_DIR
from fastapi_app.services.backup.verify.core import quote_table

logger = logging.getLogger(__name__)


class EncryptedBackupError(ValueError):
    """备份已加密且本次未带（或带错）密码。

    单独成类是为了让调用方能把它与「文件缺失/损坏」区分开：加密备份缺密码**不是**
    失败终局，前端据此仍要渲染密码输入框并允许提交 —— 否则加密备份在界面上无路可走。
    """


def _manifest_from_zip_bytes(data: bytes, filename: str) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(data), 'r') as zf:
            if 'manifest.json' not in zf.namelist():
                raise ValueError(f'备份 {filename} 缺少 manifest.json')
            return json.loads(zf.read('manifest.json'))
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f'备份文件 {filename} 读取失败: {e}') from e


def read_manifest_from_backup(
    filename: str, base_dir: Path | None = None, *, password: str | None = None,
) -> dict:
    """读取指定备份文件的 manifest.json。

    加密备份（`.enc`）无密码时抛 `EncryptedBackupError`；给了密码则先解密再读，
    这样向导第 2 步的差异预览对加密备份同样可用。文件名须为备份目录内合法文件。
    """
    base = base_dir or BACKUP_DIR
    path = base / Path(filename).name  # 防路径穿越:仅取 basename
    if not path.is_file():
        raise FileNotFoundError(f'备份文件不存在: {filename}')
    if path.suffix.endswith('.enc'):
        if not password:
            raise EncryptedBackupError(
            '该备份已加密，且服务端未配置解密密码（BACKUP_ENCRYPTION_PASSWORD），请联系管理员'
        )
        from fastapi_app.core.backup_encryption import decrypt_backup_auto

        try:
            # 用 auto 而非 decrypt_backup：它同时认 chunked-v1 / meta 前缀 / 旧裸信封，
            # 与还原链路的读取口径一致，避免「能还原却预览不了」的口径分叉
            decrypted = decrypt_backup_auto(path.read_bytes(), password)[0]
        except Exception as e:  # broad-except: 解密实现抛错类型不定，统一转成可展示的 ValueError
            raise ValueError(f'解密失败，请确认密码是否正确: {e}') from e
        return _manifest_from_zip_bytes(decrypted, filename)
    try:
        with zipfile.ZipFile(path, 'r') as zf:
            if 'manifest.json' not in zf.namelist():
                raise ValueError(f'备份 {filename} 缺少 manifest.json')
            return json.loads(zf.read('manifest.json'))
    except (zipfile.BadZipFile, OSError, ValueError) as e:
        if isinstance(e, ValueError):
            raise
        raise ValueError(f'备份文件 {filename} 读取失败: {e}') from e


async def build_restore_plan(db: AsyncSession, manifest: dict) -> dict:
    """差异预览：manifest 表级行数 vs 当前库实时 COUNT(*)。

    仅做只读探测。diff = 当前行数 - 备份行数；差异非 0 的表进入 affected 清单。
    """
    tables: dict[str, dict] = manifest.get('tables', {}) or {}
    table_diffs: list[dict] = []
    affected: list[dict] = []
    total_backup_rows = 0
    for tname, info in sorted(tables.items()):
        rows = (info or {}).get('rows', -1)
        if rows is not None and rows >= 0:
            total_backup_rows += rows
        try:
            qt = quote_table(tname)  # value cached; REV-08
            result = await db.execute(text(f'SELECT COUNT(*) FROM {qt}'))  # nosec B608 — qt 经 quote_table 白名单校验
            cur = result.scalar() or 0
        except ValueError as e:  # 表名白名单外
            cur = -1
            logger.warning(f'还原预览: 忽略不合法表名 {tname!r}: {e}')
        except Exception as e:  # broad-except: 还原预览为只读尽力统计，单表失败仅记 -1，不阻断整体预览
            cur = -1
            logger.warning(f'还原预览: 统计表 {tname} 失败: {e}')

        diff = None
        if rows is not None and rows >= 0 and cur >= 0:
            diff = cur - rows
        table_diffs.append({
            'table': tname, 'backup_rows': rows, 'current_rows': cur, 'diff': diff,
        })
        if diff not in (None, 0):
            affected.append({'table': tname, 'diff': diff})

    return {
        'table_count': len(tables),
        'total_backup_rows': total_backup_rows,
        'affected_tables': affected,
        'affected_count': len(affected),
        'tables': table_diffs,
        'encrypted': bool(manifest.get('encrypted')),
        'exported_at': manifest.get('exported_at'),
    }
