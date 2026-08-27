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
from .crypto import sha256_bytes, sha256_file
from .exceptions import BackupFileError

logger = logging.getLogger(__name__)

# 模块级记录写入失败计数器（P1+P2）：每累计 3 次失败发送一次告警，避免告警风暴
_record_write_fail_count: int = 0

# 正式备份文件命名约定：m5_fix_verify_*/erp_m3drill_* 等演练/测试件不计入统计与列表
_BACKUP_NAME_PREFIXES = ('erp_backup_', 'erp_incremental_', 'erp_auto_')
_BACKUP_FILE_SUFFIXES = ('.zip', '.json', '.zip.enc')


def _is_backup_file(f: Path) -> bool:  # log-context: internal helper 无请求上下文
    """是否为正式备份文件(按命名约定排除演练/测试临时件)"""
    return (
        f.is_file()
        and f.name.startswith(_BACKUP_NAME_PREFIXES)
        and f.name.endswith(_BACKUP_FILE_SUFFIXES)
    )


def ensure_backup_dir():  # log-context: internal helper 无请求上下文
    """确保备份目录存在"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def ensure_pre_restore_dir():  # log-context: internal helper 无请求上下文
    """确保恢复前安全备份目录存在"""
    PRE_RESTORE_DIR.mkdir(parents=True, exist_ok=True)


def write_backup_meta_file(filepath, manifest: dict, *, record_type: str = 'full'):  # log-context: internal helper 无请求上下文
    """为备份文件写入 .meta sidecar（P0-4 落地）。

    - created_at 与 _backup_created_time 的读取约定对齐（'%Y-%m-%d %H:%M:%S'），
      文件被复制/移动后保留策略不再依赖不可靠的 mtime；
    - 加密备份（.zip.enc）无法直接读 manifest，列表/状态展示依赖本 sidecar；
    - 写入失败仅告警，不阻塞备份主流程。
    """
    try:
        from fastapi_app.core.backup_encryption import create_meta_file
        fp = Path(filepath)
        meta = {
            'created_at': manifest.get('exported_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'filename': fp.name,
            'size': fp.stat().st_size,
            'type': manifest.get('type', record_type),
            'encrypted': bool(manifest.get('encrypted', False)),
            'format_version': manifest.get('version'),
            'table_count': manifest.get('table_count'),
            'total_rows': manifest.get('total_rows'),
            'exported_by': manifest.get('exported_by'),
            'remark': manifest.get('remark', ''),
            'checksum': sha256_file(fp),
        }
        meta_path = fp.parent / (fp.name + '.meta')
        meta_path.write_bytes(create_meta_file(meta))
        return meta_path
    except (OSError, ValueError, AttributeError, TypeError) as e:
        logger.warning(f'写入备份 .meta 失败（不阻塞主流程）: {e}')
        return None


def _read_backup_meta(f: Path) -> dict | None:  # log-context: internal helper 无请求上下文
    """读取备份文件的 .meta sidecar，不存在或损坏时返回 None。"""
    meta_path = f.parent / (f.name + '.meta')
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


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
        global _record_write_fail_count
        _record_write_fail_count += 1
        logger.warning(f'写入备份记录失败（不阻塞主流程）: {e}')
        # 每累计3次失败发送一次告警，避免告警风暴
        if _record_write_fail_count % 3 == 0:
            try:
                import asyncio
                from fastapi_app.services.backup.metrics.alert_service import alert_service
                # 尝试获取事件循环，有则发送告警，无则跳过（同步上下文无法 await）
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop:
                    loop.create_task(alert_service.send_alert(
                        task_name='backup_record_write',
                        error=f'备份记录写入已连续失败 {_record_write_fail_count} 次: {e}',
                        task_type='backup',
                        severity='error',
                    ))
            except Exception:
                pass  # 告警失败不影响主流程


def list_backup_files() -> list[dict]:  # log-context: internal helper 无请求上下文
    """列出服务器上的所有备份文件"""
    backups = []
    if BACKUP_DIR.exists():
        for f in sorted(BACKUP_DIR.iterdir(), reverse=True):
            if not _is_backup_file(f):
                continue
            # H1 修复：统一补 name/mtime——validation.py 4 处调用点读取
            # x.get('name')/x.get('mtime')，旧实现缺这两个键导致健康检查
            # "最近备份时间"恒为 1970、完整性抽样全部误报、/stats 数据全错
            st = f.stat()
            entry: dict = {
                'filename': f.name,
                'name': f.name,
                'size': st.st_size,
                'mtime': st.st_mtime,
            }
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
            elif f.name.endswith('.zip.enc'):
                # 加密备份无法直接读 manifest，展示信息来自 .meta sidecar（P0-4）
                entry.update({'format': 'zip', 'encrypted': True})
                if meta := _read_backup_meta(f):
                    entry.update({
                        'type': meta.get('type', 'full'),
                        'exported_at': meta.get('created_at', ''),
                        'exported_by': meta.get('exported_by', ''),
                        'remark': meta.get('remark', ''),
                        'table_count': meta.get('table_count', 0),
                        'total_rows': meta.get('total_rows', 0),
                    })
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
        # 按 mtime 取最近：文件名字典序会把 erp_auto_* 排到 erp_backup_* 之前，
        # 导致"上次备份"选中错误文件；同时只统计正式备份件，演练件不计入
        backup_files = sorted(
            (f for f in BACKUP_DIR.iterdir() if _is_backup_file(f)),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        for f in backup_files:
            total_backups += 1
            total_size += f.stat().st_size
            if last_full:
                continue
            try:
                if f.name.endswith('.zip.enc'):
                    # 加密备份从 .meta sidecar 取类型与时间（P0-4）
                    meta = _read_backup_meta(f) or {}
                    if meta.get('type') == 'full' or (not meta and f.name.startswith('erp_backup_')):
                        last_full = {
                            'filename': f.name, 'size': f.stat().st_size,
                            'created_at': meta.get('created_at', ''),
                            'exported_at': meta.get('created_at', ''),
                            'exported_by': meta.get('exported_by', ''),
                            'remark': meta.get('remark', ''), 'type': 'full',
                            'table_count': meta.get('table_count', 0),
                            'total_rows': meta.get('total_rows', 0),
                            'encrypted': True,
                        }
                elif f.name.endswith('.zip'):
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
    # 同步清理 .meta sidecar（P0-4），残留无害但会干扰列表/保留策略展示
    meta_path = BACKUP_DIR / (safe_name + '.meta')
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError as e:
            logger.warning(f'清理 .meta 失败: {meta_path.name}: {e}')
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
            meta_path = BACKUP_DIR / (name + '.meta')
            if meta_path.exists():
                meta_path.unlink()
        except OSError as e:
            errors.append(f'{name}: {e}')
            logger.warning(f'清理备份失败: {name}: {e}')

    return {
        'deleted_count': len(deleted),
        'kept_count': len(backups) - len(deleted),
        'deleted_files': deleted,
        'errors': errors,
    }


async def sync_backup_records() -> dict:
    """启动时同步文件系统与数据库备份记录（双向）。

    - 补录：文件存在但 DB 无记录 → 根据 manifest/.meta 补写 BackupRecord
    - 清理孤立：DB 有记录但文件不存在 → 删除记录
    - 修正僵尸：status='running' 但文件已存在且进程已结束 → 更新为 'success'

    幂等保证：多次运行结果一致（已存在的记录跳过，已删除的孤立不再出现，
    已修正的僵尸状态不再为 running）。

    Returns:
        dict: {'backfilled': N, 'orphaned': N, 'zombie_fixed': N, 'errors': [...]}
    """
    # 延迟导入避免循环依赖
    from fastapi_app.core.database import get_async_db_context
    from fastapi_app.shared_models.backup_record import BackupRecord
    from sqlalchemy import select, delete as sa_delete
    from fastapi_app.services.backup.verify.query_service import (
        _infer_type_from_filename,
        _infer_trigger_type_from_filename,
        _parse_exported_at,
        _parse_timestamp_from_filename,
    )

    result: dict = {'backfilled': 0, 'orphaned': 0, 'zombie_fixed': 0, 'errors': []}

    # 1. 扫描文件系统所有备份文件
    try:
        fs_files = list_backup_files()
    except Exception as e:  # defensive: 文件系统扫描失败不阻塞同步
        result['errors'].append(f'list_backup_files 失败: {e}')
        return result

    fs_filenames = {f['filename'] for f in fs_files if f.get('filename')}

    # 2. 自建数据库会话执行双向同步
    try:
        async with get_async_db_context() as db:
            # 查询所有 BackupRecord，构建 filename → record 映射
            try:
                rows = (await db.execute(select(BackupRecord))).scalars().all()
            except Exception as e:
                result['errors'].append(f'查询 BackupRecord 失败: {e}')
                return result

            record_by_filename: dict[str, object] = {}
            for r in rows:
                if r.filename:
                    record_by_filename[r.filename] = r

            # 2a. 补录：文件存在但 DB 无记录
            for fs_entry in fs_files:
                fname = fs_entry.get('filename')
                if not fname or fname in record_by_filename:
                    continue
                try:
                    # 推断备份类型：优先用 .meta 中的 type，其次文件名推断
                    record_type = fs_entry.get('type') or _infer_type_from_filename(fname)
                    trigger_type = _infer_trigger_type_from_filename(fname)
                    # 解析创建时间：优先 exported_at，其次文件名时间戳
                    created_at = _parse_exported_at(fs_entry.get('exported_at'))
                    if created_at is None:
                        created_at = _parse_timestamp_from_filename(fname)
                    record = BackupRecord(
                        type=record_type,
                        trigger_type=trigger_type,
                        filename=fname,
                        size=fs_entry.get('size'),
                        table_count=fs_entry.get('table_count'),
                        total_rows=fs_entry.get('total_rows'),
                        operator=fs_entry.get('exported_by') or 'system_sync',
                        remark=fs_entry.get('remark', ''),
                        status='success',
                        encrypted=fs_entry.get('encrypted', False),
                        created_at=created_at,
                    )
                    db.add(record)
                    await db.flush()
                    await db.commit()  # 每条补录成功后立即提交，避免后续失败回滚已成功记录
                    result['backfilled'] += 1
                except Exception as e:
                    result['errors'].append(f'补录 {fname} 失败: {e}')
                    try:
                        await db.rollback()
                    except Exception:
                        pass  # defensive: rollback 失败不阻塞后续同步

            # 2b. 清理孤立：DB 有记录但文件不存在
            for r in rows:
                if r.filename and r.filename not in fs_filenames:
                    try:
                        await db.execute(sa_delete(BackupRecord).where(BackupRecord.id == r.id))
                        await db.commit()  # 每条删除成功后立即提交，避免后续失败回滚已成功记录
                        result['orphaned'] += 1
                    except Exception as e:
                        result['errors'].append(f'清理孤立记录 {r.filename} 失败: {e}')
                        try:
                            await db.rollback()
                        except Exception:
                            pass  # defensive: rollback 失败不阻塞后续同步

            # 2c. 修正僵尸：status='running' 且对应文件存在 → 更新为 'success'
            #     （进程已结束，文件已落盘，running 状态为历史中断残留）
            for r in rows:
                if r.status == 'running' and r.filename and r.filename in fs_filenames:
                    try:
                        r.status = 'success'
                        await db.flush()
                        await db.commit()  # 每条修正成功后立即提交，避免后续失败回滚已成功记录
                        result['zombie_fixed'] += 1
                    except Exception as e:
                        result['errors'].append(f'修正僵尸记录 {r.filename} 失败: {e}')
                        try:
                            await db.rollback()
                        except Exception:
                            pass  # defensive: rollback 失败不阻塞后续同步
    except Exception as e:
        result['errors'].append(f'同步过程异常: {e}')

    return result
