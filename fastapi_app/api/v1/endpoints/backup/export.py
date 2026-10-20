"""备份创建与导出路由。

从原 backup.py 拆分，URL / schema / 权限码保持不变：
- GET  /export                  一键备份全部数据（磁盘流式返回）
- POST /save                    一键备份到服务器默认路径
- GET  /export-info             获取备份文件信息（分片数量等）
- GET  /export-chunk/{i}        下载备份文件的指定分片
- GET  /export-enhanced         支持 Range 请求头的增强备份导出
"""
import asyncio
import contextlib
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from fastapi_app.api.v1.endpoints.backup._deps import (
    _encrypt_backup_data,
    _resolve_encryption,
    require_backup_permission,
)
from fastapi_app.core.audit_middleware import _buffer_audit_entry
from fastapi_app.core.backup_progress import _sanitize_error
from fastapi_app.core.database import get_async_db
from fastapi_app.core.response import success_response
from fastapi_app.schemas.backup import (
    BackupChunkInfo,
    BackupChunkResponse,
    BackupSaveResponse,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import BackupError
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def _audit_export_download(
    request: Request,
    user: User,
    *,
    filename: str,
    format: str,
    encrypted: bool,
    size: int,
    remark: str,
) -> None:
    """下载整库备份属高敏读操作，显式写审计记录。

    AuditLogMiddleware 只审计写方法（POST/PUT/PATCH/DELETE），GET /export
    下载整库备份若无显式审计将不可追溯。审计失败仅告警，不影响下载。
    """
    try:
        client_ip = request.client.host if request.client else None
        if forwarded := request.headers.get('x-forwarded-for'):
            client_ip = forwarded.split(',')[0].strip()
        entry = {
            'user_id': getattr(user, 'id', None),
            'username': getattr(user, 'username', None),
            'action': 'EXPORT',
            'resource_type': 'backup',
            'resource_id': None,
            'detail': json.dumps({
                'filename': filename,
                'format': format,
                'encrypted': encrypted,
                'size': size,
                'remark': remark,
            }, ensure_ascii=False),
            'ip_address': client_ip,
            'user_agent': request.headers.get('user-agent', '')[:500],
            'request_id': getattr(request.state, 'request_id', None),
            'status_code': 200,
            'created_at': datetime.now(UTC),  # aware UTC：audit_log.created_at 列为 timestamptz
        }
        await _buffer_audit_entry(entry)
    except Exception as e:  # defensive: 审计失败不能阻断下载
        logger.warning('备份导出审计记录失败: %s', e)


async def _export_backup_to_response(
    request: Request,
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
    effective_encrypt, encryption_password = _resolve_encryption(encrypt, password, x_backup_password)

    if format == 'json':
        try:
            json_bytes = await backup_service.execute_legacy_backup_to_bytes(user, remark, db)
        except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
            logger.error(f'JSON 备份导出失败: {e}')
            raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

        # _resolve_encryption 约定：encrypted=True 时密码必为真值（密码缺失会降级为 False）
        if effective_encrypt and encryption_password:
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

        await _audit_export_download(
            request, user, filename=filename, format='json',
            encrypted=effective_encrypt, size=len(json_bytes), remark=remark,
        )
        return FileResponse(
            path=str(tmp_path_obj),
            filename=filename,
            media_type=media_type,
        )

    # ZIP 格式：直接写入临时文件并按需加密，避免将完整文件读入内存
    try:
        zip_path, _manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=effective_encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error(f'ZIP 备份导出失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

    register_temp(zip_path)

    if effective_encrypt:
        filename = f'erp_backup_{timestamp}.zip.enc'
        media_type = 'application/octet-stream'
    else:
        filename = f'erp_backup_{timestamp}.zip'
        media_type = 'application/zip'

    await _audit_export_download(
        request, user, filename=filename, format='zip',
        encrypted=effective_encrypt, size=zip_path.stat().st_size, remark=remark,
    )
    return FileResponse(
        path=str(zip_path),
        filename=filename,
        media_type=media_type,
    )


# ---------------------------------------------------------------------------
# GET /download/{filename}
# ---------------------------------------------------------------------------
@router.get('/download/{filename}')
async def download_server_backup(
    filename: str,
    request: Request,
    user: User = Depends(require_backup_permission('download_server_backup')),
):
    """按文件名下载服务器上已有的备份文件（P2-1：备份记录表下载入口接通）

    与 GET /export（每次现场生成新备份）不同，本端点直接回放既有文件；
    整库文件属高敏读操作，与 /export 一致显式写 EXPORT 审计。
    """
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        size = filepath.stat().st_size
    except OSError as e:
        raise HTTPException(status_code=400, detail=_sanitize_error(f'读取备份文件失败: {e}')) from e

    await _audit_export_download(
        request, user, filename=safe_name, format='file',
        encrypted=safe_name.endswith('.enc'), size=size, remark='download-by-name',
    )
    media_type = (
        'application/zip' if safe_name.endswith('.zip')
        else 'application/json' if safe_name.endswith('.json')
        else 'application/octet-stream'
    )
    return FileResponse(path=str(filepath), filename=safe_name, media_type=media_type)


# ---------------------------------------------------------------------------
# GET /export
# ---------------------------------------------------------------------------
@router.get('/export')
async def export_backup(
    background_tasks: BackgroundTasks,
    request: Request,
    remark: str = '',
    format: str = 'zip',
    encrypt: bool = Query(False, description="是否启用加密（默认不加密；总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    一键备份全部数据（磁盘流式返回，避免大文件 OOM）

    参数：
    - remark: 备份备注
    - format: 备份格式，支持 'zip' 或 'json'
    - encrypt: 是否启用加密，默认False（总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）
    - x_backup_password: 加密密码（请求头，H3：已移除 URL query 形式，避免密码进入访问日志/浏览器历史）

    加密密码获取优先级：
    1. X-Backup-Password请求头
    2. BACKUP_ENCRYPTION_PASSWORD环境变量
    3. 均未配置时不加密（记录告警日志）

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
    # H3：GET 端点密码仅走 X-Backup-Password 头/环境变量
    return await _export_backup_to_response(
        request, db, user, remark, format, encrypt, None, x_backup_password, _register_temp_file,
    )


# ---------------------------------------------------------------------------
# POST /save
# ---------------------------------------------------------------------------
@router.post('/save', response_model=BackupSaveResponse)
async def save_backup_to_server(
    remark: str = '',
    encrypt: bool = Query(False, description="是否启用加密（默认不加密；总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）"),
    password: str | None = Body(None, description="加密密码（H3：经 body 传递，避免进入访问日志/浏览器历史；为空时依次使用请求头/环境变量，均未配置时不加密）"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('save_backup_to_server')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    一键备份到服务器默认路径

    参数：
    - remark: 备份备注
    - encrypt: 是否启用加密，默认False（总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）
    - password: 加密密码（请求体，H3）
    - x_backup_password: 加密密码（请求头）

    加密密码获取优先级：
    1. password请求体字段
    2. X-Backup-Password请求头
    3. BACKUP_ENCRYPTION_PASSWORD环境变量
    4. 均未配置时不加密（记录告警日志）

    权限：backup_create
    """
    backup_service.ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # P0-1 加密决策单点化：端点先解析意图，加密由服务层一次性完成。
    # 旧路径服务层可能用随机密钥自行加密、端点又降级明文把密文存成 .zip
    # （双重加密/不可还原两种缺陷并存），此改动后加密层唯一、语义与 M1 任务路径一致。
    effective_encrypt, encryption_password = _resolve_encryption(encrypt, password, x_backup_password)
    try:
        zip_bytes, manifest = await backup_service.create_full_backup(
            db, user, remark,
            encrypt=effective_encrypt,
            encrypt_password=encryption_password,
        )
    except (BackupError, RuntimeError, OSError) as e:
        logger.error(f'服务端备份失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e

    if manifest.get('encrypted'):
        filename = f'erp_backup_{timestamp}.zip.enc'
    else:
        filename = f'erp_backup_{timestamp}.zip'
    file_bytes = zip_bytes

    filepath = backup_service.BACKUP_DIR / filename
    await asyncio.to_thread(filepath.write_bytes, file_bytes)
    backup_service.write_backup_meta_file(filepath, manifest, record_type='full')

    # 写入 BackupRecord
    # S4：状态由产物自述推导（缺表/覆盖度不足 → partial），不再默认成功
    export_status, export_detail = backup_service.evaluate_backup_completeness(manifest)
    await backup_service.write_backup_record(
        db, record_type='full', trigger_type='manual',
        filename=filename, size=len(file_bytes),
        table_count=manifest.get('table_count', 0),
        total_rows=manifest.get('total_rows', 0),
        operator=user.username if hasattr(user, 'username') else str(user.id),
        remark=backup_service.compose_remark(remark, export_detail),
        status=export_status,
        encrypted=manifest.get('encrypted', False),
    )

    return success_response(**{ 'format': 'zip', 'filename': filename,
        'size': len(file_bytes),
        'encrypted': manifest.get('encrypted', False),
        'table_count': manifest.get('table_count', 0),
        'total_rows': manifest.get('total_rows', 0),
        'exported_at': manifest.get('exported_at'),
        'exported_by': manifest.get('exported_by'),
        'includes': manifest.get('includes', {}), 'remark': remark,
        'backup_status': export_status,
        'failed_tables': manifest.get('failed_tables') or []})


# ---------------------------------------------------------------------------
# 分片传输相关辅助函数
# ---------------------------------------------------------------------------

def _get_chunk_size() -> int:
    """获取分片大小，默认为10MB"""
    return 10 * 1024 * 1024  # 10MB


# P0-3: 分片下载会话缓存。
# 旧实现每个 export-chunk 请求都重新执行一次完整备份再切片——N 片 = N 次全量
# 导出，且各片数据来自不同时刻、与 export-info 的整包 checksum 对不上。
# 现在 export-info 生成一次并登记 bundle（Redis 共享、跨 worker），export-chunk
# 按 bundle_id 从磁盘缓存切片；Redis 不可用或 bundle 过期时回退旧行为（重新生成）。
_CHUNK_BUNDLE_TTL_SECONDS = 30 * 60
_CHUNK_BUNDLE_DIR = Path(tempfile.gettempdir()) / 'erp_export_bundles'


def _bundle_redis_key(bundle_id: str) -> str:
    return f'erp:backup_export_bundle:{bundle_id}'


async def _register_chunk_bundle(path: Path, *, filename: str, total_size: int,
                                 chunk_size: int, total_chunks: int, checksum: str) -> str | None:
    """将生成好的备份文件登记为分片下载 bundle，返回 bundle_id；Redis 不可用时返回 None。"""
    import secrets

    bundle_id = secrets.token_urlsafe(12)
    payload = {
        'path': str(path), 'filename': filename, 'total_size': total_size,
        'chunk_size': chunk_size, 'total_chunks': total_chunks, 'checksum': checksum,
    }
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is None:
            return None
        await client.set(_bundle_redis_key(bundle_id), json.dumps(payload), ex=_CHUNK_BUNDLE_TTL_SECONDS)
        return bundle_id
    except Exception as e:  # broad-except: 缓存登记失败降级为旧分片行为
        logger.warning(f'登记分片 bundle 失败（回退逐片生成）: {e}')
        return None


async def _load_chunk_bundle(bundle_id: str) -> dict | None:
    """读取 bundle 登记信息；不存在/过期/Redis 不可用返回 None。"""
    try:
        from fastapi_app.core.backup_progress import _get_redis
        client = await _get_redis()
        if client is None:
            return None
        raw = await client.get(_bundle_redis_key(bundle_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:  # broad-except: 缓存读取失败降级为旧分片行为
        logger.warning(f'读取分片 bundle 失败（回退逐片生成）: {e}')
        return None


async def _sweep_chunk_bundle_files() -> None:
    """清理 bundle 目录中超过 TTL 的残留文件（多 worker 共享磁盘，任一 worker 清扫均安全）。"""
    def _sweep() -> None:
        import time as _time
        if not _CHUNK_BUNDLE_DIR.is_dir():
            return
        cutoff = _time.time() - _CHUNK_BUNDLE_TTL_SECONDS
        for f in _CHUNK_BUNDLE_DIR.iterdir():
            try:
                if f.is_file() and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                continue
    try:
        _CHUNK_BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(_sweep)
    except OSError as e:
        logger.warning(f'清扫分片 bundle 目录失败: {e}')


# ---------------------------------------------------------------------------
# GET /export-info
# ---------------------------------------------------------------------------
@router.get('/export-info', response_model=BackupChunkInfo)
async def get_backup_info(
    background_tasks: BackgroundTasks,
    remark: str = '',
    encrypt: bool = Query(False, description="是否启用加密（默认不加密；总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）"),
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

    effective_encrypt, encryption_password = _resolve_encryption(encrypt, None, x_backup_password)
    try:
        backup_path, _manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=effective_encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error(f'获取备份信息失败: {e}')
        raise HTTPException(status_code=500, detail='获取备份信息失败') from e

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
        if effective_encrypt else
        f'erp_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
    )

    # P0-3: 登记分片 bundle（文件移入专用目录，TTL 后由惰性清扫回收），
    # 后续 export-chunk 直接切片同一份文件，保证各片与整包 checksum 一致
    bundle_id = None
    try:
        await _sweep_chunk_bundle_files()
        bundle_dest = _CHUNK_BUNDLE_DIR / f'{os.path.basename(backup_path)}.bundle'
        if bundle_dest.exists():
            bundle_dest.unlink()
        backup_path.rename(bundle_dest)
        bundle_id = await _register_chunk_bundle(
            bundle_dest, filename=filename, total_size=total_size,
            chunk_size=chunk_size, total_chunks=total_chunks, checksum=checksum,
        )
        if bundle_id is None:
            # Redis 不可用：文件交给请求结束清理，分片回退逐片生成
            def _cleanup_bundle(p: Path = bundle_dest) -> None:
                if p.exists():
                    os.unlink(p)
            background_tasks.add_task(_cleanup_bundle)
    except OSError as e:
        logger.warning(f'登记分片 bundle 失败（回退逐片生成）: {e}')
        bundle_id = None

    return {
        'filename': filename,
        'total_size': total_size,
        'chunk_size': chunk_size,
        'total_chunks': total_chunks,
        'encrypted': effective_encrypt,
        'checksum': checksum,
        'bundle_id': bundle_id,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ---------------------------------------------------------------------------
# GET /export-chunk/{chunk_index}
# ---------------------------------------------------------------------------
@router.get('/export-chunk/{chunk_index}')
async def export_backup_chunk(
    chunk_index: int,
    background_tasks: BackgroundTasks,
    bundle_id: str | None = Query(None, description="export-info 返回的分片会话 ID，命中缓存则直接切片，避免每片重新全量备份"),
    remark: str = '',
    encrypt: bool = Query(False, description="是否启用加密（默认不加密；总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup_chunk')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    下载备份文件的指定分片
    """
    if chunk_index < 0:
        raise HTTPException(status_code=400, detail='分片索引不能为负数')

    # P0-3: 优先从 bundle 缓存切片（export-info 已生成好的同一份文件）。
    # Z05-R11：给了 bundle_id 但 Redis/文件已失效时，不得静默回退为「每个分片重新
    # 全量备份」——那会让 backups/ 随分片数线性膨胀。直接 410 让客户端重新 export-info。
    if bundle_id:
        bundle = await _load_chunk_bundle(bundle_id)
        if not bundle:
            raise HTTPException(status_code=410, detail='分片会话已过期，请重新获取备份信息')
        bundle_path = Path(bundle['path'])
        if not bundle_path.is_file():
            logger.warning(f'分片 bundle 文件已不存在: {bundle_id}')
            raise HTTPException(status_code=410, detail='分片会话文件已清理，请重新获取备份信息')

        total_size = bundle['total_size']
        chunk_size = bundle['chunk_size']
        total_chunks = bundle['total_chunks']
        if chunk_index >= total_chunks:
            raise HTTPException(status_code=416, detail=f'分片索引超出范围，最大索引为{total_chunks - 1}')

        start = chunk_index * chunk_size
        end = min(start + chunk_size, total_size) - 1

        def _read_cached_chunk(path: Path, _start: int, length: int) -> bytes:
            with open(path, 'rb') as f:
                f.seek(_start)
                return f.read(length)

        try:
            chunk_data = await asyncio.to_thread(_read_cached_chunk, bundle_path, start, end - start + 1)
        except OSError as e:
            logger.warning(f'读取分片 bundle 失败: {e}')
            raise HTTPException(status_code=410, detail='分片会话读取失败，请重新获取备份信息') from e
        return BackupChunkResponse(
            success=True,
            chunk_index=chunk_index,
            chunk_data=chunk_data,
            total_chunks=total_chunks,
            chunk_size=len(chunk_data),
            is_last=(chunk_index == total_chunks - 1),
        )

    # 回退路径（无 bundle_id 的旧客户端）：保持旧行为，现场生成
    effective_encrypt, encryption_password = _resolve_encryption(encrypt, None, x_backup_password)
    try:
        backup_path, _manifest = await backup_service.create_full_backup_to_file(
            db, user, remark,
            encrypt=effective_encrypt,
            encrypt_password=encryption_password,
        )
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error(f'生成备份分片失败: {e}')
        raise HTTPException(status_code=500, detail='生成备份分片失败') from e

    def _cleanup_backup_path(p: Path = backup_path) -> None:
        if p.exists():
            os.unlink(p)
    background_tasks.add_task(_cleanup_backup_path)

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
    request: Request,
    remark: str = '',
    format: str = 'zip',
    encrypt: bool = Query(False, description="是否启用加密（默认不加密；总开关 BACKUP_ENCRYPTION_ENABLED=false 时被忽略）"),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('export_backup_enhanced')),
    db: AsyncSession = Depends(get_async_db),
):
    """
    增强的备份导出端点，支持Range请求头和分片下载
    基于 FileResponse 磁盘流式传输，由 Starlette 自动处理 Range 请求。
    """

    temp_files: list[str] = []

    def _register_temp_file(path: Path) -> Path:
        temp_files.append(str(path))
        return path

    def _cleanup_temp_files() -> None:
        for _p in temp_files:
            if os.path.exists(_p):
                os.unlink(_p)
    background_tasks.add_task(_cleanup_temp_files)
    # H3：GET 端点密码仅走 X-Backup-Password 头/环境变量
    return await _export_backup_to_response(
        request, db, user, remark, format, encrypt, None, x_backup_password, _register_temp_file,
    )
