"""数据备份与恢复 API — 纯路由层

所有业务逻辑委托给 backup_service.py。
16 个现有端点保持完全相同的路径/方法/签名/响应格式。
"""
import asyncio
import io
import json
import logging
import os
import zipfile
from datetime import datetime
from pathlib import Path

_background_tasks: set[asyncio.Task] = set()

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import require_permission
from fastapi_app.services import backup_service
from fastapi_app.services.backup_service import (
    BackupError, BackupFileError, BackupLockError, RestoreError,
)
from fastapi_app.shared_models import User

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
@router.get('/ping')
async def ping(user: User = Depends(require_permission('backup_manage'))):
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
@router.get('/tables')
async def list_backup_tables(
    user: User = Depends(require_permission('backup_manage')),
    db: AsyncSession = Depends(get_async_db),
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
            except Exception as e:
                logger.warning(f'统计表 {name} 行数失败: {e}')
                count = -1
            table_info.append({'name': name, 'rows': count})
    except Exception as e:
        logger.error(f'列出备份表失败: {e}')
        raise HTTPException(status_code=500, detail='获取表信息失败，请查看服务器日志') from e
    return {'success': True, 'tables': table_info, 'total': len(table_info)}


# ---------------------------------------------------------------------------
# 3. GET /export
# ---------------------------------------------------------------------------
@router.get('/export')
async def export_backup(
    remark: str = '',
    format: str = 'zip',
    user: User = Depends(require_permission('backup_manage')),
    db: AsyncSession = Depends(get_async_db),
):
    """一键备份全部数据（流式返回，避免大文件 OOM）"""
    import os as _os
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if format == 'json':
        try:
            json_bytes = await backup_service.execute_legacy_backup_to_bytes(user, remark, db)
        except Exception as e:
            logger.error(f'JSON 备份导出失败: {e}')
            raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
        filename = f'erp_backup_{timestamp}.json'
        return StreamingResponse(
            io.BytesIO(json_bytes), media_type='application/json',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )
    try:
        # 使用文件方式避免大 ZIP 占用内存
        zip_path, manifest = await backup_service.create_full_backup_to_file(db, user, remark)
    except Exception as e:
        logger.error(f'ZIP 备份导出失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
    filename = f'erp_backup_{timestamp}.zip'

    # 使用 FileResponse 流式返回，自动清理临时文件
    def _cleanup():
        try:
            _os.unlink(zip_path)
        except OSError:
            pass

    return FileResponse(
        path=str(zip_path),
        filename=filename,
        media_type='application/zip',
        background=_cleanup,
    )


# ---------------------------------------------------------------------------
# 4. POST /import
# ---------------------------------------------------------------------------
@router.post('/import')
async def import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    user: User = Depends(require_permission('backup_manage')),
    db: AsyncSession = Depends(get_async_db),
):
    """一键恢复：从备份文件恢复全部数据"""
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

    try:
        pre_restore_info = await backup_service.create_pre_restore_backup(db)
    except Exception:
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
    except (RuntimeError, OSError):
        logger.warning('获取恢复锁失败，继续执行恢复操作')

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
        except Exception:
            raise
        verification_ok = result.get('verification', {}).get('overall_pass', True)
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
@router.post('/validate')
async def validate_backup(
    file: UploadFile = File(...),
    user: User = Depends(require_permission('backup_manage')),
):
    """验证备份文件，不执行恢复，仅返回摘要信息"""
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
@router.post('/save')
async def save_backup_to_server(
    remark: str = '',
    user: User = Depends(require_permission('backup_manage')),
    db: AsyncSession = Depends(get_async_db),
):
    """一键备份到服务器默认路径"""
    backup_service.ensure_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        zip_bytes, manifest = await backup_service.create_full_backup(db, user, remark)
    except Exception as e:
        logger.error(f'服务端备份失败: {e}')
        raise HTTPException(status_code=500, detail='备份失败，请查看服务器日志') from e
    filename = f'erp_backup_{timestamp}.zip'
    filepath = backup_service.BACKUP_DIR / filename
    filepath.write_bytes(zip_bytes)

    # 写入 BackupRecord
    await backup_service.write_backup_record(
        db, record_type='full', trigger_type='manual',
        filename=filename, size=manifest.get('zip_size', len(zip_bytes)),
        table_count=manifest.get('table_count', 0),
        total_rows=manifest.get('total_rows', 0),
        operator=user.username if hasattr(user, 'username') else str(user.id),
        remark=remark,
    )

    return {
        'success': True, 'format': 'zip', 'filename': filename,
        'size': manifest.get('zip_size', len(zip_bytes)),
        'table_count': manifest.get('table_count', 0),
        'total_rows': manifest.get('total_rows', 0),
        'exported_at': manifest.get('exported_at'),
        'exported_by': manifest.get('exported_by'),
        'includes': manifest.get('includes', {}), 'remark': remark,
    }


# ---------------------------------------------------------------------------
# 7. GET /list
# ---------------------------------------------------------------------------
@router.get('/list')
async def list_server_backups(user: User = Depends(require_permission('backup_manage'))):
    """列出服务器默认路径上的所有备份文件"""
    backups = backup_service.list_backup_files()
    return {'success': True, 'backups': backups, 'total': len(backups)}


# ---------------------------------------------------------------------------
# 8. POST /restore-by-name/{filename}
# ---------------------------------------------------------------------------
@router.post('/restore-by-name/{filename}')
async def restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    user: User = Depends(require_permission('backup_manage')),
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
    except (RuntimeError, OSError):
        logger.warning('获取恢复锁失败，继续执行恢复操作')
    try:
        result = await backup_service.restore_legacy_json(backup_data, db)
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
@router.delete('/delete-by-name/{filename}')
async def delete_server_backup(
    filename: str,
    user: User = Depends(require_permission('backup_manage')),
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
@router.get('/status')
async def backup_status(user: User = Depends(require_permission('backup_manage'))):
    """获取备份系统状态概览"""
    return backup_service.get_backup_status()


# ---------------------------------------------------------------------------
# 11. POST /save-incremental
# ---------------------------------------------------------------------------
@router.post('/save-incremental')
async def save_incremental_backup(
    remark: str = '',
    since: str = Query(''),
    user: User = Depends(require_permission('backup_manage')),
    db: AsyncSession = Depends(get_async_db),
):
    """增量备份"""
    try:
        result = await backup_service.create_incremental_backup(db, user, remark, since)
    except Exception as e:
        logger.error(f'增量备份失败: {e}')
        raise HTTPException(status_code=500, detail='增量备份失败，请查看服务器日志') from e
    return result


# ---------------------------------------------------------------------------
# 12. POST /restore-incremental/{filename}
# ---------------------------------------------------------------------------
@router.post('/restore-incremental/{filename}')
async def restore_incremental_backup(
    filename: str,
    confirm: bool = Query(False),
    user: User = Depends(require_permission('backup_manage')),
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
@router.post('/integrity-check')
async def run_integrity_check(user: User = Depends(require_permission('backup_manage'))):
    """备份完整性巡检"""
    from fastapi_app.tasks.backup_tasks import _do_integrity_check
    result = await _do_integrity_check()
    return result


# ---------------------------------------------------------------------------
# 14. GET /progress/{task_id}
# ---------------------------------------------------------------------------
@router.get('/progress/{task_id}')
async def get_restore_progress(
    task_id: str,
    user: User = Depends(require_permission('backup_manage')),
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
@router.post('/async-import')
async def async_import_backup(
    file: UploadFile = File(...),
    confirm: bool = False,
    user: User = Depends(require_permission('backup_manage')),
):
    """异步恢复：从上传文件恢复"""
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
@router.post('/async-restore-by-name/{filename}')
async def async_restore_server_backup(
    filename: str,
    confirm: bool = Query(False),
    user: User = Depends(require_permission('backup_manage')),
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
                    except (RuntimeError, OSError):
                        logger.warning('获取恢复锁失败，继续执行恢复操作')
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
@router.get('/records')
async def get_backup_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_permission('backup_manage')),
    db: AsyncSession = Depends(get_async_db),
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


@router.get('/schedule')
async def get_backup_schedule(user: User = Depends(require_permission('backup_manage'))):
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


@router.post('/schedule/trigger')
async def trigger_backup_schedule(
    task_name: str = Query(...),
    user: User = Depends(require_permission('backup_manage')),
):
    """手动触发定时任务"""
    from fastapi_app.core.celery_app import celery_app
    beat_schedule = celery_app.conf.get('beat_schedule', {})
    if task_name not in beat_schedule:
        raise HTTPException(status_code=404, detail=f'定时任务 {task_name} 不存在')
    task_id_str = beat_schedule[task_name].get('task', '')
    try:
        celery_app.send_task(task_id_str)
    except Exception as e:
        raise HTTPException(status_code=500, detail='触发任务失败，请查看服务器日志') from e
    return {'success': True, 'task_name': task_name, 'message': f'任务 {task_name} 已触发'}
