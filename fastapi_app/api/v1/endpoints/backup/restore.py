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
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import (
    _background_tasks,
    require_backup_permission,
)
from fastapi_app.core.database import get_async_db
from fastapi_app.schemas.backup import (
    AsyncTaskResponse,
    BackupImportResponse,
    BackupProgressOut,
    IncrementalRestoreResponse,
)
from fastapi_app.services import backup_service
from fastapi_app.services.backup_service import (
    BackupError, BackupLockError, RestoreError,
)
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


async def _read_backup_file(file: UploadFile) -> tuple[bytes, bool, str]:
    """读取并校验备份上传文件，返回 (content, is_zip, filename)。

    校验扩展名、文件大小上限、空内容与格式识别，不合法直接抛 HTTPException。
    从 import_backup / async_import_backup 中提取的公共逻辑。
    """
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
    return content, is_zip, filename


# ---------------------------------------------------------------------------
# POST /import
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
    content, is_zip, _ = await _read_backup_file(file)

    try:
        pre_restore_info = await backup_service.create_pre_restore_backup(db)
    except (BackupError, OSError):
        pre_restore_info = {'success': False, 'error': '创建安全备份失败'}

    from fastapi_app.services import backup_query_service
    lock_acquired = False
    try:
        if not await backup_query_service.try_acquire_restore_lock(db):
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
            await backup_query_service.release_restore_lock(db)


# ---------------------------------------------------------------------------
# POST /restore-by-name/{filename}
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

    from fastapi_app.services import backup_query_service
    lock_acquired = False
    try:
        if not await backup_query_service.try_acquire_restore_lock(db):
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
            await backup_query_service.release_restore_lock(db)
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
    user: User = Depends(require_backup_permission('async_import_backup')),
):
    """异步恢复：从上传文件恢复"""
    if not confirm:
        raise HTTPException(status_code=400, detail='恢复操作需要二次确认，请传入 confirm=true')
    content, is_zip, filename = await _read_backup_file(file)

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
# POST /async-restore-by-name/{filename}
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
                    from fastapi_app.services import backup_query_service
                    lock_acquired = False
                    try:
                        if not await backup_query_service.try_acquire_restore_lock(db):
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
                            await backup_query_service.release_restore_lock(db)

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
            except Exception as e:
                # fail_progress 内部经 _sanitize_error 清洗（去除路径并截断），可安全写入 str(e)
                await fail_progress(task_id, str(e))
    except Exception as e:
        logger.error(f'异步恢复任务异常: {e}')
        await fail_progress(task_id, str(e))
    finally:
        # 释放恢复锁
        await backup_service.release_restore_lock()
