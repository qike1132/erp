"""备份创建与导出路由。

从原 backup.py 拆分，URL / schema / 权限码保持不变：
- GET  /export                  一键备份全部数据（磁盘流式返回）
- POST /save                    一键备份到服务器默认路径
- POST /save-incremental        增量备份
- GET  /export-info             获取备份文件信息（分片数量等）
- GET  /export-chunk/{i}        下载备份文件的指定分片
- GET  /export-enhanced         支持 Range 请求头的增强备份导出
"""
import asyncio
import contextlib
import hashlib
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import (
    _encrypt_backup_data,
    _get_encryption_password,
    require_backup_permission,
)
from fastapi_app.core.database import get_async_db
from fastapi_app.schemas.backup import (
    BackupChunkInfo,
    BackupSaveResponse,
    IncrementalBackupResponse,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import BackupError
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def _export_backup_to_response(
    db: AsyncSession,
    user: User,
    remark: str,
    format: str,
    encrypt: bool,
    password: str | None,
    x_backup_password: str | None,
    register_temp: Callable[[Path], Path],
) -> FileResponse:
    """导出备份（JSON/ZIP）并返回 FileResponse。

    公共逻辑从 export_backup / export_backup_enhanced 提取，
    两个端点仅差异在权限名与临时文件清理方式（由 register_temp 登记）。
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if format == 'json':
        try:
            json_bytes = await backup_service.execute_legacy_backup_to_bytes(user, remark, db)
        except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
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
        tmp_path_obj = register_temp(Path(tmp_path))
        await asyncio.to_thread(tmp_path_obj.write_bytes, json_bytes)

        return FileResponse(
            path=str(tmp_path_obj),
            filename=filename,
            media_type=media_type,
        )

    # ZIP 格式：直接写入临时文件并按需加密，避免将完整文件读入内存
    encryption_password = _get_encryption_password(password, x_backup_password) if encrypt else None
    try:
        zip_path, _manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error(f'ZIP 备份导出失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

    register_temp(zip_path)

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
# GET /export
# ---------------------------------------------------------------------------
@router.get('/export')
async def export_backup(
    background_tasks: BackgroundTasks,
    remark: str = '',
    format: str = 'zip',
    encrypt: bool = Query(True, description="是否启用加密"),
    password: str | None = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
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
    temp_files: list[str] = []

    def _register_temp_file(path: Path) -> Path:
        temp_files.append(str(path))
        return path

    def _cleanup_temp_files():
        for p in temp_files:
            with contextlib.suppress(OSError):
                os.unlink(p)

    background_tasks.add_task(_cleanup_temp_files)
    return await _export_backup_to_response(
        db, user, remark, format, encrypt, password, x_backup_password, _register_temp_file,
    )


# ---------------------------------------------------------------------------
# POST /save
# ---------------------------------------------------------------------------
@router.post('/save', response_model=BackupSaveResponse)
async def save_backup_to_server(
    remark: str = '',
    encrypt: bool = Query(True, description="是否启用加密"),
    password: str | None = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
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
# POST /save-incremental
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
    password: str | None = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
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
        backup_path, _manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error(f'获取备份信息失败: {e}')
        raise HTTPException(status_code=500, detail='获取备份信息失败') from e

    background_tasks.add_task(lambda p=backup_path: p.exists() and os.unlink(p))

    try:
        total_size = os.path.getsize(backup_path)
        chunk_size = _get_chunk_size()
        total_chunks = (total_size + chunk_size - 1) // chunk_size
        checksum = await asyncio.to_thread(_sha256_file, backup_path)
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
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
    password: str | None = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
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
        backup_path, _manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
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
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
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
    password: str | None = Query(None, description="加密密码，为空时使用环境变量或生成临时密码"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup_enhanced')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    增强的备份导出端点，支持Range请求头和分片下载
    基于 FileResponse 磁盘流式传输，由 Starlette 自动处理 Range 请求。
    """
    datetime.now().strftime('%Y%m%d_%H%M%S')
    temp_files: list[str] = []

    def _register_temp_file(path: Path) -> Path:
        temp_files.append(str(path))
        return path

    background_tasks.add_task(lambda: [os.unlink(p) for p in temp_files if os.path.exists(p)])
    return await _export_backup_to_response(
        db, user, remark, format, encrypt, password, x_backup_password, _register_temp_file,
    )
