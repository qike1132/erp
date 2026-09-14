"""备份导入与恢复路由。

从原 backup.py 拆分，URL / schema / 权限码保持不变：
- POST /import                       一键恢复：从上传文件恢复
- POST /restore-by-name/{filename}   从服务器默认路径恢复指定备份
- POST /restore-incremental/{name}   从增量备份恢复
- GET  /progress/{task_id}           查询异步任务进度
- POST /async-import                 异步恢复：从上传文件恢复
- POST /async-restore-by-name/{name} 异步恢复：从服务器文件恢复
"""
import asyncio
import gzip
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import (
    _background_tasks,
    _get_encryption_password,
    require_backup_permission,
)
from fastapi_app.core.database import get_async_db
from fastapi_app.schemas.backup import (
    AsyncTaskResponse,
    BackupImportResponse,
    BackupProgressOut,
    BackupRestorePlanOut,
    BackupRestorePlanRequest,
    IncrementalRestoreResponse,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import (
    BackupError,
    BackupLockError,
    RestoreError,
)
from fastapi_app.services.backup import restore_plan as restore_plan_service
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def _redis_unavailable() -> bool:
    """探测 Redis 是否可用（用于区分 409 锁被占与 503 锁服务故障）。

    委托 core.backup_progress.is_redis_available 统一实现。
    """
    try:
        from fastapi_app.core.backup_progress import is_redis_available
        return not await is_redis_available()
    except Exception:  # broad-except: 探测失败按不可用处理（fail-closed）
        return True


async def _acquire_sync_restore_lock(purpose: str) -> None:
    """同步还原路径统一获取 Redis 还原锁（P0-5 锁统一）。

    - 与异步任务路径共用同一把锁（erp:restore_lock），消除旧实现"同步走 PG
      advisory、异步走 Redis，可各持一种锁并发还原"的窗口；
    - fail-closed：Redis 不可用时 503 拒绝还原。
    """
    if not await backup_service.acquire_restore_lock(purpose):
        if await _redis_unavailable():
            logger.error('Redis 不可用，拒绝执行恢复操作（fail-closed）')
            raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试')
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')


async def fail_progress_quietly(task_id: str) -> None:
    """锁获取失败时把进度键标记为失败（避免前端轮询假死 1 小时）。"""
    try:
        from fastapi_app.core.backup_progress import fail_progress
        await fail_progress(task_id, '获取恢复锁失败，任务未启动')
    except Exception as e:  # broad-except: 进度上报失败不影响主流程
        logger.warning(f'标记进度失败（{task_id}）: {e}')


async def _read_backup_file(file: UploadFile) -> tuple[bytes, bool, str]:
    """读取并校验备份上传文件，返回 (content, is_zip, filename)。

    校验扩展名、文件大小上限、空内容与格式识别，不合法直接抛 HTTPException。
    从 import_backup / async_import_backup 中提取的公共逻辑。
    """
    filename = file.filename or ''
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.zip', '.json', '.gz', '.enc'):
        raise HTTPException(status_code=400, detail=f'不支持的文件类型: {ext}，仅支持 .zip / .zip.enc / .json / .gz')
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
    is_zip = filename.endswith('.zip') or filename.endswith('.zip.enc') or content[:4] == b'PK\x03\x04'
    is_json = filename.endswith('.json') or (content[:1] == b'{' and content.strip().endswith(b'}'))
    is_gz = filename.endswith('.gz') or (content[:2] == b'\x1f\x8b')
    if not is_zip and not is_json and not is_gz:
        raise HTTPException(status_code=400, detail='无法识别的备份文件格式')
    if is_gz:
        content = await asyncio.to_thread(gzip.decompress, content)
        is_json = True
    return content, is_zip, filename


# ---------------------------------------------------------------------------
# POST /import
# ---------------------------------------------------------------------------
@router.post('/import', response_model=BackupImportResponse)
async def import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件（.env.production / jwt 密钥），默认跳过'),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('import_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """一键恢复：从备份文件恢复全部数据

    解密密码仅通过 X-Backup-Password 请求头或环境变量提供（H3：multipart 端点
    无法安全混合 JSON body，且密码不进 URL query 避免落入访问日志/浏览器历史）。
    """
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    content, is_zip, _ = await _read_backup_file(file)
    decrypt_password = _get_encryption_password(None, x_backup_password)

    try:
        pre_restore_info = await backup_service.create_pre_restore_backup(db)
    except (BackupError, OSError):
        pre_restore_info = {'success': False, 'error': '创建安全备份失败'}

    # P0-5: 同步路径统一 Redis 还原锁（fail-closed），与异步任务共用
    await _acquire_sync_restore_lock('sync_import')
    try:
        if is_zip:
            try:
                result = await backup_service.restore_from_zip(
                    content, db,
                    decrypt_password=decrypt_password,
                    confirm_sensitive=confirm_sensitive,
                )
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
        await backup_service.release_restore_lock()


# ---------------------------------------------------------------------------
# POST /restore-by-name/{filename}
# ---------------------------------------------------------------------------
@router.post('/restore-by-name/{filename}', response_model=BackupImportResponse)
async def restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件（.env.production / jwt 密钥），默认跳过'),
    password: str | None = Body(None, description='加密备份解密密码（H3：经 body 传递，避免进入访问日志/浏览器历史；为空时依次使用请求头/环境变量）'),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
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
    # P0-5: 与上传路径一致的大小上限，防超大文件整体读入内存
    try:
        if filepath.stat().st_size > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)，请使用分片或异步方式',
            )
        # H5: 大文件读取为阻塞 IO，移入线程池避免卡住事件循环
        content = await asyncio.to_thread(filepath.read_bytes)
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e

    decrypt_password = _get_encryption_password(password, x_backup_password)
    is_zip = safe_name.endswith('.zip') or safe_name.endswith('.zip.enc') or content[:4] == b'PK\x03\x04'
    if is_zip:
        # P0-5: 补齐还原前安全备份 + Redis 还原锁（旧实现此路径两者皆无）
        try:
            pre_restore_info = await backup_service.create_pre_restore_backup(db)
        except (BackupError, OSError):
            pre_restore_info = {'success': False, 'error': '创建安全备份失败'}
        await _acquire_sync_restore_lock('sync_restore_by_name')
        try:
            try:
                result = await backup_service.restore_from_zip(
                    content, db,
                    decrypt_password=decrypt_password,
                    confirm_sensitive=confirm_sensitive,
                )
            except RestoreError as e:
                raise HTTPException(status_code=500, detail=str(e)) from e
        finally:
            await backup_service.release_restore_lock()
        result['pre_restore_backup'] = pre_restore_info
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

    await _acquire_sync_restore_lock('sync_restore_by_name_json')
    try:
        result = await backup_service.restore_legacy_json(backup_data, db)
        await db.commit()
    except (BackupError, SQLAlchemyError, RuntimeError, ValueError):
        await db.rollback()
        raise
    finally:
        await backup_service.release_restore_lock()
    verification_ok = result.get('verification', {}).get('overall_pass', True)
    return {
        'success': verification_ok, 'format': 'json', 'filename': safe_name,
        'total_inserted': result['total_inserted'], 'results': result['results'],
        'errors': result['errors'],
        'restored_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ---------------------------------------------------------------------------
# POST /restore-incremental/{filename}
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
        if filepath.stat().st_size > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)',
            )
        # H5: 大文件读取为阻塞 IO，移入线程池避免卡住事件循环
        content = await asyncio.to_thread(filepath.read_bytes)
    except HTTPException:
        raise
    except OSError as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e
    is_zip = safe_name.endswith('.zip') or safe_name.endswith('.zip.enc') or content[:4] == b'PK\x03\x04'
    if not is_zip:
        raise HTTPException(status_code=400, detail='增量备份文件必须是 ZIP 格式')
    # B2 修复：增量还原接入统一 Redis 还原锁，与全量还原互斥
    # （此前仅持 PG advisory lock，与全量 psql 还原的 Redis 锁互不感知，
    #   可并发执行：增量 upsert 连接会被全量还原的 pg_terminate_backend 杀死）
    await _acquire_sync_restore_lock(f'incremental_{safe_name}')
    try:
        result = await backup_service.restore_incremental(db, content, safe_name)
    except BackupLockError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except RestoreError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        await backup_service.release_restore_lock(f'incremental_{safe_name}')
    return result


