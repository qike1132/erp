"""备份记录与状态。"""
from __future__ import annotations

import io
import json
import logging
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._constants import (
    _MAX_PRE_RESTORE_BACKUPS,
    BACKUP_DIR,
    BACKUP_MAX_COUNT,
    BACKUP_RETENTION_DAYS,
    PRE_RESTORE_DIR,
)
from .crypto import sha256_bytes
from .exceptions import BackupFileError

logger = logging.getLogger(__name__)


def ensure_backup_dir():  # log-context: internal helper 无请求上下文
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def ensure_pre_restore_dir():  # log-context: internal helper 无请求上下文
    """确保恢复前安全备份目录存在"""
    PRE_RESTORE_DIR.mkdir(parents=True, exist_ok=True)


async def write_backup_record(
    db: AsyncSession,
    *,
    record_type: str,
    trigger_type: str = 'manual',
    filename: str | None = None,
    size: int | None = None,
    table_count: int | None = None,
    total_rows: int | None = None,
    operator: str | None = None,
    remark: str | None = None,
    status: str = 'success',
    error_message: str | None = None,
    duration_seconds: float | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    parent_record_id: int | None = None,
    manifest_summary: dict | None = None,
    schedule_id: int | None = None,
    encrypted: bool | None = None,
) -> None:
    """写入备份操作记录到 BackupRecord 表"""
    try:
        from fastapi_app.shared_models.backup_record import BackupRecord
        record = BackupRecord(
            type=record_type, trigger_type=trigger_type, filename=filename,
            size=size, table_count=table_count, total_rows=total_rows,
            operator=operator, remark=remark, status=status,
            error_message=error_message, duration_seconds=duration_seconds,
            ip_address=ip_address, user_agent=user_agent,
            parent_record_id=parent_record_id,
            manifest_summary=manifest_summary,
            schedule_id=schedule_id,
            encrypted=encrypted,
        )
        db.add(record)
        await db.flush()
    except (SQLAlchemyError, OSError) as e:
        logger.warning(f'写入备份记录失败（不阻塞主流程）: {e}')


