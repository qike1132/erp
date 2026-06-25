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
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

_background_tasks: set[asyncio.Task] = set()

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import require_permission
from fastapi_app.core.exceptions import db_transaction, http_error
from fastapi_app.core.sanitizer import safe_exception_message
from fastapi_app.schemas.backup import (
    AsyncTaskResponse,
    BackupChunkInfo,
    BackupDeleteResponse,
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
    BACKUP_CHUNK_SIZE,
    BackupError,
    BackupFileError,
    BackupLockError,
    RestoreError,
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


def require_backup_permission(endpoint_name: str) -> Callable:
    """细粒度权限检查依赖工厂，返回 FastAPI 依赖。"""
    permission = _get_backup_permission(endpoint_name)
    return require_permission(permission)

logger = logging.getLogger(__name__)
router = APIRouter()

# 兼容常量（供 Celery 旧导入过渡期使用，后续可移除）
BACKUP_DIR = backup_service.BACKUP_DIR
BACKUP_FORMAT_VERSION = backup_service.BACKUP_FORMAT_VERSION


def _ensure_backup_dir() -> None:
    backup_service.ensure_backup_dir()


# ---------------------------------------------------------------------------
# 1. GET /ping
# ---------------------------------------------------------------------------
@router.get('/ping', response_model=BackupPingResponse)
async def ping(user: User = Depends(require_backup_permission('ping'))) -> dict:
    """快速诊断端点，返回表数量、格式版本和时间戳。"""
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
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """列出所有可备份的数据库表及行数。

    通过白名单验证仅查询 ORM 模型中已定义的表名，
    避免SQL注入风险。统计失败时该表行数记为 -1。
    """
    try:
        table_info = await backup_service.list_tables_with_row_counts(db)
    except (SQLAlchemyError, OperationalError, RuntimeError) as e:
        logger.error(f'列出备份表失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail='获取表信息失败，请查看服务器日志') from e
    return {'success': True, 'tables': table_info, 'total': len(table_info)}


# ---------------------------------------------------------------------------
# 3. GET /export
# ---------------------------------------------------------------------------
@router.get('/export')
async def export_backup(
    remark: str = '',
    format: str = 'zip',
    encrypt: bool = Query(True, description="是否启用加密"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup')),
    db: AsyncSession = Depends(get_async_db),
) -> StreamingResponse:
    """
    一键备份全部数据（流式返回，避免大文件 OOM）
    
    参数：
    - remark: 备份备注
    - format: 备份格式，支持 'zip' 或 'json'
    - encrypt: 是否启用加密，默认True
    - X-Backup-Password: 加密密码（请求头，推荐）
    
    加密密码获取优先级：
    1. X-Backup-Password请求头
    2. BACKUP_ENCRYPTION_PASSWORD环境变量
    3. 生成临时密码（记录到日志）
    
    权限：backup_create
    """
    import os as _os
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if format == 'json':
        try:
            json_bytes = await backup_service.execute_legacy_backup_to_bytes(user, remark, db)
        except (BackupError, RuntimeError, OSError) as e:
            logger.error(f'JSON 备份导出失败: %s', safe_exception_message(e))
            raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
        
        if encrypt:
            encryption_password = _get_encryption_password(x_backup_password)
            json_bytes = _encrypt_backup_data(json_bytes, encryption_password)
            filename = f'erp_backup_{timestamp}.json.enc'
            media_type = 'application/octet-stream'
        else:
            filename = f'erp_backup_{timestamp}.json'
            media_type = 'application/json'
        
        return StreamingResponse(
            io.BytesIO(json_bytes), media_type=media_type,
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    
    try:
        zip_path, manifest = await backup_service.create_full_backup_to_file(db, user, remark)
    except (BackupError, RuntimeError, OSError) as e:
        logger.error(f'ZIP 备份导出失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
    
    def _read_zip():
        with open(zip_path, 'rb') as file:
            return file.read()

    try:
        zip_bytes = await asyncio.to_thread(_read_zip)

        if encrypt:
            encryption_password = _get_encryption_password(x_backup_password)
            encrypted_bytes = _encrypt_backup_data(zip_bytes, encryption_password)
            filename = f'erp_backup_{timestamp}.zip.enc'
            media_type = 'application/octet-stream'
            response_data = encrypted_bytes
        else:
            filename = f'erp_backup_{timestamp}.zip'
            media_type = 'application/zip'
            response_data = zip_bytes

        return StreamingResponse(
            io.BytesIO(response_data), media_type=media_type,
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    finally:
        # 确保临时文件在任何路径（含加密失败抛异常）下都被清理
        try:
            _os.unlink(zip_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 恢复辅助函数（advisory lock 管理、格式检测、上传校验、恢复响应构建）
# ---------------------------------------------------------------------------
async def _acquire_restore_lock(db: AsyncSession) -> bool:
    """获取恢复 advisory lock，成功返回 True。失败时抛出 HTTPException。"""
    from sqlalchemy import text
    try:
        lock_result = await db.execute(
            text('SELECT pg_try_advisory_lock(:lock_id)'),
            {'lock_id': backup_service.RESTORE_LOCK_ID},
        )
        if not lock_result.scalar():
            raise http_error(
                status_code=409,
                code='RESTORE_LOCK_HELD',
                message='另一个恢复操作正在执行中，请稍后重试',
            )
        return True
    except HTTPException:
        raise
    except (RuntimeError, OSError) as e:
        # fail-closed：锁服务不可用时拒绝恢复，防止并发恢复导致数据损坏
        logger.error('获取恢复锁失败，拒绝执行恢复操作: %s', e)
        raise HTTPException(
            status_code=503,
            detail='恢复锁服务暂时不可用，请稍后重试',
        ) from e


async def _release_restore_lock(db: AsyncSession) -> None:
    """释放恢复 advisory lock。"""
    from sqlalchemy import text
    try:
        await db.execute(
            text('SELECT pg_advisory_unlock(:lock_id)'),
            {'lock_id': backup_service.RESTORE_LOCK_ID},
        )
    except (RuntimeError, OSError):
        logger.warning('释放恢复锁失败')


def _detect_backup_format(filename: str, content: bytes) -> tuple[bool, bool]:
    """检测备份文件格式，返回 (is_zip, is_json)。"""
    is_zip = filename.endswith('.zip') or content[:4] == b'PK\x03\x04'
    is_json = filename.endswith('.json') or (
        content[:1] == b'{' and content.strip().endswith(b'}')
    )
    return is_zip, is_json


async def _read_upload_for_restore(file: UploadFile, confirm: bool) -> tuple[bytes, bool, bool]:
    """读取并校验上传的备份文件，返回 (content, is_zip, is_json)。"""
    if not confirm:
        raise http_error(
            status_code=400,
            code='CONFIRMATION_REQUIRED',
            message='恢复操作需要二次确认，请传入 confirm=true',
        )
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise http_error(
            status_code=400,
            code='UNSUPPORTED_FILE_TYPE',
            message=f'不支持的文件类型: {ext}，仅支持 .zip / .json',
        )
    try:
        content = await file.read()
        if len(content) > backup_service.MAX_BACKUP_FILE_SIZE:
            raise http_error(
                status_code=400,
                code='FILE_TOO_LARGE',
                message=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)',
            )
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取文件失败: {e}') from e
    if not content:
        raise HTTPException(status_code=400, detail='备份文件内容为空')
    is_zip, is_json = _detect_backup_format(filename, content)
    if not is_zip and not is_json:
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')
    return content, is_zip, is_json


async def _create_pre_restore_backup(db: AsyncSession) -> dict:
    """创建恢复前安全备份，失败时返回错误信息字典。"""
    try:
        return await backup_service.create_pre_restore_backup(db)
    except (BackupError, OSError):
        return {'success': False, 'error': '创建安全备份失败'}


async def _build_zip_restore_response(
    content: bytes,
    db: AsyncSession,
    filename: Optional[str] = None,
    pre_restore_info: Optional[dict] = None,
) -> dict:
    """执行 ZIP 备份恢复并构建响应（不含事务/锁管理）。"""
    result = await backup_service.restore_from_zip(content, db)
    if pre_restore_info is not None:
        result['pre_restore_backup'] = pre_restore_info
    total_rows = sum(td.get('rows', 0) for td in result.get('_manifest_tables', {}).values())
    result.pop('_manifest_tables', None)
    verification_ok = result.get('verification', {}).get('overall_pass', True)
    response = {
        'success': verification_ok, 'format': 'zip', 'results': result,
        'total_inserted': total_rows,
        'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if filename is not None:
        response['filename'] = filename
    return response


async def _restore_json_upload(content: bytes, db: AsyncSession, pre_restore_info: dict) -> dict:
    """解析并执行 JSON 备份恢复（上传路径），构建响应。"""
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
    return {
        'success': verification_ok, 'format': 'json',
        'total_inserted': result['total_inserted'], 'results': result['results'],
        'errors': result['errors'], 'pre_restore_backup': pre_restore_info,
        'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def _read_server_backup_file(filename: str) -> tuple[str, bytes]:
    """读取服务器备份文件，校验文件名安全性与存在性，返回 (safe_name, content)。"""
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
    return safe_name, content


def _decrypt_server_backup_if_needed(
    safe_name: str, content: bytes, x_backup_password: Optional[str],
) -> tuple[str, bytes]:
    """若为加密备份则解密，返回 (解密后文件名, 解密后内容)。"""
    if not safe_name.endswith('.enc'):
        return safe_name, content
    enc_password = _get_decryption_password(x_backup_password)
    if not enc_password:
        raise http_error(
            status_code=400,
            code='ENCRYPTED_PASSWORD_REQUIRED',
            message='加密备份需要提供解密密码，请通过 X-Backup-Password 请求头提供',
        )
    try:
        content = _decrypt_backup_data(content, enc_password)
    except HTTPException:
        raise
    except (ValueError, RuntimeError, OSError) as e:
        raise HTTPException(status_code=400, detail=f'解密失败: {str(e)}') from e
    # 解密后按内部格式处理
    return safe_name.removesuffix('.enc'), content


# ---------------------------------------------------------------------------
# 4. POST /import
# ---------------------------------------------------------------------------
@router.post('/import', response_model=BackupImportResponse)
async def import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    user: User = Depends(require_backup_permission('import_backup')),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """一键恢复：从备份文件恢复全部数据。

    支持 ZIP 和 JSON 格式，使用 advisory lock 防止并发恢复。
    恢复前自动创建安全备份（pre_restore）。
    """
    content, is_zip, _ = await _read_upload_for_restore(file, confirm)
    lock_acquired = await _acquire_restore_lock(db)
    try:
        async with db_transaction(db):
            pre_restore_info = await _create_pre_restore_backup(db)
            if is_zip:
                try:
                    return await _build_zip_restore_response(
                        content, db, pre_restore_info=pre_restore_info,
                    )
                except RestoreError as e:
                    raise HTTPException(status_code=500, detail=str(e)) from e
            return await _restore_json_upload(content, db, pre_restore_info)
    finally:
        if lock_acquired:
            await _release_restore_lock(db)


# ---------------------------------------------------------------------------
# 5. POST /validate
# ---------------------------------------------------------------------------
@router.post('/validate', response_model=BackupValidateResponse)
async def validate_backup(
    file: UploadFile = File(...),
    user: User = Depends(require_backup_permission('validate_backup')),
) -> dict:
    """验证备份文件，不执行恢复，仅返回摘要信息。"""
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json')
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
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('save_backup_to_server')),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    一键备份到服务器默认路径
    
    参数：
    - remark: 备份备注
    - encrypt: 是否启用加密，默认True
    - X-Backup-Password: 加密密码（请求头，推荐）
    
    加密密码获取优先级：
    1. X-Backup-Password请求头
    2. BACKUP_ENCRYPTION_PASSWORD环境变量
    3. 生成临时密码（记录到日志）
    
    权限：backup_create
    """
    backup_service.ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    try:
        async with db_transaction(db):
            zip_bytes, manifest = await backup_service.create_full_backup(db, user, remark)
    except (BackupError, RuntimeError, OSError) as e:
        logger.error(f'服务端备份失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

    if encrypt:
        encryption_password = _get_encryption_password(x_backup_password)
        encrypted_bytes = _encrypt_backup_data(zip_bytes, encryption_password)
        filename = f'erp_backup_{timestamp}.zip.enc'
        file_bytes = encrypted_bytes
    else:
        filename = f'erp_backup_{timestamp}.zip'
        file_bytes = zip_bytes

    filepath = backup_service.BACKUP_DIR / filename
    await asyncio.to_thread(filepath.write_bytes, file_bytes)

    # 加密备份时写入 .meta 侧车文件，供列表展示元数据
    if encrypt:
        meta_dict = {
            'created_at': manifest.get('exported_at', ''),
            'exported_by': manifest.get('exported_by', ''),
            'remark': remark,
            'table_count': manifest.get('table_count', 0),
            'total_rows': manifest.get('total_rows', 0),
            'includes': manifest.get('includes', {}),
            'base_timestamp': manifest.get('base_timestamp', ''),
            'encrypted': True,
            'algorithm': 'AES-256-GCM',
        }
        meta_path = backup_service.BACKUP_DIR / (filename + '.meta')
        await asyncio.to_thread(meta_path.write_bytes, json.dumps(meta_dict, indent=2, ensure_ascii=False).encode('utf-8'))

    # 写入 BackupRecord
    async with db_transaction(db):
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
async def list_server_backups(user: User = Depends(require_backup_permission('list_server_backups'))) -> dict:
    """列出服务器默认路径上的所有备份文件。"""
    backups = backup_service.list_backup_files()
    return {'success': True, 'backups': backups, 'total': len(backups)}


# ---------------------------------------------------------------------------
# 8. POST /restore-by-name/{filename}
# ---------------------------------------------------------------------------
def _get_decryption_password(
    header_password: Optional[str] = None,
) -> Optional[str]:
    """
    获取解密密码（仅从请求头获取，不生成临时密码）
    """
    if header_password:
        return header_password
    return os.environ.get('BACKUP_ENCRYPTION_PASSWORD')


@router.post('/restore-by-name/{filename}', response_model=BackupImportResponse)
async def restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('restore_server_backup')),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """从服务器默认路径恢复指定备份文件。

    支持加密备份解密，使用 Path.name 防止路径穿越。
    """
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    safe_name, content = _read_server_backup_file(filename)
    safe_name, content = _decrypt_server_backup_if_needed(safe_name, content, x_backup_password)
    is_zip, _ = _detect_backup_format(safe_name, content)
    if is_zip:
        try:
            async with db_transaction(db):
                return await _build_zip_restore_response(content, db, filename=safe_name)
        except RestoreError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
    # JSON path
    try:
        backup_data = await asyncio.to_thread(json.loads, content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail='备份文件格式无效') from None
    if 'tables' not in backup_data:
        raise HTTPException(status_code=400, detail='JSON 备份文件缺少 tables 字段')
    lock_acquired = await _acquire_restore_lock(db)
    try:
        async with db_transaction(db):
            result = await backup_service.restore_legacy_json(backup_data, db)
    finally:
        if lock_acquired:
            await _release_restore_lock(db)
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
) -> dict:
    """删除服务器默认路径上的指定备份文件。"""
    try:
        deleted = backup_service.delete_backup_file(filename)
    except BackupFileError as e:
        raise HTTPException(status_code=404 if '不存在' in str(e) else 400, detail=str(e)) from e
    return {'success': True, 'deleted': deleted}


# ---------------------------------------------------------------------------
# 10. GET /status
# ---------------------------------------------------------------------------
@router.get('/status', response_model=BackupStatusOut)
async def backup_status(user: User = Depends(require_backup_permission('backup_status'))) -> dict:
    """获取备份系统状态概览。"""
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
) -> dict:
    """增量备份，仅备份自指定时间以来变更的数据。"""
    try:
        async with db_transaction(db):
            result = await backup_service.create_incremental_backup(db, user, remark, since)
        return result
    except (BackupError, RuntimeError, OSError) as e:
        logger.error(f'增量备份失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail='增量备份失败，请查看服务器日志') from e


# ---------------------------------------------------------------------------
# 12. POST /restore-incremental/{filename}
# ---------------------------------------------------------------------------
@router.post('/restore-incremental/{filename}', response_model=IncrementalRestoreResponse)
async def restore_incremental_backup(
    filename: str,
    confirm: bool = Query(False),
    user: User = Depends(require_backup_permission('restore_incremental_backup')),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """从增量备份恢复，仅支持 ZIP 格式。"""
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
        async with db_transaction(db):
            result = await backup_service.restore_incremental(db, content, safe_name)
        return result
    except BackupLockError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RestoreError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ---------------------------------------------------------------------------
# 13. POST /integrity-check
# ---------------------------------------------------------------------------
@router.post('/integrity-check', response_model=IntegrityCheckResponse)
async def run_integrity_check(user: User = Depends(require_backup_permission('run_integrity_check'))) -> dict:
    """备份完整性巡检，检查所有备份文件的完整性。"""
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
) -> dict:
    """查询异步恢复任务进度。"""
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
) -> dict:
    """异步恢复：从上传文件恢复，返回任务 ID 供进度查询。"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .json')
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
    is_json = filename.endswith('.json') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    if not is_zip and not is_json:
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')

    # 并发检查：避免同时启动多个恢复任务
    if await backup_service.is_restore_in_progress():
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')

    from fastapi_app.core.backup_progress import create_progress, generate_task_id
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
) -> dict:
    """异步恢复：从服务器文件恢复，返回任务 ID 供进度查询。"""
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

    from fastapi_app.core.backup_progress import create_progress, generate_task_id
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
async def _run_async_file_restore(task_id: str, content: bytes, is_zip: bool, filename: str) -> None:
    """异步恢复后台执行，更新进度并释放恢复锁。"""
    from fastapi_app.core.backup_progress import (
        complete_progress,
        fail_progress,
        update_progress,
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
        logger.error(f'异步恢复任务异常: %s', safe_exception_message(e))
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
) -> dict:
    """备份记录分页列表，按创建时间倒序。"""
    from sqlalchemy import func, select

    from fastapi_app.shared_models.backup_record import BackupRecord

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
                'id': record.id, 'type': record.type, 'trigger_type': record.trigger_type,
                'filename': record.filename, 'size': record.size, 'table_count': record.table_count,
                'total_rows': record.total_rows, 'operator': record.operator, 'remark': record.remark,
                'status': record.status, 'error_message': record.error_message,
                'duration_seconds': record.duration_seconds, 'ip_address': record.ip_address,
                'user_agent': record.user_agent, 'parent_record_id': record.parent_record_id,
                'created_at': record.created_at.isoformat() if record.created_at else None,
                'updated_at': record.updated_at.isoformat() if record.updated_at else None,
            }
            for record in records
        ],
        'total': total, 'page': page, 'page_size': page_size,
    }


@router.get('/schedule', response_model=BackupScheduleOut)
async def get_backup_schedule(user: User = Depends(require_backup_permission('get_backup_schedule'))) -> dict:
    """定时任务配置列表。"""
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
) -> dict:
    """手动触发指定的定时备份任务。"""
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
    header_password: Optional[str] = None,
) -> str:
    """
    获取加密密码，优先级：
    1. 请求头 X-Backup-Password
    2. 环境变量 BACKUP_ENCRYPTION_PASSWORD
    3. 生成临时密码（仅记录日志不记录密码内容）
    """
    if header_password:
        return header_password
    
    env_password = os.environ.get('BACKUP_ENCRYPTION_PASSWORD')
    if env_password:
        return env_password
    
    temp_password = secrets.token_urlsafe(32)
    logger.warning(
        '未提供加密密码，已生成临时密码。'
        '建议设置 BACKUP_ENCRYPTION_PASSWORD 环境变量或通过 X-Backup-Password 请求头提供密码'
    )
    return temp_password


def _encrypt_backup_data(zip_bytes: bytes, password: str) -> bytes:
    """
    加密备份数据。加密模块不可用时抛出异常，不静默降级。
    """
    try:
        from fastapi_app.core.backup_encryption import encrypt_backup
        encrypted_bytes, meta = encrypt_backup(zip_bytes, password)
        meta_json = json.dumps(meta, ensure_ascii=False).encode('utf-8')
        meta_len = len(meta_json).to_bytes(4, 'big')
        return meta_len + meta_json + encrypted_bytes
    except ImportError as e:
        logger.error('加密模块不可用，无法完成加密备份')
        raise HTTPException(status_code=500, detail='加密模块不可用，请安装加密依赖或禁用加密') from e
    except HTTPException:
        raise
    except (ValueError, RuntimeError, OSError) as e:
        logger.error(f'加密失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail=f'备份加密失败: {str(e)}') from e


def _decrypt_backup_data(encrypted_bytes: bytes, password: str) -> bytes:
    """
    解密备份数据。解密失败时抛出明确异常，不静默返回原数据。
    """
    try:
        from fastapi_app.core.backup_encryption import BackupFileError, decrypt_backup
        
        if len(encrypted_bytes) < 4:
            raise BackupFileError('加密数据格式无效')
        
        meta_len = int.from_bytes(encrypted_bytes[:4], 'big')
        if len(encrypted_bytes) < 4 + meta_len:
            raise BackupFileError('加密数据格式无效')
        
        encrypted_data = encrypted_bytes[4 + meta_len:]
        return decrypt_backup(encrypted_data, password)
    except ImportError as e:
        logger.error('加密模块不可用，无法解密备份')
        raise HTTPException(status_code=500, detail='加密模块不可用，无法解密备份文件') from e
    except HTTPException:
        raise
    except BackupFileError as e:
        raise HTTPException(status_code=400, detail=f'解密失败: {str(e)}') from e
    except (ValueError, RuntimeError, OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        logger.error(f'解密失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=400, detail=f'备份解密失败: {str(e)}') from e


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

def _parse_range_header(range_header: str, file_size: int) -> tuple[int, int]:
    """解析 Range 请求头，返回 (start, end) 字节范围。

    支持格式：bytes=start-end、bytes=start-、bytes=-end。

    Args:
        range_header: Range 请求头字符串。
        file_size: 文件总大小（字节）。

    Returns:
        (start, end) 字节范围元组。

    Raises:
        HTTPException 416: Range 头格式无效或超出文件大小时抛出。
    """
    if not range_header.startswith('bytes='):
        raise HTTPException(status_code=416, detail='无效的Range头格式')

    range_str = range_header[6:]
    if '-' not in range_str:
        raise HTTPException(status_code=416, detail='无效的Range头格式')

    start_str, end_str = range_str.split('-', 1)

    try:
        if start_str and end_str:
            start = int(start_str)
            end = int(end_str)
        elif start_str:
            start = int(start_str)
            end = file_size - 1
        elif end_str:
            end = int(end_str)
            start = file_size - end
            end = file_size - 1
        else:
            raise HTTPException(status_code=416, detail='无效的Range头格式')
    except ValueError as e:
        raise HTTPException(status_code=416, detail='无效的Range头格式') from e

    if start < 0 or end >= file_size or start > end:
        raise HTTPException(status_code=416, detail='请求范围超出文件大小')

    return start, end


def _get_chunk_size() -> int:
    """
    获取分片大小，默认为100MB。

    可通过 BACKUP_CHUNK_SIZE 环境变量自定义（单位：字节）。
    """
    return BACKUP_CHUNK_SIZE


# ---------------------------------------------------------------------------
# GET /export-info
# ---------------------------------------------------------------------------
@router.get('/export-info', response_model=BackupChunkInfo)
async def get_backup_info(
    remark: str = '',
    encrypt: bool = Query(True, description="是否启用加密"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('get_backup_info')),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    获取备份文件信息（大小、分片数量等）
    用于支持大文件分片下载
    
    加密密码通过 X-Backup-Password 请求头提供
    """
    try:
        # 生成备份数据但不写入文件
        zip_bytes, manifest = await backup_service.create_full_backup(db, user, remark)
        
        # 应用加密
        if encrypt:
            encryption_password = _get_encryption_password(x_backup_password)
            backup_data = _encrypt_backup_data(zip_bytes, encryption_password)
            filename = f'erp_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip.enc'
        else:
            backup_data = zip_bytes
            filename = f'erp_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        
        # 计算分片信息
        total_size = len(backup_data)
        chunk_size = _get_chunk_size()
        total_chunks = (total_size + chunk_size - 1) // chunk_size  # 向上取整
        
        # 计算校验和
        import hashlib
        checksum = hashlib.sha256(backup_data).hexdigest()
        
        return {
            'filename': filename,
            'total_size': total_size,
            'chunk_size': chunk_size,
            'total_chunks': total_chunks,
            'encrypted': encrypt,
            'checksum': checksum,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
    except HTTPException:
        raise
    except (BackupError, RuntimeError, OSError, ValueError) as e:
        logger.error(f'获取备份信息失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail='获取备份信息失败') from e


# ---------------------------------------------------------------------------
# GET /export-chunk/{chunk_index}
# ---------------------------------------------------------------------------
@router.get('/export-chunk/{chunk_index}')
async def export_backup_chunk(
    chunk_index: int,
    remark: str = '',
    encrypt: bool = Query(True, description="是否启用加密"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup_chunk')),
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    """
    下载备份文件的指定分片
    
    加密密码通过 X-Backup-Password 请求头提供
    """
    if chunk_index < 0:
        raise HTTPException(status_code=400, detail='分片索引不能为负数')
    
    try:
        # 生成备份数据
        zip_bytes, manifest = await backup_service.create_full_backup(db, user, remark)
        
        # 应用加密
        if encrypt:
            encryption_password = _get_encryption_password(x_backup_password)
            backup_data = _encrypt_backup_data(zip_bytes, encryption_password)
        else:
            backup_data = zip_bytes
        
        # 计算分片信息
        total_size = len(backup_data)
        chunk_size = _get_chunk_size()
        total_chunks = (total_size + chunk_size - 1) // chunk_size
        
        if chunk_index >= total_chunks:
            raise HTTPException(status_code=416, detail=f'分片索引超出范围，最大索引为{total_chunks-1}')
        
        # 计算分片范围
        start = chunk_index * chunk_size
        end = min(start + chunk_size, total_size) - 1
        chunk_data = backup_data[start:end+1]
        
        # 构建响应
        from fastapi_app.schemas.backup import BackupChunkResponse
        return BackupChunkResponse(
            success=True,
            chunk_index=chunk_index,
            chunk_data=chunk_data,
            total_chunks=total_chunks,
            chunk_size=len(chunk_data),
            is_last=(chunk_index == total_chunks - 1),
        )
        
    except HTTPException:
        raise
    except (BackupError, RuntimeError, OSError, ValueError, IndexError) as e:
        logger.error(f'下载备份分片失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail='下载备份分片失败') from e


# ---------------------------------------------------------------------------
# 增强的 GET /export 支持Range请求头
# ---------------------------------------------------------------------------
@router.get('/export-enhanced')
async def export_backup_enhanced(
    request: Request,
    remark: str = '',
    format: str = 'zip',
    encrypt: bool = Query(True, description="是否启用加密"),
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup_enhanced')),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """
    增强的备份导出端点，支持Range请求头和分片下载
    
    加密密码通过 X-Backup-Password 请求头提供
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if format == 'json':
        try:
            json_bytes = await backup_service.execute_legacy_backup_to_bytes(user, remark, db)
        except (BackupError, RuntimeError, OSError) as e:
            logger.error(f'JSON 备份导出失败: %s', safe_exception_message(e))
            raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
        
        if encrypt:
            encryption_password = _get_encryption_password(x_backup_password)
            json_bytes = _encrypt_backup_data(json_bytes, encryption_password)
            filename = f'erp_backup_{timestamp}.json.enc'
            media_type = 'application/octet-stream'
        else:
            filename = f'erp_backup_{timestamp}.json'
            media_type = 'application/json'
        
        backup_data = json_bytes
        
    else:
        try:
            zip_bytes, manifest = await backup_service.create_full_backup(db, user, remark)
        except (BackupError, RuntimeError, OSError) as e:
            logger.error(f'ZIP 备份导出失败: %s', safe_exception_message(e))
            raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
        
        if encrypt:
            encryption_password = _get_encryption_password(x_backup_password)
            backup_data = _encrypt_backup_data(zip_bytes, encryption_password)
            filename = f'erp_backup_{timestamp}.zip.enc'
            media_type = 'application/octet-stream'
        else:
            backup_data = zip_bytes
            filename = f'erp_backup_{timestamp}.zip'
            media_type = 'application/zip'
    
    # 检查Range请求头
    range_header = request.headers.get('range')
    total_size = len(backup_data)
    
    if range_header:
        try:
            start, end = _parse_range_header(range_header, total_size)
            chunk_size = end - start + 1
            chunk_data = backup_data[start:end+1]
            
            # 返回部分内容响应
            from fastapi.responses import Response
            headers = {
                'Content-Range': f'bytes {start}-{end}/{total_size}',
                'Accept-Ranges': 'bytes',
                'Content-Length': str(chunk_size),
                'Content-Disposition': f'attachment; filename="{filename}"',
            }
            
            return Response(
                content=chunk_data,
                status_code=206,  # Partial Content
                headers=headers,
                media_type=media_type,
            )
        except HTTPException:
            # Range解析失败，返回完整文件
            pass
    
    # 返回完整文件
    headers = {
        'Content-Length': str(total_size),
        'Accept-Ranges': 'bytes',
        'Content-Disposition': f'attachment; filename="{filename}"',
    }
    
    return Response(
        content=backup_data,
        headers=headers,
        media_type=media_type,
    )


# ---------------------------------------------------------------------------
# GET /health — 辅助函数
# ---------------------------------------------------------------------------

def _check_backup_dir() -> tuple[dict, list[str], str | None]:
    """检查备份目录可写性，返回 (check_result, issues, severity)"""
    backup_dir = backup_service.BACKUP_DIR
    test_file = backup_dir / ".health_check"

    if not backup_dir.exists():
        backup_dir.mkdir(parents=True, exist_ok=True)
        return (
            {'status': 'warning', 'message': '备份目录不存在，已自动创建', 'path': str(backup_dir)},
            [],
            None,
        )

    try:
        test_file.touch()
        test_file.unlink()
        return (
            {'status': 'healthy', 'message': '备份目录可写', 'path': str(backup_dir), 'writable': True},
            [],
            None,
        )
    except OSError as e:
        return (
            {'status': 'unhealthy', 'message': f'备份目录不可写: {str(e)}', 'path': str(backup_dir), 'writable': False},
            [f'备份目录不可写: {str(e)}'],
            'degraded',
        )


async def _check_database() -> tuple[dict, list[str], str | None]:
    """检查数据库连接状态，返回 (check_result, issues, severity)"""
    from sqlalchemy import text

    from fastapi_app.core.database import get_async_db_context

    try:
        async with get_async_db_context() as db:
            result = await db.execute(text('SELECT 1'))
            db_ok = result.scalar() == 1

        if db_ok:
            return ({'status': 'healthy', 'message': '数据库连接正常', 'connected': True}, [], None)
        return (
            {'status': 'unhealthy', 'message': '数据库连接失败', 'connected': False},
            ['数据库连接失败'],
            'unhealthy',
        )
    except (SQLAlchemyError, OSError, RuntimeError) as e:
        return (
            {'status': 'unhealthy', 'message': f'数据库连接检查失败: {str(e)}', 'error': str(e)},
            [f'数据库连接检查失败: {str(e)}'],
            'unhealthy',
        )


async def _check_redis() -> tuple[dict, list[str], str | None]:
    """检查Redis连接状态，返回 (check_result, issues, severity)"""
    try:
        from fastapi_app.core.redis_wrapper import ping
    except ImportError:
        return (
            {'status': 'warning', 'message': 'Redis模块未安装，进度追踪功能不可用', 'connected': False},
            ['Redis模块未安装'],
            'degraded',
        )

    try:
        redis_ok = await ping(context="备份健康检查")
        if redis_ok:
            return ({'status': 'healthy', 'message': 'Redis连接正常', 'connected': True}, [], None)
        return (
            {'status': 'warning', 'message': 'Redis连接不可用（不影响核心功能）', 'connected': False},
            ['Redis连接不可用，进度追踪功能可能受限'],
            'degraded',
        )
    except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
        return (
            {'status': 'warning', 'message': f'Redis连接检查失败: {str(e)}', 'error': str(e)},
            [f'Redis连接检查失败: {str(e)}'],
            'degraded',
        )


def _check_last_backup() -> tuple[dict, list[str], str | None]:
    """检查最近备份时间，返回 (check_result, issues, severity)"""
    try:
        backup_files = backup_service.list_backup_files()
        if backup_files:
            latest_backup = max(backup_files, key=lambda x: x.get('mtime', 0))
            latest_time = datetime.fromtimestamp(latest_backup.get('mtime', 0))
            hours_since = (datetime.now() - latest_time).total_seconds() / 3600
            within_24h = hours_since <= 24
            check = {
                'status': 'healthy' if within_24h else 'warning',
                'message': f'最近备份时间: {latest_time.strftime("%Y-%m-%d %H:%M:%S")}',
                'latest_backup_time': latest_time.isoformat(),
                'hours_since_last_backup': round(hours_since, 2),
                'within_24h': within_24h,
            }
            if within_24h:
                return (check, [], None)
            return (
                check,
                [f'最近备份时间超过24小时（{round(hours_since, 1)}小时前）'],
                'degraded',
            )
        else:
            return (
                {'status': 'warning', 'message': '未找到备份文件', 'latest_backup_time': None, 'hours_since_last_backup': None, 'within_24h': False},
                ['未找到任何备份文件'],
                'degraded',
            )
    except OSError as e:
        return (
            {'status': 'unhealthy', 'message': f'检查最近备份时间失败: {str(e)}', 'error': str(e)},
            [f'检查最近备份时间失败: {str(e)}'],
            'unhealthy',
        )


def _check_backup_integrity() -> tuple[dict, list[str], str | None]:
    """抽样检查备份文件完整性，返回 (check_result, issues, severity)"""
    import random

    try:
        backup_files = backup_service.list_backup_files()
        if not backup_files:
            return (
                {'status': 'warning', 'message': '没有备份文件可检查', 'sample_size': 0, 'results': []},
                [],
                None,
            )

        sample_files = random.sample(backup_files, min(3, len(backup_files)))
        integrity_results = []
        severity = None

        for file_info in sample_files:
            filename = file_info.get('name', '')
            filepath = backup_service.BACKUP_DIR / filename
            try:
                if filepath.exists() and filepath.is_file():
                    integrity_results.append({
                        'filename': filename,
                        'status': 'healthy',
                        'size': filepath.stat().st_size,
                        'readable': True,
                        'message': '文件完整可读',
                    })
                else:
                    integrity_results.append({
                        'filename': filename,
                        'status': 'unhealthy',
                        'size': 0,
                        'readable': False,
                        'message': '文件不存在或不是普通文件',
                    })
                    severity = 'degraded'
            except OSError as e:
                integrity_results.append({
                    'filename': filename,
                    'status': 'unhealthy',
                    'size': 0,
                    'readable': False,
                    'message': f'文件检查失败: {str(e)}',
                    'error': str(e),
                })
                severity = 'degraded'

        all_healthy = all(result['status'] == 'healthy' for result in integrity_results)
        issues = [f'备份文件异常: {result["filename"]}' for result in integrity_results if result['status'] != 'healthy']
        issues += [f'备份文件检查失败 {result["filename"]}: {result.get("error", "")}' for result in integrity_results if 'error' in result]

        return (
            {
                'status': 'healthy' if all_healthy else 'degraded',
                'message': f'抽样检查了 {len(integrity_results)} 个备份文件',
                'sample_size': len(integrity_results),
                'results': integrity_results,
            },
            issues,
            severity,
        )
    except Exception as e:  # defensive: health check helper must report failure without crashing
        return (
            {'status': 'unhealthy', 'message': f'备份文件完整性检查失败: {str(e)}', 'error': str(e)},
            [f'备份文件完整性检查失败: {str(e)}'],
            'unhealthy',
        )


def _check_disk_space() -> tuple[dict, list[str], str | None]:
    """检查磁盘空间，返回 (check_result, issues, severity)"""
    import shutil

    try:
        backup_dir = backup_service.BACKUP_DIR
        if not backup_dir.exists():
            return (
                {'status': 'warning', 'message': '备份目录不存在，无法检查磁盘空间', 'sufficient': None},
                [],
                None,
            )

        disk_usage = shutil.disk_usage(backup_dir)
        total_gb = disk_usage.total / (1024**3)
        used_gb = disk_usage.used / (1024**3)
        free_gb = disk_usage.free / (1024**3)
        free_percent = (disk_usage.free / disk_usage.total) * 100

        if free_percent <= 5:
            return (
                {
                    'status': 'warning',
                    'message': f'磁盘空间: {free_gb:.1f}GB 可用 ({free_percent:.1f}%)',
                    'total_gb': round(total_gb, 2), 'used_gb': round(used_gb, 2),
                    'free_gb': round(free_gb, 2), 'free_percent': round(free_percent, 2),
                    'sufficient': free_percent > 10,
                },
                [f'磁盘空间严重不足: 仅剩 {free_percent:.1f}% 可用空间'],
                'unhealthy',
            )
        if free_percent <= 10:
            return (
                {
                    'status': 'warning',
                    'message': f'磁盘空间: {free_gb:.1f}GB 可用 ({free_percent:.1f}%)',
                    'total_gb': round(total_gb, 2), 'used_gb': round(used_gb, 2),
                    'free_gb': round(free_gb, 2), 'free_percent': round(free_percent, 2),
                    'sufficient': free_percent > 10,
                },
                [f'磁盘空间不足: 仅剩 {free_percent:.1f}% 可用空间'],
                'degraded',
            )
        return (
            {
                'status': 'healthy',
                'message': f'磁盘空间: {free_gb:.1f}GB 可用 ({free_percent:.1f}%)',
                'total_gb': round(total_gb, 2), 'used_gb': round(used_gb, 2),
                'free_gb': round(free_gb, 2), 'free_percent': round(free_percent, 2),
                'sufficient': True,
            },
            [],
            None,
        )
    except OSError as e:
        return (
            {'status': 'warning', 'message': f'磁盘空间检查失败: {str(e)}', 'error': str(e)},
            [f'磁盘空间检查失败: {str(e)}'],
            'degraded',
        )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
@router.get('/health', response_model=BackupHealthCheckResponse)
async def health_check(
    user: User = Depends(require_backup_permission('health_check')),
) -> dict:
    """
    备份系统健康检查端点
    检查项目：
    1. 备份目录可写性
    2. 数据库连接状态
    3. Redis连接状态（用于进度追踪）
    4. 最近备份时间（不超过24小时）
    5. 备份文件完整性
    """
    checks = {}
    issues = []
    overall_status = "healthy"

    check_runners = [
        ('backup_dir', _check_backup_dir),
        ('database', _check_database),
        ('redis', _check_redis),
        ('last_backup', _check_last_backup),
        ('backup_integrity', _check_backup_integrity),
        ('disk_space', _check_disk_space),
    ]

    for name, runner in check_runners:
        try:
            check_result, check_issues, severity = await runner()
        except Exception as e:  # defensive: health check runner must not crash the whole endpoint
            check_result = {'status': 'unhealthy', 'message': f'{name}检查异常: {safe_exception_message(e)}', 'error': str(e)}
            check_issues = [f'{name}检查异常: {safe_exception_message(e)}']
            severity = 'unhealthy'

        checks[name] = check_result
        issues.extend(check_issues)
        if severity == 'unhealthy':
            overall_status = 'unhealthy'
        elif severity == 'degraded' and overall_status == 'healthy':
            overall_status = 'degraded'

    return {
        'status': overall_status,
        'timestamp': datetime.now().isoformat(),
        'checks': checks,
        'issues': issues,
    }


# ---------------------------------------------------------------------------
# 验证缓存管理
# ---------------------------------------------------------------------------

class ValidationCache:
    """备份验证结果缓存"""
    
    def __init__(self, ttl_seconds: int = 3600):  # 默认1小时缓存
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, cache_key: str) -> Optional[dict]:
        """获取缓存项，过期返回 None。"""
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if time.time() - entry['timestamp'] < self.ttl:
                return entry['data']
            else:
                # 缓存过期
                del self.cache[cache_key]
        return None

    def set(self, cache_key: str, data: dict) -> None:
        """设置缓存项。"""
        self.cache[cache_key] = {
            'data': data,
            'timestamp': time.time()
        }

    def clear(self) -> None:
        """清空缓存。"""
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


def _resolve_validation_password(x_backup_password: Optional[str]) -> Optional[str]:
    """解析验证用密码：优先请求头，其次环境变量。"""
    if x_backup_password:
        return x_backup_password
    return os.environ.get('BACKUP_ENCRYPTION_PASSWORD')


def _build_validation_failure(filename: str, file_size: int, issue: str) -> dict:
    """构建验证失败的响应字典。"""
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
        'issues': [issue],
    }


def _decrypt_for_validation(
    content: bytes, x_backup_password: Optional[str], filename: str, file_size: int,
) -> tuple[bytes, Optional[dict]]:
    """解密加密备份用于验证。返回 (内容, 失败响应)。失败响应非 None 时应直接返回。"""
    password_to_use = _resolve_validation_password(x_backup_password)
    if not password_to_use:
        return content, _build_validation_failure(filename, file_size, '文件已加密但未提供密码')
    try:
        return _decrypt_backup_data(content, password_to_use), None
    except (ValueError, TypeError, OSError) as e:
        return content, _build_validation_failure(filename, file_size, f'解密失败: {str(e)}')


def _validate_zip_content(content: bytes) -> tuple[list[str], bool]:
    """验证 ZIP 备份内容完整性，返回 (issues, valid)。"""
    issues: list[str] = []
    valid = True
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
            namelist = zip_file.namelist()
            if 'manifest.json' not in namelist:
                issues.append('ZIP文件缺少manifest.json')
                valid = False
            for zip_info in zip_file.infolist():
                try:
                    with zip_file.open(zip_info.filename) as member_file:
                        member_file.read()  # 尝试读取文件
                except (OSError, zipfile.BadZipFile, RuntimeError) as e:
                    issues.append(f'文件 {zip_info.filename} 损坏: {str(e)}')
                    valid = False
    except zipfile.BadZipFile as e:
        issues.append(f'ZIP文件损坏: {str(e)}')
        valid = False
    except (OSError, ValueError, TypeError) as e:
        issues.append(f'文件验证失败: {str(e)}')
        valid = False
    return issues, valid


def _validate_json_content(content: bytes) -> tuple[list[str], bool]:
    """验证 JSON 备份内容，返回 (issues, valid)。"""
    issues: list[str] = []
    valid = True
    try:
        backup_data = json.loads(content.decode('utf-8'))
        if 'tables' not in backup_data:
            issues.append('JSON文件缺少tables字段')
            valid = False
    except json.JSONDecodeError as e:
        issues.append(f'JSON解析失败: {str(e)}')
        valid = False
    except (OSError, ValueError, TypeError) as e:
        issues.append(f'文件验证失败: {str(e)}')
        valid = False
    return issues, valid


def _validate_backup_content(content: bytes, filename: str) -> tuple[list[str], bool]:
    """根据文件扩展名分派格式验证，返回 (issues, valid)。"""
    if filename.endswith('.zip') or filename.endswith('.zip.enc'):
        return _validate_zip_content(content)
    if filename.endswith('.json') or filename.endswith('.json.enc'):
        return _validate_json_content(content)
    return ['不支持的文件格式'], False


def _extract_backup_metadata(content: bytes, filename: str) -> tuple:
    """从备份内容提取元数据，返回 (format_version, table_count, total_rows, created_at)。"""
    if filename.endswith('.zip') or filename.endswith('.zip.enc'):
        with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
            if 'manifest.json' in zip_file.namelist():
                with zip_file.open('manifest.json') as member_file:
                    manifest = json.load(member_file)
                    return (
                        manifest.get('format_version'),
                        manifest.get('table_count'),
                        manifest.get('total_rows'),
                        manifest.get('exported_at'),
                    )
        return None, None, None, None
    if filename.endswith('.json') or filename.endswith('.json.enc'):
        backup_data = json.loads(content.decode('utf-8'))
        return (
            backup_data.get('format_version', '1.0'),
            len(backup_data.get('tables', {})),
            sum(len(table_data.get('data', [])) for table_data in backup_data.get('tables', {}).values()),
            backup_data.get('exported_at'),
        )
    return None, None, None, None


# ---------------------------------------------------------------------------
# GET /validate/{filename}
# ---------------------------------------------------------------------------
@router.get('/validate/{filename}', response_model=BackupValidationResponse)
async def validate_backup_file(
    filename: str,
    x_backup_password: Optional[str] = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('validate_backup_file')),
) -> dict:
    """
    验证服务器上已有备份文件的完整性
    支持加密备份的解密验证（密码通过 X-Backup-Password 请求头提供）
    """
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')

    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')

    cache_key = _get_validation_cache_key(filename, x_backup_password)
    cached_result = _validation_cache.get(cache_key)
    if cached_result:
        cached_result['cache_hit'] = True
        return cached_result

    try:
        content = filepath.read_bytes()
        file_size = len(content)

        encrypted = _is_encrypted_data(content)
        if encrypted:
            content, failure = _decrypt_for_validation(content, x_backup_password, filename, file_size)
            if failure is not None:
                return failure

        # 计算校验和
        checksum = hashlib.sha256(content).hexdigest()

        # 验证文件格式
        issues, valid = _validate_backup_content(content, filename)

        # 尝试提取元数据
        if valid:
            try:
                format_version, table_count, total_rows, created_at = _extract_backup_metadata(content, filename)
            except (ValueError, TypeError, OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
                format_version, table_count, total_rows, created_at = None, None, None, None
        else:
            format_version, table_count, total_rows, created_at = None, None, None, None

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

    except Exception as e:  # defensive: endpoint must convert any validation error to HTTPException
        logger.error(f'验证备份文件失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail=f'验证备份文件失败: {str(e)}') from e


# ---------------------------------------------------------------------------
# POST /validate-integrity
# ---------------------------------------------------------------------------
@router.post('/validate-integrity', response_model=BackupIntegrityCheckResponse)
async def validate_backup_integrity(
    user: User = Depends(require_backup_permission('validate_backup_integrity')),
) -> dict:
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
            '_'.join(sorted(file['name'] for file in backup_files)).encode()
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
                    
                except (OSError, ValueError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as e:
                    corrupted_files.append(filename)
                    details.append({
                        'filename': filename,
                        'status': 'corrupted',
                        'message': f'读取失败: {str(e)}',
                        'size': file_size,
                        'error': str(e)
                    })
                
            except Exception as e:  # defensive: per-file iteration must continue despite unexpected errors
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
        
    except Exception as e:  # defensive: endpoint must convert any integrity check error to HTTPException
        logger.error(f'完整性检查失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail=f'完整性检查失败: {str(e)}') from e


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------
@router.get('/stats', response_model=BackupStatisticsResponse)
async def get_backup_statistics(
    user: User = Depends(require_backup_permission('get_backup_statistics')),
    db: AsyncSession = Depends(get_async_read_db),
) -> dict:
    """
    获取备份统计信息
    """
    from datetime import datetime
    from collections import defaultdict
    import shutil

    try:
        # 1. 获取备份文件列表
        backup_files = backup_service.list_backup_files()

        # 2. 计算基本统计
        total_backups = len(backup_files)
        total_size_bytes = sum(file.get('size', 0) for file in backup_files)

        # 3. 计算最近备份时间
        last_backup_time = None
        if backup_files:
            latest_backup = max(backup_files, key=lambda x: x.get('mtime', 0))
            last_backup_time = datetime.fromtimestamp(latest_backup.get('mtime', 0)).isoformat()

        # 4-5. 备份记录统计（成功率、类型分布）下沉到 service 层
        records_stats = await backup_service.get_backup_statistics_records(db, days=30)
        total_records = records_stats['total_records']
        success_records = records_stats['success_records']
        backup_success_rate = records_stats['success_rate']
        type_distribution = records_stats['type_distribution']

        # 6. 计算存储使用情况
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
            except OSError as e:
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

    except Exception as e:  # defensive: endpoint must convert any stats error to HTTPException
        logger.error(f'获取备份统计信息失败: %s', safe_exception_message(e))
        raise HTTPException(status_code=500, detail=f'获取备份统计信息失败: {str(e)}') from e