# ---------------------------------------------------------------------------
# GET /progress/{task_id}
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
# POST /async-import
# ---------------------------------------------------------------------------
@router.post('/async-import', response_model=AsyncTaskResponse)
async def async_import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件，默认跳过'),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('async_import_backup')),
):
    """异步恢复：从上传文件恢复

    解密密码仅通过 X-Backup-Password 请求头或环境变量提供（H3：multipart 端点
    无法安全混合 JSON body，且密码不进 URL query 避免落入访问日志/浏览器历史）。
    """
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    content, is_zip, filename = await _read_backup_file(file)
    decrypt_password = _get_encryption_password(None, x_backup_password)

    # 并发检查：避免同时启动多个恢复任务。委托共享助手区分「Redis 故障(503)」
    # 与「锁真实占用(409)」，并自愈崩溃残留的陈旧锁（同 actions._check_task_mutex）
    from fastapi_app.api.v1.endpoints.backup._mutex import ensure_restore_slot_free
    await ensure_restore_slot_free()

    from fastapi_app.core.backup_progress import create_progress, generate_task_id
    task_id = generate_task_id()
    await create_progress(task_id, 'file_import')
    # B1 修复：必须检查锁获取结果，失败时清理进度键并拒绝启动，消除
    # is_restore_in_progress 与 acquire 之间 TOCTOU 窗口内的并发还原
    if not await backup_service.acquire_restore_lock(task_id):
        await fail_progress_quietly(task_id)
        if await _redis_unavailable():
            raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试')
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')

    task = asyncio.create_task(_run_async_file_restore(
        task_id, content, is_zip, filename,
        confirm_sensitive=confirm_sensitive, decrypt_password=decrypt_password,
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {'success': True, 'task_id': task_id, 'message': '恢复任务已启动'}


# ---------------------------------------------------------------------------
# POST /async-restore-by-name/{filename}
# ---------------------------------------------------------------------------
@router.post('/async-restore-by-name/{filename}', response_model=AsyncTaskResponse)
async def async_restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    confirm_sensitive: bool = Query(False, description='确认同时还原敏感配置文件，默认跳过'),
    password: str | None = Body(None, description='加密备份解密密码（H3：经 body 传递，避免进入访问日志/浏览器历史；为空时依次使用请求头/环境变量）'),
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('async_restore_server_backup')),
):
    """异步恢复：从服务器文件恢复"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')

    # 并发检查（同 async_import_backup：区分 Redis 故障与真实占用 + 陈旧锁自愈）
    from fastapi_app.api.v1.endpoints.backup._mutex import ensure_restore_slot_free
    await ensure_restore_slot_free()
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='无效的文件名')
    filepath = backup_service.BACKUP_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail='备份文件不存在')
    try:
        if filepath.stat().st_size > backup_service.MAX_BACKUP_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f'备份文件超过大小限制({backup_service.MAX_BACKUP_FILE_SIZE // 1024 // 1024}MB)',
            )
        # H5: 大文件读取为阻塞 IO，移入线程池避免卡住事件循环
        content = await asyncio.to_thread(filepath.read_bytes)
    except HTTPException:
        raise
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f'读取备份文件失败: {e}') from e

    decrypt_password = _get_encryption_password(password, x_backup_password)
    from fastapi_app.core.backup_progress import create_progress, generate_task_id
    task_id = generate_task_id()
    await create_progress(task_id, 'server_restore')
    # B1 修复：必须检查锁获取结果（同 async_import_backup）
    if not await backup_service.acquire_restore_lock(task_id):
        await fail_progress_quietly(task_id)
        if await _redis_unavailable():
            raise HTTPException(status_code=503, detail='恢复锁服务暂时不可用，请稍后重试')
        raise HTTPException(status_code=409, detail='另一个恢复操作正在执行中，请稍后重试')

    is_zip = safe_name.endswith('.zip') or safe_name.endswith('.zip.enc') or content[:4] == b'PK\x03\x04'
    task = asyncio.create_task(_run_async_file_restore(
        task_id, content, is_zip, safe_name,
        confirm_sensitive=confirm_sensitive, decrypt_password=decrypt_password,
    ))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {'success': True, 'task_id': task_id, 'message': '恢复任务已启动'}


# ---------------------------------------------------------------------------
# 异步恢复后台任务
# ---------------------------------------------------------------------------
async def _run_async_file_restore(
    task_id: str, content: bytes, is_zip: bool, filename: str,
    *, confirm_sensitive: bool = False, decrypt_password: str | None = None,
):
    """异步恢复后台执行"""
    from fastapi_app.core.backup_progress import (
        complete_progress,
        fail_progress,
        update_progress,
    )
    from fastapi_app.core.database import get_async_db_context

    # B1 修复：锁续期 watchdog——还原超 TTL(3600s) 时锁会被 Redis 回收，
    # 每 10 分钟续期一次防止长任务锁丢失后被并发还原抢占
    async def _lock_watchdog():
        while True:
            await asyncio.sleep(600)
            if not await backup_service.renew_restore_lock(task_id):
                logger.warning(f'还原任务 {task_id} 恢复锁续期失败（锁已易主或 Redis 不可用）')

    watchdog = asyncio.create_task(_lock_watchdog())
    try:
        await update_progress(task_id, 'pre_backup', detail='准备恢复')
        pre_restore_info = None

        async with get_async_db_context() as db:
            try:
                await update_progress(task_id, 'pre_backup', 0.0, '创建安全备份')
                # 异步路径已持有还原锁，须跳过还原互斥检查，否则安全备份必然失败
                pre_result = await backup_service.create_pre_restore_backup(db, skip_restore_check=True)
                pre_restore_info = pre_result
                await update_progress(task_id, 'pre_backup', 1.0, '安全备份完成')

                if is_zip:
                    result = await backup_service.restore_from_zip(
                        content, db,
                        decrypt_password=decrypt_password,
                        task_id=task_id,
                        confirm_sensitive=confirm_sensitive,
                    )
                else:
                    try:
                        backup_data = await asyncio.to_thread(json.loads, content)
                    except json.JSONDecodeError:
                        await fail_progress(task_id, '备份文件格式无效（非 ZIP 亦非有效 JSON）')
                        return
                    if 'tables' not in backup_data:
                        await fail_progress(task_id, 'JSON 备份文件缺少 tables 字段')
                        return
                    # JSON 恢复路径（Redis 还原锁已由入口端点获取，见 finally 统一释放）
                    await update_progress(task_id, 'restore_db', 0.0, '通过 JSON 恢复数据库')
                    result = await backup_service.restore_legacy_json(backup_data, db)

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
            except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
                # fail_progress 内部经 _sanitize_error 清洗（去除路径并截断），可安全写入 str(e)
                await fail_progress(task_id, str(e))
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error(f'异步恢复任务异常: {e}')
        await fail_progress(task_id, str(e))
    finally:
        watchdog.cancel()
        # 释放恢复锁（B1 修复：按持有者 task_id 释放，避免误删他人锁）
        await backup_service.release_restore_lock(task_id)


# ---------------------------------------------------------------------------
# POST /restore/plan  还原差异预览（只读，原型向导第 2 步数据源）
# ---------------------------------------------------------------------------
@router.post('/restore/plan', response_model=BackupRestorePlanOut)
async def restore_plan(
    payload: BackupRestorePlanRequest,
    user: User = Depends(require_backup_permission('restore_plan')),
    db: AsyncSession = Depends(get_async_db),
):
    """还原差异预览：manifest 行数 vs 当前库实时 COUNT(*)。

    权限:backup_read。仅做只读探测，不触发任何写/还原。
    """
    try:
        manifest = restore_plan_service.read_manifest_from_backup(payload.filename)
    except (FileNotFoundError, ValueError) as e:
        return BackupRestorePlanOut(success=False, filename=payload.filename, error=str(e))
    try:
        plan = await restore_plan_service.build_restore_plan(db, manifest)
    except Exception as e:  # broad-except: 预览失败返回 message，不中断请求
        logger.warning(f'还原差异预览失败: {e}')
        return BackupRestorePlanOut(success=False, filename=payload.filename, error=str(e))
    return BackupRestorePlanOut(success=True, filename=payload.filename, **plan)
