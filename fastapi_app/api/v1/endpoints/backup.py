"""数据备份与恢复 API — 纯路由层

所有业务逻辑委托给 backup_service.py。

主要功能：
1. 备份管理：创建、恢复、删除备份
2. 加密支持：默认启用AES-256-GCM加密，支持密码和环境变量
3. 大文件分片传输：支持Range请求头和分片下载
4. 细粒度权限控制：backup_read、backup_create、backup_restore、backup_delete、backup_manage
5. 健康检查：系统状态监控
6. 备份验证：文件完整性检查和验证缓存
7. 统计信息：备份系统运行统计

新增端点：
- GET /export-enhanced: 支持Range请求头的增强备份导出
- GET /export-info: 获取备份文件信息（大小、分片数量等）
- GET /export-chunk/{chunk_index}: 下载备份文件的指定分片
- GET /health: 备份系统健康检查
- GET /validate/{filename}: 验证服务器上已有备份文件
- POST /validate-integrity: 执行深度完整性检查
- GET /stats: 获取备份统计信息

权限说明：
- backup_read: 查看备份列表和状态
- backup_create: 创建备份
- backup_restore: 恢复备份
- backup_delete: 删除备份
- backup_manage: 管理备份（所有权限）
"""
import asyncio
import hashlib
import io
import json
import logging
import os
import secrets
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

_background_tasks: set[asyncio.Task] = set()

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, Header
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.schemas.backup import (
    AsyncTaskResponse,
    BackupChunkInfo,
    BackupDeleteResponse,
    BackupEncryptionRequest,
    BackupHealthCheckResponse,
    BackupImportResponse,
    BackupIntegrityCheckResponse,
    BackupListResponse,
    BackupPingResponse,
    BackupProgressOut,
    BackupRecordListOut,
    BackupSaveResponse,
    BackupScheduleOut,
    BackupStatisticsResponse,
    BackupStatusOut,
    BackupTablesResponse,
    BackupTriggerOut,
    BackupValidateResponse,
    BackupValidationResponse,
    IncrementalBackupResponse,
    IncrementalRestoreResponse,
    IntegrityCheckResponse,
)
from fastapi_app.services import backup_service
from fastapi_app.services.backup_service import (
    BackupError, BackupFileError, BackupLockError, RestoreError,
)
from fastapi_app.shared_models import User


# ===========================================================================
# 细粒度权限控制
# ===========================================================================

def _get_backup_permission(endpoint_name: str) -> str:
    """
    根据端点名称返回对应的细粒度权限
    权限映射：
    - backup_read: 查看备份列表和状态
    - backup_create: 创建备份
    - backup_restore: 恢复备份
    - backup_delete: 删除备份
    - backup_manage: 管理备份（所有权限）
    """
    permission_map = {
        # 读取权限
        'ping': 'backup_read',
        'list_backup_tables': 'backup_read',
        'list_server_backups': 'backup_read',
        'backup_status': 'backup_read',
        'get_backup_records': 'backup_read',
        'get_backup_schedule': 'backup_read',
        'get_backup_info': 'backup_read',

        # 创建权限
        'export_backup': 'backup_create',
        'export_backup_enhanced': 'backup_create',
        'save_backup_to_server': 'backup_create',
        'save_incremental_backup': 'backup_create',

        # 恢复权限
        'import_backup': 'backup_restore',
        'restore_server_backup': 'backup_restore',
        'restore_incremental_backup': 'backup_restore',
        'async_import_backup': 'backup_restore',
        'async_restore_server_backup': 'backup_restore',

        # 删除权限
        'delete_server_backup': 'backup_delete',

        # 验证权限
        'validate_backup': 'backup_read',
        'validate_server_backup': 'backup_read',
        'run_integrity_check': 'backup_read',

        # 进度查询
        'get_restore_progress': 'backup_read',

        # 统计
        'get_backup_statistics': 'backup_read',

        # 调度
        'trigger_backup_schedule': 'backup_create',

        # 分片导出
        'export_backup_chunk': 'backup_create',

        # 健康检查
        'health_check': 'backup_read',

        # 验证文件
        'validate_backup_file': 'backup_read',

        # 深度完整性检查
        'validate_backup_integrity': 'backup_read',
    }

    return permission_map.get(endpoint_name, 'backup_manage')


def require_backup_permission(endpoint_name: str):
    """
    细粒度权限检查依赖工厂
    """
    permission = _get_backup_permission(endpoint_name)
    return require_permission(permission)

logger = logging.getLogger(__name__)
router = APIRouter()

# 兼容常量（供 Celery 旧导入过渡期使用，后续可移除）
BACKUP_DIR = backup_service.BACKUP_DIR
BACKUP_FORMAT_VERSION = backup_service.BACKUP_FORMAT_VERSION


def _ensure_backup_dir():
    backup_service.ensure_backup_dir()