def list_backup_files() -> list[dict]:  # log-context: internal helper 无请求上下文
    """列出服务器上的所有备份文件"""
    backups = []
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not f.is_file():
                continue
            if not ((f.name.startswith('erp_backup_') or f.name.startswith('erp_incremental_') or f.name.startswith('erp_auto_'))
                    and (f.name.endswith('.zip') or f.name.endswith('.json'))):
                continue
            entry: dict = {'filename': f.name, 'size': f.stat().st_size}
            if f.name.endswith('.zip'):
                try:
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            manifest = json.loads(zf.read('manifest.json'))
                            entry.update({
                                'format': manifest.get('type', 'zip'),
                                'exported_at': manifest.get('exported_at', ''),
                                'exported_by': manifest.get('exported_by', ''),
                                'remark': manifest.get('remark', ''),
                                'table_count': manifest.get('table_count', 0),
                                'total_rows': manifest.get('total_rows', 0),
                                'includes': manifest.get('includes', {}),
                                'base_timestamp': manifest.get('base_timestamp', ''),
                                'encrypted': manifest.get('encrypted', False),
                            })
                except (OSError, zipfile.BadZipFile, ValueError) as e:
                    logger.warning(f'读取 ZIP 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            elif f.name.endswith('.json'):
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    entry.update({
                        'format': 'json',
                        'exported_at': data.get('exported_at', ''),
                        'exported_by': data.get('exported_by', ''),
                        'remark': data.get('remark', ''),
                        'table_count': len(data.get('tables', {})),
                        'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in data.get('tables', {}).values()),
                    })
                except (OSError, json.JSONDecodeError, ValueError) as e:
                    logger.warning(f'读取 JSON 备份 {f.name} 失败: {e}')
                    entry['error'] = str(e)
            backups.append(entry)
    return backups


def get_backup_status() -> dict:  # log-context: internal helper 无请求上下文
    """获取备份系统状态概览"""
    from .verify import get_checksum_tables
    last_full: dict | None = None
    total_backups = 0
    total_size = 0
    if BACKUP_DIR.exists():
        # 按 mtime 取最近：文件名字典序会把 m5_fix_verify_* 等演练件排在
        # erp_backup_* 手动件之前，导致"上次备份"选中错误文件
        backup_files = sorted(
            (f for f in BACKUP_DIR.iterdir()
             if f.is_file() and (f.name.endswith('.zip') or f.name.endswith('.json'))),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for f in backup_files:
            total_backups += 1
            total_size += f.stat().st_size
            if last_full:
                continue
            try:
                if f.name.endswith('.zip'):
                    with zipfile.ZipFile(f, 'r') as zf:
                        if 'manifest.json' in zf.namelist():
                            mf = json.loads(zf.read('manifest.json'))
                            if mf.get('type') == 'full':
                                last_full = {
                                    'filename': f.name, 'size': f.stat().st_size,
                                    'created_at': datetime.fromtimestamp(
                                        f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                                    'exported_at': mf.get('exported_at', ''),
                                    'exported_by': mf.get('exported_by', ''),
                                    'remark': mf.get('remark', ''), 'type': 'full',
                                    'table_count': mf.get('table_count', 0),
                                    'total_rows': mf.get('total_rows', 0),
                                }
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warning(f'解析备份清单失败: {e}')
                continue
    try:
        du = shutil.disk_usage(str(BACKUP_DIR))
        disk_usage_percent = round(du.used / du.total * 100, 1)
    except OSError:
        disk_usage_percent = None
    return {
        'success': True, 'backup_dir': str(BACKUP_DIR),
        'total_backups': total_backups, 'total_size_bytes': total_size,
        'last_full_backup': last_full,
        'disk_usage_percent': disk_usage_percent,
        'checksum_tables': sorted(get_checksum_tables()),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def validate_backup_file(content: bytes, filename: str) -> dict:  # log-context: internal helper 无请求上下文
    """验证备份文件，不执行恢复，仅返回摘要信息"""
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if is_zip:
        try:
            zf = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            raise BackupFileError('无效的 ZIP 文件') from None
        if 'manifest.json' not in zf.namelist():
            raise BackupFileError('ZIP 备份缺少 manifest.json')
        manifest = json.loads(zf.read('manifest.json'))
        names = zf.namelist()
        checksums_ok = True
        checksum_errors = []
        stored_checksums = manifest.get('checksums', {})
        for db_file in ['database/dump.sql.gz', 'database/dump.json']:
            if stored_checksums.get(db_file):
                actual = sha256_bytes(zf.read(db_file))  # REV-14
                if actual != stored_checksums[db_file]:
                    checksums_ok = False
                    checksum_errors.append(f'{db_file} 校验和不匹配')
        return {
            'format': 'zip', 'version': manifest.get('version'),
            'exported_at': manifest.get('exported_at'),
            'exported_by': manifest.get('exported_by'),
            'remark': manifest.get('remark', ''),
            'table_count': manifest.get('table_count'),
            'total_rows': manifest.get('total_rows'),
            'includes': manifest.get('includes', {}),
            'checksums_ok': checksums_ok, 'checksum_errors': checksum_errors,
            'zip_contents': {
                'has_database': 'database/dump.sql.gz' in names or 'database/dump.json' in names,
                'db_format': 'sql' if 'database/dump.sql.gz' in names else 'json' if 'database/dump.json' in names else 'none',
                'has_filestore': any(n.startswith('filestore/') for n in names),
                'has_config': any(n.startswith('config/') for n in names),
                'has_redis': 'redis/dump.rdb' in names,
                'has_meilisearch': any(n.startswith('meilisearch/') for n in names),
                'filestore_count': sum(1 for n in names if n.startswith('filestore/') and not n.endswith('/')),
                'config_files': [n for n in names if n.startswith('config/') and not n.endswith('/')],
            },
        }
    # JSON format
    try:
        backup_data = json.loads(content)
    except json.JSONDecodeError:
        raise BackupFileError('备份文件格式无效（非 ZIP 亦非有效 JSON）') from None
    if 'tables' not in backup_data:
        raise BackupFileError('JSON 备份文件缺少 tables 字段')
    from fastapi_app.shared_models import Base
    existing_tables = {str(t.name) for t in Base.metadata.sorted_tables}
    summary = {
        'format': 'json', 'version': backup_data.get('version'),
        'exported_at': backup_data.get('exported_at'),
        'exported_by': backup_data.get('exported_by'),
        'remark': backup_data.get('remark', ''),
        'table_count': len(backup_data['tables']),
        'total_rows': sum(t.get('count', len(t.get('rows', []))) for t in backup_data['tables'].values()),
        'checksums_ok': None, 'tables': [],
    }
    for table_name, table_data in backup_data['tables'].items():
        row_count = table_data.get('count', len(table_data.get('rows', [])))
        summary['tables'].append({
            'name': table_name, 'rows': row_count,
            'exists': table_name in existing_tables,
            'has_error': 'error' in table_data,
        })
    return summary


def delete_backup_file(filename: str) -> str:  # log-context: internal helper 无请求上下文
    """删除服务器上的指定备份文件"""
    safe_name = Path(filename).name
    if safe_name != filename:
        raise BackupFileError('无效的文件名')
    filepath = BACKUP_DIR / safe_name
    if not filepath.exists():
        raise BackupFileError('备份文件不存在')
    try:
        filepath.unlink()
    except (OSError, ValueError) as e:
        raise BackupFileError(f'删除备份文件失败: {e}') from e
    return safe_name


def cleanup_pre_restore_backups():  # log-context: internal helper 无请求上下文
    """清理旧的恢复前安全备份（保留最近 5 个）"""
    if not PRE_RESTORE_DIR.exists():
        return
    backups = sorted(
        [f for f in PRE_RESTORE_DIR.iterdir() if f.is_file() and f.name.startswith('pre_restore_') and f.name.endswith('.zip')],
        key=lambda f: f.name, reverse=True
    )
    for old_backup in backups[_MAX_PRE_RESTORE_BACKUPS:]:
        try:
            old_backup.unlink()
            logger.info(f'已清理旧安全备份: {old_backup.name}')
        except OSError as e:
            logger.warning(f'清理旧安全备份失败: {old_backup.name}: {e}')


def _backup_created_time(f: Path) -> datetime:  # log-context: internal helper 无请求上下文
    """获取备份文件的真实创建时间。

    优先读取伴随的 ``.meta`` 文件中的 ``created_at``（加密备份的 mtime 可能被刷新，
    导致按文件系统 mtime 判定保留期不准）；无 meta 时回退到文件系统 mtime。
    """
    meta_path = f.parent / (f.name + '.meta')
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            created_at = meta.get('created_at')
            if created_at:
                return datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass  # defensive: 异常静默处理,不影响主流程
    return datetime.fromtimestamp(f.stat().st_mtime)


def cleanup_old_backups() -> dict:  # log-context: internal helper 无请求上下文
    """清理过期备份文件

    策略：
    1. 删除超过 BACKUP_RETENTION_DAYS 天的备份
    2. 如果总数超过 BACKUP_MAX_COUNT，删除最旧的
    3. 增量备份依赖其基础全量备份，删除全量备份时级联删除依赖它的增量备份

    Returns: dict with deleted_count, kept_count, errors
    """
    if not BACKUP_DIR.exists():
        return {'deleted_count': 0, 'kept_count': 0, 'errors': []}

    now = datetime.now()
    cutoff = now - timedelta(days=BACKUP_RETENTION_DAYS)
    deleted = []
    errors = []

    # 收集所有备份文件及其元数据
    backups = []
    for f in BACKUP_DIR.iterdir():
        if not f.is_file():
            continue
        if not ((f.name.startswith('erp_backup_') or f.name.startswith('erp_auto_') or f.name.startswith('erp_incremental_'))
                and (f.name.endswith('.zip') or f.name.endswith('.json') or f.name.endswith('.zip.enc'))):
            continue
        mtime = _backup_created_time(f)
        size = f.stat().st_size
        is_incremental = 'incremental' in f.name
        base_timestamp = None

        # 读取增量备份的基础时间戳
        if is_incremental and f.name.endswith('.zip'):
            try:
                with zipfile.ZipFile(f, 'r') as zf:
                    if 'manifest.json' in zf.namelist():
                        manifest = json.loads(zf.read('manifest.json'))
                        base_timestamp = manifest.get('base_timestamp')
            except (OSError, zipfile.BadZipFile, ValueError):
                pass  # defensive: 异常静默处理,不影响主流程

        backups.append({
            'path': f, 'name': f.name, 'mtime': mtime, 'size': size,
            'is_incremental': is_incremental, 'base_timestamp': base_timestamp,
        })

    # 按时间排序（最新的在前）
    backups.sort(key=lambda b: b['mtime'], reverse=True)

    # 标记需要删除的文件
    to_delete = set()

    # 策略1: 删除超过保留天数的
    for b in backups:
        if b['mtime'] < cutoff:
            to_delete.add(b['name'])

    # 策略2: 超过最大数量的
    if len(backups) - len(to_delete) > BACKUP_MAX_COUNT:
        # 从最旧的开始删除
        for b in reversed(backups):
            if b['name'] in to_delete:
                continue
            if len(backups) - len(to_delete) <= BACKUP_MAX_COUNT:
                break
            to_delete.add(b['name'])

    # 策略3: 级联删除 - 删除全量备份时，删除依赖它的增量备份
    full_backup_timestamps = set()
    for b in backups:
        if not b['is_incremental'] and b['name'] not in to_delete:
            # 提取全量备份的时间戳
            try:
                ts_str = b['name'].replace('erp_backup_', '').replace('erp_auto_daily_', '').replace('.zip', '').replace('.json', '').replace('.enc', '')
                full_backup_timestamps.add(ts_str)
            except (ValueError, IndexError):
                pass  # defensive: 异常静默处理,不影响主流程

    # 检查增量备份的基础全量备份是否还在
    for b in backups:
        if b['is_incremental'] and b['base_timestamp']:
            # 如果基础全量备份被删除，增量备份也应该删除
            base_exists = any(ts for ts in full_backup_timestamps if ts <= b['base_timestamp'])
            if not base_exists:
                to_delete.add(b['name'])

    # 执行删除
    for name in to_delete:
        filepath = BACKUP_DIR / name
        try:
            filepath.unlink()
            deleted.append(name)
            logger.info(f'已清理过期备份: {name}')
        except OSError as e:
            errors.append(f'{name}: {e}')
            logger.warning(f'清理备份失败: {name}: {e}')

    return {
        'deleted_count': len(deleted),
        'kept_count': len(backups) - len(deleted),
        'deleted_files': deleted,
        'errors': errors,
    }