# ---------------------------------------------------------------------------
# 1. GET /ping
# ---------------------------------------------------------------------------
@router.get('/ping', response_model=BackupPingResponse)
async def ping(user: User = Depends(require_backup_permission('ping'))):
    """快速诊断端点"""
    from fastapi_app.shared_models import Base
    return {
        'status': 'ok',
        'table_count': len(Base.metadata.sorted_tables),
        'format_version': backup_service.BACKUP_FORMAT_VERSION,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ---------------------------------------------------------------------------
# 2. GET /tables
# ---------------------------------------------------------------------------
@router.get('/tables', response_model=BackupTablesResponse)
async def list_backup_tables(
    user: User = Depends(require_backup_permission('list_backup_tables')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """列出所有可备份的数据库表及行数"""
    from fastapi_app.shared_models import Base
    from sqlalchemy import text
    # 白名单验证：仅允许 ORM 模型中已定义的表名
    valid_table_names = {t.name for t in Base.metadata.sorted_tables}
    table_info = []
    try:
        for table in Base.metadata.sorted_tables:
            name = str(table.name)
            if name not in valid_table_names:
                logger.warning(f'跳过非法表名: {name}')
                continue
            try:
                qtname = backup_service.quote_table(name)
                result = await db.execute(text(f'SELECT COUNT(*) FROM {qtname}'))
                count = result.scalar()
            except (SQLAlchemyError, OperationalError, OSError) as e:
                await db.rollback()
                logger.warning(f'统计表 {name} 行数失败: {e}')
                count = -1
            table_info.append({'name': name, 'rows': count})
    except (SQLAlchemyError, OperationalError, RuntimeError) as e:
        logger.error(f'列出备份表失败: {e}')
        raise HTTPException(status_code=500, detail='获取表信息失败，请查看服务器日志') from e
    return {'success': True, 'tables': table_info, 'total': len(table_info)}


# ---------------------------------------------------------------------------
# 3. GET /export
# ---------------------------------------------------------------------------
@router.get('/export')
async def export_backup(
    background_tasks: BackgroundTasks,
    remark: str = '',
    format: str = 'zip',
    encrypt: bool = Query(True, description="是否启用加密"),
    password: Optional[str] = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    一键备份全部数据（磁盘流式返回，避免大文件 OOM）

    参数：
    - remark: 备份备注
    - format: 备份格式，支持 'zip' 或 'json'
    - encrypt: 是否启用加密，默认True
    - password: 加密密码（查询参数）
    - x_backup_password: 加密密码（请求头）

    加密密码获取优先级：
    1. password查询参数
    2. X-Backup-Password请求头
    3. BACKUP_ENCRYPTION_PASSWORD环境变量
    4. 生成临时密码（记录到日志）

    权限：backup_create
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_files: list[str] = []

    def _register_temp_file(path: Path) -> Path:
        temp_files.append(str(path))
        return path

    def _cleanup_temp_files():
        for p in temp_files:
            try:
                os.unlink(p)
            except OSError:
                pass

    background_tasks.add_task(_cleanup_temp_files)

    if format == 'json':
        try:
            json_bytes = await backup_service.execute_legacy_backup_to_bytes(user, remark, db)
        except (BackupError, RuntimeError, OSError) as e:
            logger.error(f'JSON 备份导出失败: {e}')
            raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

        if encrypt:
            encryption_password = _get_encryption_password(password, x_backup_password)
            json_bytes = _encrypt_backup_data(json_bytes, encryption_password)
            filename = f'erp_backup_{timestamp}.json.enc'
            media_type = 'application/octet-stream'
        else:
            filename = f'erp_backup_{timestamp}.json'
            media_type = 'application/json'

        fd, tmp_path = tempfile.mkstemp(suffix='.json', prefix='erp_backup_')
        os.close(fd)
        tmp_path_obj = _register_temp_file(Path(tmp_path))
        await asyncio.to_thread(tmp_path_obj.write_bytes, json_bytes)

        return FileResponse(
            path=str(tmp_path_obj),
            filename=filename,
            media_type=media_type,
        )

    # ZIP 格式：直接写入临时文件并按需加密，避免将完整文件读入内存
    encryption_password = _get_encryption_password(password, x_backup_password) if encrypt else None
    try:
        zip_path, manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=encrypt,
            encrypt_password=encryption_password,
        )
    except (BackupError, RuntimeError, OSError) as e:
        logger.error(f'ZIP 备份导出失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

    _register_temp_file(zip_path)

    if encrypt:
        filename = f'erp_backup_{timestamp}.zip.enc'
        media_type = 'application/octet-stream'
    else:
        filename = f'erp_backup_{timestamp}.zip'
        media_type = 'application/zip'

    return FileResponse(
        path=str(zip_path),
        filename=filename,
        media_type=media_type,
    )


# ---------------------------------------------------------------------------
# 4. POST /import
# ---------------------------------------------------------------------------
@router.post('/import', response_model=BackupImportResponse)
async def import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    user: User = Depends(require_backup_permission('import_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """一键恢复：从备份文件恢复全部数据"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json / .gz')
        try:
            content = await file.read()
            if len(content) > backup_service.MAX_BACKUP_FILE_SIZE:
                raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
        except HTTPException:
            raise
        except (OSError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
        if not content:
            raise HTTPException(status_code=400, detail='备份文件内容为空')

    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    is_json = filename.endswith('.json') or filename.endswith('.gz') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    if not is_zip and not is_json:
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')

    try:
        pre_restore_info = await backup_service.create_pre_restore_backup(db)
    except (BackupError, OSError):
        pre_restore_info = {'success': False, 'error': '创建安全备份失败'}

    from sqlalchemy import text
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': backup_service.RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
        lock_acquired = True
    except HTTPException:
        raise
    except (RuntimeError, OSError) as e:
        # fail-closed：锁服务不可用时拒绝恢复，防止并发恢复导致数据损坏
        logger.error('获取恢复锁失败，拒绝执行恢复操作: %s', e)
        raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试') from e

    try:
        if is_zip:
            try:
                result = await backup_service.restore_from_zip(content, db)
            except RestoreError as e:
                raise HTTPException(status_code=500, detail=str(e)) from e
            result['pre_restore_backup'] = pre_restore_info
            total_rows = sum(td.get('rows', 0) for td in result.get('_manifest_tables', {}).values())
            result.pop('_manifest_tables', None)
            verification_ok = result.get('verification', {}).get('overall_pass', True)
            return {
                'success': verification_ok, 'format': 'zip', 'results': result,
                'total_inserted': total_rows,
                'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        # JSON path
        try:
            backup_data = await asyncio.to_thread(json.loads, content)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail='备份文件格式无效（非 ZIP 亦非有效 JSON）') from None
        if 'tables' not in backup_data:
            raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')

        try:
            result = await backup_service.restore_legacy_json(backup_data, db)
        except (BackupError, SQLAlchemyError, RuntimeError, ValueError):
            raise
        verification_ok = result.get('verification', {}).get('overall_pass', True)
        await db.commit()
        return {
            'success': verification_ok, 'format': 'json',
            'total_inserted': result['total_inserted'], 'results': result['results'],
            'errors': result['errors'], 'pre_restore_backup': pre_restore_info,
            'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    finally:
        if lock_acquired:
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': backup_service.RESTORE_LOCK_ID})
            except (RuntimeError, OSError, Exception):
                logger.warning('释放恢复锁失败')


# ---------------------------------------------------------------------------
# 5. POST /validate
# ---------------------------------------------------------------------------
@router.post('/validate', response_model=BackupValidateResponse)
async def validate_backup(
    file: UploadFile = File(...),
    user: User = Depends(require_backup_permission('validate_backup')),
):
    """验证备份文件，不执行恢复，仅返回摘要信息"""
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json / .gz')
    try:
        content = await file.read()
        if len(content) > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
    try:
        summary = backup_service.validate_backup_file(content, file.filename or '')
    except BackupFileError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {'success': True, 'summary': summary}


# ---------------------------------------------------------------------------
# 6. POST /save
# ---------------------------------------------------------------------------
@router.post('/save', response_model=BackupSaveResponse)
async def save_backup_to_server(
    remark: str = '',
    encrypt: bool = Query(True, description="是否启用加密"),
    password: Optional[str] = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('save_backup_to_server')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    一键备份到服务器默认路径
    
    参数：
    - remark: 备份备注
    - encrypt: 是否启用加密，默认True
    - password: 加密密码（查询参数）
    - x_backup_password: 加密密码（请求头）
    
    加密密码获取优先级：
    1. password查询参数
    2. X-Backup-Password请求头
    3. BACKUP_ENCRYPTION_PASSWORD环境变量
    4. 生成临时密码（记录到日志）
    
    权限：backup_create
    """
    backup_service.ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    try:
        zip_bytes, manifest = await backup_service.create_full_backup(db, user, remark)
    except (BackupError, RuntimeError, OSError) as e:
        logger.error(f'服务端备份失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
    
    # 应用加密
    if encrypt:
        encryption_password = _get_encryption_password(password, x_backup_password)
        encrypted_bytes = _encrypt_backup_data(zip_bytes, encryption_password)
        filename = f'erp_backup_{timestamp}.zip.enc'
        file_bytes = encrypted_bytes
    else:
        filename = f'erp_backup_{timestamp}.zip'
        file_bytes = zip_bytes
    
    filepath = backup_service.BACKUP_DIR / filename
    await asyncio.to_thread(filepath.write_bytes, file_bytes)

    # 写入 BackupRecord
    await backup_service.write_backup_record(
        db, record_type='full', trigger_type='manual',
        filename=filename, size=manifest.get('zip_size', len(file_bytes)),
        table_count=manifest.get('table_count', 0),
        total_rows=manifest.get('total_rows', 0),
        operator=user.username if hasattr(user, 'username') else str(user.id),
        remark=remark,
    )

    return {
        'success': True, 'format': 'zip', 'filename': filename,
        'size': manifest.get('zip_size', len(file_bytes)),
        'table_count': manifest.get('table_count', 0),
        'total_rows': manifest.get('total_rows', 0),
        'exported_at': manifest.get('exported_at'),
        'exported_by': manifest.get('exported_by'),
        'includes': manifest.get('includes', {}), 'remark': remark,
    }


# ---------------------------------------------------------------------------
# 7. GET /list
# ---------------------------------------------------------------------------
@router.get('/list', response_model=BackupListResponse)
async def list_server_backups(user: User = Depends(require_backup_permission('list_server_backups'))):
    """列出服务器默认路径上的所有备份文件"""
    backups = backup_service.list_backup_files()
    return {'success': True, 'backups': backups, 'total': len(backups)}


# ---------------------------------------------------------------------------
# 8. POST /restore-by-name/{filename}
# ---------------------------------------------------------------------------
@router.post('/restore-by-name/{filename}', response_model=BackupImportResponse)
async def restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    user: User = Depends(require_backup_permission('restore_server_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """从服务器默认路径恢复指定备份文件"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        content = filepath.read_bytes()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e

    is_zip = safe_name.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if is_zip:
        try:
            result = await backup_service.restore_from_zip(content, db)
        except RestoreError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        total_rows = sum(td.get('rows', 0) for td in result.get('_manifest_tables', {}).values())
        result.pop('_manifest_tables', None)
        verification_ok = result.get('verification', {}).get('overall_pass', True)
        return {
            'success': verification_ok, 'format': 'zip', 'filename': safe_name,
            'results': result, 'total_inserted': total_rows,
            'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    # JSON path
    try:
        backup_data = await asyncio.to_thread(json.loads, content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')

    from sqlalchemy import text
    lock_acquired = False
    try:
        lock_result = await db.execute(text('SELECT pg_try_advisory_lock(:lock_id)'), {'lock_id': backup_service.RESTORE_LOCK_ID})
        if not lock_result.scalar():
            raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
        lock_acquired = True
    except HTTPException:
        raise
    except (RuntimeError, OSError) as e:
        # fail-closed：锁服务不可用时拒绝恢复，防止并发恢复导致数据损坏
        logger.error('获取恢复锁失败，拒绝执行恢复操作: %s', e)
        raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试') from e
    try:
        result = await backup_service.restore_legacy_json(backup_data, db)
        await db.commit()
    except (BackupError, SQLAlchemyError, RuntimeError, ValueError):
        await db.rollback()
        raise
    finally:
        if lock_acquired:
            try:
                await db.execute(text('SELECT pg_advisory_unlock(:lock_id)'), {'lock_id': backup_service.RESTORE_LOCK_ID})
            except (RuntimeError, OSError, Exception):
                logger.warning('释放恢复锁失败')
    verification_ok = result.get('verification', {}).get('overall_pass', True)
    return {
        'success': verification_ok, 'format': 'json', 'filename': safe_name,
        'total_inserted': result['total_inserted'], 'results': result['results'],
        'errors': result['errors'],
        'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ---------------------------------------------------------------------------
# 9. DELETE /delete-by-name/{filename}
# ---------------------------------------------------------------------------
@router.delete('/delete-by-name/{filename}', response_model=BackupDeleteResponse)
async def delete_server_backup(
    filename: str,
    user: User = Depends(require_backup_permission('delete_server_backup')),
):
    """删除服务器默认路径上的指定备份文件"""
    try:
        deleted = backup_service.delete_backup_file(filename)
    except BackupFileError as e:
        raise HTTPException(status_code=404 if '不存在' in str(e) else 400, detail=str(e)) from e
    return {'success': True, 'deleted': deleted}


# ---------------------------------------------------------------------------
# 10. GET /status
# ---------------------------------------------------------------------------
@router.get('/status', response_model=BackupStatusOut)
async def backup_status(user: User = Depends(require_backup_permission('backup_status'))):
    """获取备份系统状态概览"""
    return backup_service.get_backup_status()


# ---------------------------------------------------------------------------
# 11. POST /save-incremental
# ---------------------------------------------------------------------------
@router.post('/save-incremental', response_model=IncrementalBackupResponse)
async def save_incremental_backup(
    remark: str = '',
    since: str = Query(''),
    user: User = Depends(require_backup_permission('save_incremental_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """增量备份"""
    try:
        result = await backup_service.create_incremental_backup(db, user, remark, since)
    except (BackupError, RuntimeError, OSError) as e:
        logger.error(f'增量备份失败: {e}')
        raise HTTPException(status_code=500, detail='增量备份失败，请查看服务器日志') from e
    return result


# ---------------------------------------------------------------------------
# 12. POST /restore-incremental/{filename}
# ---------------------------------------------------------------------------
@router.post('/restore-incremental/{filename}', response_model=IncrementalRestoreResponse)
async def restore_incremental_backup(
    filename: str,
    confirm: bool = Query(False),
    user: User = Depends(require_backup_permission('restore_incremental_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """从增量备份恢复"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        content = filepath.read_bytes()
    except OSError as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e
    is_zip = safe_name.endswith('.zip') or content[:4] == b'PK\x03\x04'
    if not is_zip:
        raise HTTPException(status_code=400, detail='增量备份文件必须是 ZIP 格式')
    try:
        result = await backup_service.restore_incremental(db, content, safe_name)
    except BackupLockError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RestoreError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return result


# ---------------------------------------------------------------------------
# 13. POST /integrity-check
# ---------------------------------------------------------------------------
@router.post('/integrity-check', response_model=IntegrityCheckResponse)
async def run_integrity_check(user: User = Depends(require_backup_permission('run_integrity_check'))):
    """备份完整性巡检"""
    from fastapi_app.tasks.backup_tasks import _do_integrity_check
    result = await _do_integrity_check()
    return result


# ---------------------------------------------------------------------------
# 14. GET /progress/{task_id}
# ---------------------------------------------------------------------------
@router.get('/progress/{task_id}', response_model=BackupProgressOut)
async def get_restore_progress(
    task_id: str,
    user: User = Depends(require_backup_permission('get_restore_progress')),
):
    """查询异步任务进度"""
    from fastapi_app.core.backup_progress import get_progress as _get_progress
    progress = await _get_progress(task_id)
    if progress is None:
        raise HTTPException(status_code=404, detail='任务不存在或已过期')
    return {'success': True, **progress}


# ---------------------------------------------------------------------------
# 15. POST /async-import
# ---------------------------------------------------------------------------
@router.post('/async-import', response_model=AsyncTaskResponse)
async def async_import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    user: User = Depends(require_backup_permission('async_import_backup')),
):
    """异步恢复：从上传文件恢复"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json / .gz')
    try:
        content = await file.read()
        if len(content) > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)')
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
    if not content:
        raise HTTPException(status_code=400, detail='备份文件内容为空')
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    is_json = filename.endswith('.json') or filename.endswith('.gz') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    if not is_zip and not is_json:
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')

    # 并发检查：避免同时启动多个恢复任务
    if await backup_service.is_restore_in_progress():
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')

    from fastapi_app.core.backup_progress import generate_task_id, create_progress
    task_id = generate_task_id()
    await create_progress(task_id, 'file_import')
    await backup_service.acquire_restore_lock(task_id)

    task = asyncio.create_task(_run_async_file_restore(task_id, content, is_zip, filename))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {'success': True, 'task_id': task_id, 'message': '恢复任务已启动'}


# ---------------------------------------------------------------------------
# 16. POST /async-restore-by-name/{filename}
# ---------------------------------------------------------------------------
@router.post('/async-restore-by-name/{filename}', response_model=AsyncTaskResponse)
async def async_restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    user: User = Depends(require_backup_permission('async_restore_server_backup')),
):
    """异步恢复：从服务器文件恢复"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')

    # 并发检查
    if await backup_service.is_restore_in_progress():
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        content = filepath.read_bytes()
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e

    from fastapi_app.core.backup_progress import generate_task_id, create_progress
    task_id = generate_task_id()
    await create_progress(task_id, 'server_restore')
    await backup_service.acquire_restore_lock(task_id)

    is_zip = safe_name.endswith('.zip') or content[:4] == b'PK\x03\x04'
    task = asyncio.create_task(_run_async_file_restore(task_id, content, is_zip, safe_name))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {'success': True, 'task_id': task_id, 'message': '恢复任务已启动'}


# ---------------------------------------------------------------------------
# 异步恢复后台任务
# ---------------------------------------------------------------------------
async def _run_async_file_restore(task_id: str, content: bytes, is_zip: bool, filename: str):
    """异步恢复后台执行"""
    from fastapi_app.core.backup_progress import (
        update_progress, complete_progress, fail_progress,
    )
    from fastapi_app.core.database import get_async_db_context

    try:
        await update_progress(task_id, 'pre_backup', detail='准备恢复')
        pre_restore_info = None

        async with get_async_db_context() as db:
            try:
                await update_progress(task_id, 'pre_backup', 0.0, '创建安全备份')
                pre_result = await backup_service.create_pre_restore_backup(db)
                pre_restore_info = pre_result
                await update_progress(task_id, 'pre_backup', 1.0, '安全备份完成')

                if is_zip:
                    result = await backup_service.restore_from_zip(content, db, task_id=task_id)
                else:
                    try:
                        backup_data = await asyncio.to_thread(json.loads, content)
                    except json.JSONDecodeError:
                        await fail_progress(task_id, '备份文件格式无效（非 ZIP 亦非有效 JSON）')
                        return
                    if 'tables' not in backup_data:
                        await fail_progress(task_id, 'JSON 备份文件缺少 tables 字段')
                        return
                    # JSON 恢复路径（带进度报告的简化版）
                    from sqlalchemy import text
                    lock_acquired = False
                    try:
                        lock_result = await db.execute(
                            text('SELECT pg_try_advisory_lock(:lock_id)'),
                            {'lock_id': backup_service.RESTORE_LOCK_ID}
                        )
                        if not lock_result.scalar():
                            await fail_progress(task_id, '另一个恢复操作正在执行中，请稍后重试')
                            return
                        lock_acquired = True
                    except (RuntimeError, OSError) as e:
                        # fail-closed：锁服务不可用时拒绝恢复，防止并发恢复导致数据损坏
                        logger.error('获取恢复锁失败，拒绝执行恢复操作: %s', e)
                        await fail_progress(task_id, '恢复锁服务暂时不可用，请稍后重试')
                        return
                    await update_progress(task_id, 'restore_db', 0.0, '通过 JSON 恢复数据库')
                    try:
                        result = await backup_service.restore_legacy_json(backup_data, db)
                    finally:
                        if lock_acquired:
                            try:
                                await db.execute(
                                    text('SELECT pg_advisory_unlock(:lock_id)'),
                                    {'lock_id': backup_service.RESTORE_LOCK_ID}
                                )
                            except (RuntimeError, OSError, Exception):
                                logger.warning('释放恢复锁失败')

                result['pre_restore_backup'] = pre_restore_info
                result['restored_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                result['filename'] = filename
                result['format'] = 'zip' if is_zip else 'json'

                if is_zip:
                    manifest_tables = result.get('_manifest_tables', {})
                    total_rows = sum(td.get('rows', 0) for td in manifest_tables.values()) if manifest_tables else 0
                    result['total_inserted'] = total_rows
                    result.pop('_manifest_tables', None)

                db_status = result.get('database', {}).get('status', '')
                verification_ok = result.get('verification', {}).get('overall_pass', True)
                restore_failed = db_status == 'error'
                verification_failed = not verification_ok

                if restore_failed:
                    error_msg = result.get('database', {}).get('error') or result.get('database', {}).get('message') or '数据库恢复失败'
                    await fail_progress(task_id, f'数据库恢复失败: {error_msg}')
                elif verification_failed:
                    l1_summary = result.get('verification', {}).get('l1_row_count', {}).get('summary', '')
                    l2_summary = result.get('verification', {}).get('l2_fingerprint', {}).get('summary', '')
                    verify_err = f'数据验证未通过: {l1_summary}'
                    if l2_summary:
                        verify_err += f'; {l2_summary}'
                    await fail_progress(task_id, verify_err)
                else:
                    await complete_progress(task_id, result)

            except HTTPException as e:
                await fail_progress(task_id, e.detail)
            except (RuntimeError, OSError, ValueError, Exception) as e:
                await fail_progress(task_id, str(e))
    except (RuntimeError, OSError, ValueError, Exception) as e:
        logger.error(f'异步恢复任务异常: {e}')
        await fail_progress(task_id, str(e))
    finally:
        # 释放恢复锁
        await backup_service.release_restore_lock()


# ---------------------------------------------------------------------------
# 新增端点（备份记录、定时任务）
# ---------------------------------------------------------------------------
@router.get('/records', response_model=BackupRecordListOut)
async def get_backup_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_backup_permission('get_backup_records')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """备份记录分页列表"""
    from fastapi_app.shared_models.backup_record import BackupRecord
    from sqlalchemy import select, func

    total_result = await db.execute(select(func.count(BackupRecord.id)))
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    stmt = select(BackupRecord).order_by(BackupRecord.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    records = result.scalars().all()

    return {
        'success': True,
        'records': [
            {
                'id': r.id, 'type': r.type, 'trigger_type': r.trigger_type,
                'filename': r.filename, 'size': r.size, 'table_count': r.table_count,
                'total_rows': r.total_rows, 'operator': r.operator, 'remark': r.remark,
                'status': r.status, 'error_message': r.error_message,
                'duration_seconds': r.duration_seconds, 'ip_address': r.ip_address,
                'user_agent': r.user_agent, 'parent_record_id': r.parent_record_id,
                'created_at': r.created_at.isoformat() if r.created_at else None,
                'updated_at': r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in records
        ],
        'total': total, 'page': page, 'page_size': page_size,
    }


@router.get('/schedule', response_model=BackupScheduleOut)
async def get_backup_schedule(user: User = Depends(require_backup_permission('get_backup_schedule'))):
    """定时任务配置"""
    from fastapi_app.core.celery_app import celery_app
    tasks = []
    beat_schedule = celery_app.conf.get('beat_schedule', {})
    for name, config in beat_schedule.items():
        schedule = config.get('schedule')
        if hasattr(schedule, 'hour') and hasattr(schedule, 'minute'):
            schedule_str = f'{schedule.hour}:{schedule.minute:02d}'
        else:
            schedule_str = str(schedule)
        tasks.append({
            'name': name, 'task': config.get('task', ''),
            'schedule': schedule_str, 'enabled': True,
        })
    return {'success': True, 'tasks': tasks}


@router.post('/schedule/trigger', response_model=BackupTriggerOut)
async def trigger_backup_schedule(
    task_name: str = Query(...),
    user: User = Depends(require_backup_permission('trigger_backup_schedule')),
):
    """手动触发定时任务"""
    from fastapi_app.core.celery_app import celery_app
    beat_schedule = celery_app.conf.get('beat_schedule', {})
    if task_name not in beat_schedule:
        raise HTTPException(status_code=404, detail=f'定时任务 {task_name} 不存在')
    task_id_str = beat_schedule[task_name].get('task', '')
    try:
        celery_app.send_task(task_id_str)
    except (RuntimeError, OSError, ConnectionError) as e:
        raise HTTPException(status_code=500, detail='触发任务失败，请查看服务器日志') from e
    return {'success': True, 'task_name': task_name, 'message': f'任务 {task_name} 已触发'}


# ===========================================================================
# 加密辅助函数
# ===========================================================================

def _get_encryption_password(
    password: Optional[str] = None,
    x_backup_password: Optional[str] = None,
) -> str:
    """
    获取加密密码，优先级：
    1. 请求参数中的 password
    2. 请求头 X-Backup-Password
    3. 环境变量 BACKUP_ENCRYPTION_PASSWORD
    4. 生成临时密码并记录到日志
    """
    # 1. 检查请求参数
    if password:
        return password
    
    # 2. 检查请求头
    if x_backup_password:
        return x_backup_password
    
    # 3. 检查环境变量
    env_password = os.environ.get('BACKUP_ENCRYPTION_PASSWORD')
    if env_password:
        return env_password
    
    # 4. 生成临时密码
    temp_password = secrets.token_urlsafe(32)
    logger.warning(
        f'未提供加密密码，使用临时密码：{temp_password[:8]}... '
        f'建议设置 BACKUP_ENCRYPTION_PASSWORD 环境变量或通过请求头/参数提供密码'
    )
    return temp_password


def _encrypt_backup_data(zip_bytes: bytes, password: str) -> bytes:
    """
    加密备份数据
    """
    try:
        from fastapi_app.core.backup_encryption import encrypt_backup
        encrypted_bytes, meta = encrypt_backup(zip_bytes, password)
        # 添加元数据到加密数据开头（JSON格式）
        meta_json = json.dumps(meta, ensure_ascii=False).encode('utf-8')
        meta_len = len(meta_json).to_bytes(4, 'big')
        return meta_len + meta_json + encrypted_bytes
    except ImportError:
        logger.error('加密模块不可用，备份数据将不加密')
        return zip_bytes
    except (ValueError, RuntimeError, OSError) as e:
        logger.error(f'加密失败: {e}')
        raise HTTPException(status_code=500, detail=f'备份加密失败: {str(e)}')


def _decrypt_backup_data(encrypted_bytes: bytes, password: str) -> bytes:
    """
    解密备份数据
    """
    try:
        from fastapi_app.core.backup_encryption import decrypt_backup, BackupFileError
        
        # 解析元数据长度
        if len(encrypted_bytes) < 4:
            raise BackupFileError('加密数据格式无效')
        
        meta_len = int.from_bytes(encrypted_bytes[:4], 'big')
        if len(encrypted_bytes) < 4 + meta_len:
            raise BackupFileError('加密数据格式无效')
        
        # 跳过元数据，解密实际数据
        encrypted_data = encrypted_bytes[4 + meta_len:]
        return decrypt_backup(encrypted_data, password)
    except ImportError:
        logger.error('加密模块不可用，假设数据未加密')
        return encrypted_bytes
    except BackupFileError as e:
        raise HTTPException(status_code=400, detail=f'解密失败: {str(e)}')
    except Exception as e:
        logger.error(f'解密失败: {e}')
        raise HTTPException(status_code=500, detail=f'备份解密失败: {str(e)}')


def _is_encrypted_data(data: bytes) -> bool:
    """
    检查数据是否已加密
    """
    try:
        # 检查是否有元数据长度前缀
        if len(data) < 4:
            return False
        
        meta_len = int.from_bytes(data[:4], 'big')
        if len(data) < 4 + meta_len:
            return False
        
        # 尝试解析元数据
        meta_json = data[4:4 + meta_len]
        meta = json.loads(meta_json.decode('utf-8'))
        return meta.get('encrypted', False)
    except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError, IndexError):
        return False


# ===========================================================================
# 新增端点：加密默认启用、大文件分片传输、权限控制增强、健康检查、备份验证、统计
# ===========================================================================

# ---------------------------------------------------------------------------
# 分片传输相关辅助函数
# ---------------------------------------------------------------------------

def _get_chunk_size() -> int:
    """获取分片大小，默认为10MB"""
    return 10 * 1024 * 1024  # 10MB


# ---------------------------------------------------------------------------
# GET /export-info
# ---------------------------------------------------------------------------
@router.get('/export-info', response_model=BackupChunkInfo)
async def get_backup_info(
    background_tasks: BackgroundTasks,
    remark: str = '',
    encrypt: bool = Query(True, description="是否启用加密"),
    password: Optional[str] = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('get_backup_info')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    获取备份文件信息（大小、分片数量等）
    用于支持大文件分片下载
    """
    def _sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    encryption_password = _get_encryption_password(password, x_backup_password) if encrypt else None
    try:
        backup_path, manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:
        logger.error(f'获取备份信息失败: {e}')
        raise HTTPException(status_code=500, detail='获取备份信息失败') from e

    background_tasks.add_task(lambda p=backup_path: p.exists() and os.unlink(p))

    try:
        total_size = os.path.getsize(backup_path)
        chunk_size = _get_chunk_size()
        total_chunks = (total_size + chunk_size - 1) // chunk_size
        checksum = await asyncio.to_thread(_sha256_file, backup_path)
    except Exception as e:
        logger.error(f'计算备份文件信息失败: {e}')
        raise HTTPException(status_code=500, detail='计算备份文件信息失败') from e

    filename = (
        f'erp_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip.enc'
        if encrypt else
        f'erp_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    )

    return {
        'filename': filename,
        'total_size': total_size,
        'chunk_size': chunk_size,
        'total_chunks': total_chunks,
        'encrypted': encrypt,
        'checksum': checksum,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ---------------------------------------------------------------------------
# GET /export-chunk/{chunk_index}
# ---------------------------------------------------------------------------
@router.get('/export-chunk/{chunk_index}')
async def export_backup_chunk(
    chunk_index: int,
    background_tasks: BackgroundTasks,
    remark: str = '',
    encrypt: bool = Query(True, description="是否启用加密"),
    password: Optional[str] = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup_chunk')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    下载备份文件的指定分片
    """
    if chunk_index < 0:
        raise HTTPException(status_code=400, detail='分片索引不能为负数')

    encryption_password = _get_encryption_password(password, x_backup_password) if encrypt else None
    try:
        backup_path, manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:
        logger.error(f'生成备份分片失败: {e}')
        raise HTTPException(status_code=500, detail='生成备份分片失败') from e

    background_tasks.add_task(lambda p=backup_path: p.exists() and os.unlink(p))

    try:
        total_size = os.path.getsize(backup_path)
        chunk_size = _get_chunk_size()
        total_chunks = (total_size + chunk_size - 1) // chunk_size

        if chunk_index >= total_chunks:
            raise HTTPException(status_code=416, detail=f'分片索引超出范围，最大索引为{total_chunks-1}')

        start = chunk_index * chunk_size
        end = min(start + chunk_size, total_size) - 1

        def _read_chunk(path: Path, start: int, length: int) -> bytes:
            with open(path, 'rb') as f:
                f.seek(start)
                return f.read(length)

        chunk_data = await asyncio.to_thread(_read_chunk, backup_path, start, end - start + 1)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'下载备份分片失败: {e}')
        raise HTTPException(status_code=500, detail='下载备份分片失败') from e

    from fastapi_app.schemas.backup import BackupChunkResponse
    return BackupChunkResponse(
        success=True,
        chunk_index=chunk_index,
        chunk_data=chunk_data,
        total_chunks=total_chunks,
        chunk_size=len(chunk_data),
        is_last=(chunk_index == total_chunks - 1),
    )


# ---------------------------------------------------------------------------
# 增强的 GET /export 支持Range请求头
# ---------------------------------------------------------------------------
@router.get('/export-enhanced')
async def export_backup_enhanced(
    background_tasks: BackgroundTasks,
    remark: str = '',
    format: str = 'zip',
    encrypt: bool = Query(True, description="是否启用加密"),
    password: Optional[str] = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup_enhanced')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    增强的备份导出端点，支持Range请求头和分片下载
    基于 FileResponse 磁盘流式传输，由 Starlette 自动处理 Range 请求。
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_files: list[str] = []

    def _register_temp_file(path: Path) -> Path:
        temp_files.append(str(path))
        return path

    background_tasks.add_task(lambda: [os.unlink(p) for p in temp_files if os.path.exists(p)])

    if format == 'json':
        try:
            json_bytes = await backup_service.execute_legacy_backup_to_bytes(user, remark, db)
        except Exception as e:
            logger.error(f'JSON 备份导出失败: {e}')
            raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

        if encrypt:
            encryption_password = _get_encryption_password(password, x_backup_password)
            json_bytes = _encrypt_backup_data(json_bytes, encryption_password)
            filename = f'erp_backup_{timestamp}.json.enc'
            media_type = 'application/octet-stream'
        else:
            filename = f'erp_backup_{timestamp}.json'
            media_type = 'application/json'

        fd, tmp_path = tempfile.mkstemp(suffix='.json', prefix='erp_backup_')
        os.close(fd)
        tmp_path_obj = _register_temp_file(Path(tmp_path))
        await asyncio.to_thread(tmp_path_obj.write_bytes, json_bytes)

        return FileResponse(
            path=str(tmp_path_obj),
            filename=filename,
            media_type=media_type,
        )

    # ZIP 格式：由服务层按需加密并写入临时文件
    encryption_password = _get_encryption_password(password, x_backup_password) if encrypt else None
    try:
        zip_path, manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:
        logger.error(f'ZIP 备份导出失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

    _register_temp_file(zip_path)

    if encrypt:
        filename = f'erp_backup_{timestamp}.zip.enc'
        media_type = 'application/octet-stream'
    else:
        filename = f'erp_backup_{timestamp}.zip'
        media_type = 'application/zip'

    return FileResponse(
        path=str(zip_path),
        filename=filename,
        media_type=media_type,
    )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
@router.get('/health', response_model=BackupHealthCheckResponse)
async def health_check(
    user: User = Depends(require_backup_permission('health_check')),
):
    """
    备份系统健康检查端点
    检查项目：
    1. 备份目录可写性
    2. 数据库连接状态
    3. Redis连接状态（用于进度追踪）
    4. 最近备份时间（不超过24小时）
    5. 备份文件完整性
    """
    from datetime import datetime, timedelta
    import os
    from pathlib import Path
    
    checks = {}
    issues = []
    overall_status = "healthy"
    
    # 1. 检查备份目录可写性
    try:
        backup_dir = backup_service.BACKUP_DIR
        test_file = backup_dir / ".health_check"
        
        # 检查目录是否存在
        if not backup_dir.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            checks['backup_dir'] = {
                'status': 'warning',
                'message': '备份目录不存在，已自动创建',
                'path': str(backup_dir)
            }
        else:
            # 检查目录可写性
            try:
                test_file.touch()
                test_file.unlink()
                checks['backup_dir'] = {
                    'status': 'healthy',
                    'message': '备份目录可写',
                    'path': str(backup_dir),
                    'writable': True
                }
            except Exception as e:
                checks['backup_dir'] = {
                    'status': 'unhealthy',
                    'message': f'备份目录不可写: {str(e)}',
                    'path': str(backup_dir),
                    'writable': False
                }
                issues.append(f'备份目录不可写: {str(e)}')
                overall_status = "degraded"
    except Exception as e:
        checks['backup_dir'] = {
            'status': 'unhealthy',
            'message': f'备份目录检查失败: {str(e)}',
            'error': str(e)
        }
        issues.append(f'备份目录检查失败: {str(e)}')
        overall_status = "unhealthy"
    
    # 2. 检查数据库连接状态
    try:
        from fastapi_app.core.database import get_async_db_context
        from sqlalchemy import text

        async def check_db_connection():
            async with get_async_db_context() as db:
                # 执行简单查询
                result = await db.execute(text('SELECT 1'))
                return result.scalar() == 1

        db_ok = await check_db_connection()
        checks['database'] = {
            'status': 'healthy' if db_ok else 'unhealthy',
            'message': '数据库连接正常' if db_ok else '数据库连接失败',
            'connected': db_ok
        }
        if not db_ok:
            issues.append('数据库连接失败')
            overall_status = "unhealthy"
    except Exception as e:
        checks['database'] = {
            'status': 'unhealthy',
            'message': f'数据库连接检查失败: {str(e)}',
            'error': str(e)
        }
        issues.append(f'数据库连接检查失败: {str(e)}')
        overall_status = "unhealthy"
    
    # 3. 检查Redis连接状态
    try:
        from utils.redis_cache import redis_cache

        redis_ok = False
        try:
            redis_client = redis_cache.redis_client
            if redis_client:
                # 检查Redis连接
                ping_result = await redis_client.ping()
                redis_ok = ping_result == True
            else:
                redis_ok = False
                issues.append('Redis客户端未初始化')
        except Exception as e:
            redis_ok = False
            logger.warning(f'Redis ping 失败: {e}')

        checks['redis'] = {
            'status': 'healthy' if redis_ok else 'warning',
            'message': 'Redis连接正常' if redis_ok else 'Redis连接不可用（不影响核心功能）',
            'connected': redis_ok
        }
        if not redis_ok:
            issues.append('Redis连接不可用，进度追踪功能可能受限')
            if overall_status == "healthy":
                overall_status = "degraded"
    except ImportError:
        checks['redis'] = {
            'status': 'warning',
            'message': 'Redis模块未安装，进度追踪功能不可用',
            'connected': False
        }
        issues.append('Redis模块未安装')
        if overall_status == "healthy":
            overall_status = "degraded"
    except Exception as e:
        checks['redis'] = {
            'status': 'warning',
            'message': f'Redis连接检查失败: {str(e)}',
            'error': str(e)
        }
        issues.append(f'Redis连接检查失败: {str(e)}')
        if overall_status == "healthy":
            overall_status = "degraded"
    
    # 4. 检查最近备份时间
    try:
        backup_files = backup_service.list_backup_files()
        if backup_files:
            # 获取最新的备份文件
            latest_backup = max(backup_files, key=lambda x: x.get('mtime', 0))
            latest_time = datetime.fromtimestamp(latest_backup.get('mtime', 0))
            now = datetime.now()
            hours_since_last_backup = (now - latest_time).total_seconds() / 3600
            
            checks['last_backup'] = {
                'status': 'healthy' if hours_since_last_backup <= 24 else 'warning',
                'message': f'最近备份时间: {latest_time.strftime("%Y-%m-%d %H:%M:%S")}',
                'latest_backup_time': latest_time.isoformat(),
                'hours_since_last_backup': round(hours_since_last_backup, 2),
                'within_24h': hours_since_last_backup <= 24
            }
            
            if hours_since_last_backup > 24:
                issues.append(f'最近备份时间超过24小时（{round(hours_since_last_backup, 1)}小时前）')
                if overall_status == "healthy":
                    overall_status = "degraded"
        else:
            checks['last_backup'] = {
                'status': 'warning',
                'message': '未找到备份文件',
                'latest_backup_time': None,
                'hours_since_last_backup': None,
                'within_24h': False
            }
            issues.append('未找到任何备份文件')
            if overall_status == "healthy":
                overall_status = "degraded"
    except Exception as e:
        checks['last_backup'] = {
            'status': 'unhealthy',
            'message': f'检查最近备份时间失败: {str(e)}',
            'error': str(e)
        }
        issues.append(f'检查最近备份时间失败: {str(e)}')
        overall_status = "unhealthy"
    
    # 5. 检查备份文件完整性（抽样检查）
    try:
        backup_files = backup_service.list_backup_files()
        if backup_files:
            # 随机选择1个文件进行检查（避免性能问题）
            import random
            sample_files = random.sample(backup_files, min(3, len(backup_files)))
            
            integrity_results = []
            for file_info in sample_files:
                filename = file_info.get('name', '')
                filepath = backup_service.BACKUP_DIR / filename
                
                try:
                    # 检查文件是否存在且可读
                    if filepath.exists() and filepath.is_file():
                        # 检查文件大小
                        file_size = filepath.stat().st_size
                        integrity_results.append({
                            'filename': filename,
                            'status': 'healthy',
                            'size': file_size,
                            'readable': True,
                            'message': '文件完整可读'
                        })
                    else:
                        integrity_results.append({
                            'filename': filename,
                            'status': 'unhealthy',
                            'size': 0,
                            'readable': False,
                            'message': '文件不存在或不是普通文件'
                        })
                        issues.append(f'备份文件异常: {filename}')
                        overall_status = "degraded"
                except Exception as e:
                    integrity_results.append({
                        'filename': filename,
                        'status': 'unhealthy',
                        'size': 0,
                        'readable': False,
                        'message': f'文件检查失败: {str(e)}',
                        'error': str(e)
                    })
                    issues.append(f'备份文件检查失败 {filename}: {str(e)}')
                    overall_status = "degraded"
            
            checks['backup_integrity'] = {
                'status': 'healthy' if all(r['status'] == 'healthy' for r in integrity_results) else 'degraded',
                'message': f'抽样检查了 {len(integrity_results)} 个备份文件',
                'sample_size': len(integrity_results),
                'results': integrity_results
            }
        else:
            checks['backup_integrity'] = {
                'status': 'warning',
                'message': '没有备份文件可检查',
                'sample_size': 0,
                'results': []
            }
    except Exception as e:
        checks['backup_integrity'] = {
            'status': 'unhealthy',
            'message': f'备份文件完整性检查失败: {str(e)}',
            'error': str(e)
        }
        issues.append(f'备份文件完整性检查失败: {str(e)}')
        overall_status = "unhealthy"
    
    # 6. 检查磁盘空间
    try:
        import shutil
        backup_dir = backup_service.BACKUP_DIR
        if backup_dir.exists():
            disk_usage = shutil.disk_usage(backup_dir)
            total_gb = disk_usage.total / (1024**3)
            used_gb = disk_usage.used / (1024**3)
            free_gb = disk_usage.free / (1024**3)
            free_percent = (disk_usage.free / disk_usage.total) * 100
            
            checks['disk_space'] = {
                'status': 'healthy' if free_percent > 10 else 'warning',
                'message': f'磁盘空间: {free_gb:.1f}GB 可用 ({free_percent:.1f}%)',
                'total_gb': round(total_gb, 2),
                'used_gb': round(used_gb, 2),
                'free_gb': round(free_gb, 2),
                'free_percent': round(free_percent, 2),
                'sufficient': free_percent > 10
            }
            
            if free_percent <= 10:
                issues.append(f'磁盘空间不足: 仅剩 {free_percent:.1f}% 可用空间')
                if overall_status == "healthy":
                    overall_status = "degraded"
            elif free_percent <= 5:
                issues.append(f'磁盘空间严重不足: 仅剩 {free_percent:.1f}% 可用空间')
                overall_status = "unhealthy"
        else:
            checks['disk_space'] = {
                'status': 'warning',
                'message': '备份目录不存在，无法检查磁盘空间',
                'sufficient': None
            }
    except Exception as e:
        checks['disk_space'] = {
            'status': 'warning',
            'message': f'磁盘空间检查失败: {str(e)}',
            'error': str(e)
        }
        issues.append(f'磁盘空间检查失败: {str(e)}')
        if overall_status == "healthy":
            overall_status = "degraded"
    
    return {
        'status': overall_status,
        'timestamp': datetime.now().isoformat(),
        'checks': checks,
        'issues': issues
    }


# ---------------------------------------------------------------------------
# 验证缓存管理
# ---------------------------------------------------------------------------

class ValidationCache:
    """备份验证结果缓存"""
    
    def __init__(self, ttl_seconds: int = 3600):  # 默认1小时缓存
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, cache_key: str):
        """获取缓存项"""
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if time.time() - entry['timestamp'] < self.ttl:
                return entry['data']
            else:
                # 缓存过期
                del self.cache[cache_key]
        return None
    
    def set(self, cache_key: str, data):
        """设置缓存项"""
        self.cache[cache_key] = {
            'data': data,
            'timestamp': time.time()
        }
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()


# 全局验证缓存实例
_validation_cache = ValidationCache()


def _get_validation_cache_key(filename: str, password: Optional[str] = None) -> str:
    """生成验证缓存键"""
    key_parts = [filename]
    if password:
        # 使用密码的哈希值，避免存储明文密码
        key_parts.append(hashlib.sha256(password.encode()).hexdigest()[:16])
    return hashlib.md5('_'.join(key_parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# GET /validate/{filename}
# ---------------------------------------------------------------------------
@router.get('/validate/{filename}', response_model=BackupValidationResponse)
async def validate_backup_file(
    filename: str,
    password: Optional[str] = Query(None, description="加密备份的解密密码"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('validate_backup_file')),
):
    """
    验证服务器上已有备份文件的完整性
    支持加密备份的解密验证
    """
    # 安全检查：防止路径遍历
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    
    # 检查缓存
    cache_key = _get_validation_cache_key(filename, password or x_backup_password)
    cached_result = _validation_cache.get(cache_key)
    if cached_result:
        cached_result['cache_hit'] = True
        return cached_result
    
    try:
        # 读取文件
        content = filepath.read_bytes()
        file_size = len(content)
        
        # 检查是否为加密文件
        encrypted = _is_encrypted_data(content)
        
        # 如果是加密文件，尝试解密
        if encrypted:
            if not password and not x_backup_password:
                # 检查环境变量
                env_password = os.environ.get('BACKUP_ENCRYPTION_PASSWORD')
                if not env_password:
                    return {
                        'success': True,
                        'filename': filename,
                        'valid': False,
                        'encrypted': True,
                        'size': file_size,
                        'checksum': None,
                        'format_version': None,
                        'table_count': None,
                        'total_rows': None,
                        'created_at': None,
                        'issues': ['文件已加密但未提供密码']
                    }
                password_to_use = env_password
            else:
                password_to_use = password or x_backup_password
            
            try:
                decrypted_content = _decrypt_backup_data(content, password_to_use)
                content = decrypted_content
                encryption_status = 'decrypted'
            except Exception as e:
                return {
                    'success': True,
                    'filename': filename,
                    'valid': False,
                    'encrypted': True,
                    'size': file_size,
                    'checksum': None,
                    'format_version': None,
                    'table_count': None,
                    'total_rows': None,
                    'created_at': None,
                    'issues': [f'解密失败: {str(e)}']
                }
        else:
            encryption_status = 'not_encrypted'
        
        # 计算校验和
        checksum = hashlib.sha256(content).hexdigest()
        
        # 验证文件格式
        issues = []
        valid = True
        
        try:
            # 尝试解析为ZIP文件
            if filename.endswith('.zip') or filename.endswith('.zip.enc'):
                with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                    # 检查必需的manifest文件
                    namelist = zip_file.namelist()
                    if 'manifest.json' not in namelist:
                        issues.append('ZIP文件缺少manifest.json')
                        valid = False
                    
                    # 检查文件完整性
                    for zip_info in zip_file.infolist():
                        try:
                            with zip_file.open(zip_info.filename) as f:
                                f.read()  # 尝试读取文件
                        except Exception as e:
                            issues.append(f'文件 {zip_info.filename} 损坏: {str(e)}')
                            valid = False
            
            # 尝试解析为JSON文件
            elif filename.endswith('.json') or filename.endswith('.json.enc'):
                try:
                    backup_data = json.loads(content.decode('utf-8'))
                    if 'tables' not in backup_data:
                        issues.append('JSON文件缺少tables字段')
                        valid = False
                except json.JSONDecodeError as e:
                    issues.append(f'JSON解析失败: {str(e)}')
                    valid = False
            
            else:
                issues.append('不支持的文件格式')
                valid = False
        
        except zipfile.BadZipFile as e:
            issues.append(f'ZIP文件损坏: {str(e)}')
            valid = False
        except Exception as e:
            issues.append(f'文件验证失败: {str(e)}')
            valid = False
        
        # 尝试提取元数据
        format_version = None
        table_count = None
        total_rows = None
        created_at = None
        
        if valid:
            try:
                if filename.endswith('.zip') or filename.endswith('.zip.enc'):
                    with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                        if 'manifest.json' in zip_file.namelist():
                            with zip_file.open('manifest.json') as f:
                                manifest = json.load(f)
                                format_version = manifest.get('format_version')
                                table_count = manifest.get('table_count')
                                total_rows = manifest.get('total_rows')
                                created_at = manifest.get('exported_at')
                elif filename.endswith('.json') or filename.endswith('.json.enc'):
                    backup_data = json.loads(content.decode('utf-8'))
                    format_version = backup_data.get('format_version', '1.0')
                    table_count = len(backup_data.get('tables', {}))
                    total_rows = sum(len(table_data.get('data', [])) for table_data in backup_data.get('tables', {}).values())
                    created_at = backup_data.get('exported_at')
            except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
                pass  # 元数据提取失败不影响验证结果
        
        # 构建响应
        result = {
            'success': True,
            'filename': filename,
            'valid': valid,
            'encrypted': encrypted,
            'size': file_size,
            'checksum': checksum,
            'format_version': format_version,
            'table_count': table_count,
            'total_rows': total_rows,
            'created_at': created_at,
            'issues': issues,
            'cache_hit': False,
            'cache_key': cache_key
        }
        
        # 缓存验证结果（仅当验证成功时）
        if valid:
            _validation_cache.set(cache_key, result)
        
        return result
        
    except Exception as e:
        logger.error(f'验证备份文件失败: {e}')
        raise HTTPException(status_code=500, detail=f'验证备份文件失败: {str(e)}') from e


# ---------------------------------------------------------------------------
# POST /validate-integrity
# ---------------------------------------------------------------------------
@router.post('/validate-integrity', response_model=BackupIntegrityCheckResponse)
async def validate_backup_integrity(
    user: User = Depends(require_backup_permission('validate_backup_integrity')),
):
    """
    执行深度完整性检查，验证所有备份文件的完整性
    支持缓存避免重复验证
    """
    try:
        backup_files = backup_service.list_backup_files()
        if not backup_files:
            return {
                'success': True,
                'checked_at': datetime.now().isoformat(),
                'total_files': 0,
                'valid_files': 0,
                'invalid_files': 0,
                'corrupted_files': [],
                'missing_files': [],
                'details': [],
                'cache_hit': False,
                'cache_key': None
            }
        
        # 检查缓存
        cache_key = hashlib.md5(
            '_'.join(sorted(f['name'] for f in backup_files)).encode()
        ).hexdigest()
        
        cached_result = _validation_cache.get(cache_key)
        if cached_result:
            cached_result['cache_hit'] = True
            return cached_result
        
        # 执行完整性检查
        details = []
        corrupted_files = []
        missing_files = []
        
        for file_info in backup_files:
            filename = file_info.get('name', '')
            filepath = backup_service.BACKUP_DIR / filename
            
            try:
                # 检查文件是否存在
                if not filepath.exists():
                    missing_files.append(filename)
                    details.append({
                        'filename': filename,
                        'status': 'missing',
                        'message': '文件不存在'
                    })
                    continue
                
                # 检查文件大小
                file_size = filepath.stat().st_size
                if file_size == 0:
                    corrupted_files.append(filename)
                    details.append({
                        'filename': filename,
                        'status': 'corrupted',
                        'message': '文件大小为0',
                        'size': file_size
                    })
                    continue
                
                # 尝试读取文件
                try:
                    content = filepath.read_bytes()
                    
                    # 检查是否为加密文件
                    encrypted = _is_encrypted_data(content)
                    
                    # 如果是加密文件，跳过深度验证（需要密码）
                    if encrypted:
                        details.append({
                            'filename': filename,
                            'status': 'encrypted',
                            'message': '文件已加密，跳过深度验证',
                            'size': file_size,
                            'encrypted': True
                        })
                        continue
                    
                    # 验证文件格式
                    valid = True
                    message = '验证通过'
                    
                    if filename.endswith('.zip'):
                        try:
                            with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
                                # 测试ZIP文件完整性
                                test_result = zip_file.testzip()
                                if test_result is not None:
                                    valid = False
                                    message = f'ZIP文件损坏: {test_result}'
                                    corrupted_files.append(filename)
                        except zipfile.BadZipFile as e:
                            valid = False
                            message = f'ZIP文件格式错误: {str(e)}'
                            corrupted_files.append(filename)
                    
                    elif filename.endswith('.json'):
                        try:
                            json.loads(content.decode('utf-8'))
                        except json.JSONDecodeError as e:
                            valid = False
                            message = f'JSON格式错误: {str(e)}'
                            corrupted_files.append(filename)
                    
                    details.append({
                        'filename': filename,
                        'status': 'valid' if valid else 'invalid',
                        'message': message,
                        'size': file_size,
                        'encrypted': encrypted,
                        'valid': valid
                    })
                    
                except Exception as e:
                    corrupted_files.append(filename)
                    details.append({
                        'filename': filename,
                        'status': 'corrupted',
                        'message': f'读取失败: {str(e)}',
                        'size': file_size,
                        'error': str(e)
                    })
                
            except Exception as e:
                details.append({
                    'filename': filename,
                    'status': 'error',
                    'message': f'检查过程中发生错误: {str(e)}',
                    'error': str(e)
                })
        
        valid_files = len(backup_files) - len(corrupted_files) - len(missing_files)
        
        result = {
            'success': True,
            'checked_at': datetime.now().isoformat(),
            'total_files': len(backup_files),
            'valid_files': valid_files,
            'invalid_files': len(corrupted_files) + len(missing_files),
            'corrupted_files': corrupted_files,
            'missing_files': missing_files,
            'details': details,
            'cache_hit': False,
            'cache_key': cache_key
        }
        
        # 缓存结果
        _validation_cache.set(cache_key, result)
        
        return result
        
    except Exception as e:
        logger.error(f'完整性检查失败: {e}')
        raise HTTPException(status_code=500, detail=f'完整性检查失败: {str(e)}') from e


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------
@router.get('/stats', response_model=BackupStatisticsResponse)
async def get_backup_statistics(
    user: User = Depends(require_backup_permission('get_backup_statistics')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """
    获取备份统计信息
    """
    from datetime import datetime, timedelta
    
    try:
        # 1. 获取备份文件列表
        backup_files = backup_service.list_backup_files()
        
        # 2. 计算基本统计
        total_backups = len(backup_files)
        total_size_bytes = sum(f.get('size', 0) for f in backup_files)
        
        # 3. 计算最近备份时间
        last_backup_time = None
        if backup_files:
            latest_backup = max(backup_files, key=lambda x: x.get('mtime', 0))
            last_backup_time = datetime.fromtimestamp(latest_backup.get('mtime', 0)).isoformat()
        
        # 4. 计算备份成功率（从备份记录中获取）
        from fastapi_app.shared_models.backup_record import BackupRecord
        from sqlalchemy import select, func
        
        # 获取最近30天的备份记录
        thirty_days_ago = datetime.now() - timedelta(days=30)
        stmt = select(
            func.count(BackupRecord.id).label('total'),
            func.sum(func.case((BackupRecord.status == 'success', 1), else_=0)).label('success')
        ).where(BackupRecord.created_at >= thirty_days_ago)
        
        result = await db.execute(stmt)
        stats = result.first()
        
        total_records = stats.total or 0
        success_records = stats.success or 0
        backup_success_rate = (success_records / total_records * 100) if total_records > 0 else 100.0
        
        # 5. 计算备份类型分布
        stmt_dist = select(
            BackupRecord.type,
            func.count(BackupRecord.id).label('count')
        ).where(BackupRecord.created_at >= thirty_days_ago).group_by(BackupRecord.type)
        
        result_dist = await db.execute(stmt_dist)
        type_distribution = {row.type: row.count for row in result_dist}
        
        # 6. 计算存储使用情况
        import shutil
        backup_dir = backup_service.BACKUP_DIR
        
        storage_usage = {}
        if backup_dir.exists():
            try:
                disk_usage = shutil.disk_usage(backup_dir)
                storage_usage = {
                    'total_bytes': disk_usage.total,
                    'used_bytes': disk_usage.used,
                    'free_bytes': disk_usage.free,
                    'used_percent': (disk_usage.used / disk_usage.total * 100) if disk_usage.total > 0 else 0,
                    'free_percent': (disk_usage.free / disk_usage.total * 100) if disk_usage.total > 0 else 0,
                }
            except Exception as e:
                logger.warning(f'无法获取磁盘使用情况: {e}')
                storage_usage = {'error': str(e)}
        
        # 7. 获取最近备份列表（最近10个）
        recent_backups = []
        if backup_files:
            # 按修改时间排序
            sorted_backups = sorted(backup_files, key=lambda x: x.get('mtime', 0), reverse=True)
            for backup in sorted_backups[:10]:  # 只取最近10个
                recent_backups.append({
                    'filename': backup.get('name', ''),
                    'size_bytes': backup.get('size', 0),
                    'modified_time': datetime.fromtimestamp(backup.get('mtime', 0)).isoformat(),
                    'type': 'full' if 'full' in backup.get('name', '').lower() else 'incremental' if 'inc' in backup.get('name', '').lower() else 'unknown',
                    'encrypted': backup.get('name', '').endswith('.enc'),
                })
        
        # 8. 计算备份频率
        backup_frequency = {}
        if backup_files:
            # 按日期分组
            from collections import defaultdict
            daily_counts = defaultdict(int)
            
            for backup in backup_files:
                mtime = datetime.fromtimestamp(backup.get('mtime', 0))
                date_key = mtime.strftime('%Y-%m-%d')
                daily_counts[date_key] += 1
            
            backup_frequency = {
                'daily_average': sum(daily_counts.values()) / max(len(daily_counts), 1),
                'most_active_day': max(daily_counts.items(), key=lambda x: x[1]) if daily_counts else None,
                'days_with_backups': len(daily_counts),
                'total_days': 30,  # 统计周期
            }
        
        return {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'total_backups': total_backups,
            'total_size_bytes': total_size_bytes,
            'last_backup_time': last_backup_time,
            'backup_success_rate': round(backup_success_rate, 2),
            'backup_distribution': type_distribution,
            'storage_usage': storage_usage,
            'recent_backups': recent_backups,
            'backup_frequency': backup_frequency,
            'records_analyzed': {
                'total': total_records,
                'success': success_records,
                'failure': total_records - success_records,
                'period_days': 30,
            }
        }
        
    except Exception as e:
        logger.error(f'获取备份统计信息失败: {e}')
        raise HTTPException(status_code=500, detail=f'获取备份统计信息失败: {str(e)}') from e
