"""备份记录查询、状态、调度与删除路由。

从原 backup.py 拆分，URL / schema / 权限码保持不变：
- GET    /ping                       快速诊断端点
- GET    /tables                     列出所有可备份的数据库表及行数
- GET    /list                       列出服务器默认路径上的所有备份文件
- DELETE /delete-by-name/{filename}  删除服务器默认路径上的指定备份文件
- GET    /status                     获取备份系统状态概览
- GET    /records                    备份记录分页列表
- GET    /schedule                   定时任务配置（ARQ cron_jobs）
- POST   /schedule/trigger           手动触发定时任务（通过 ARQ 入队）
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import require_backup_permission
from fastapi_app.core.database import get_async_read_db
from fastapi_app.schemas.backup import (
    BackupDeleteResponse,
    BackupListResponse,
    BackupPingResponse,
    BackupRecordListOut,
    BackupScheduleOut,
    BackupStatusOut,
    BackupTablesResponse,
    BackupTriggerOut,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup.verify import query_service as backup_query_service
from fastapi_app.services.backup import BackupFileError
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /ping
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
# GET /tables
# ---------------------------------------------------------------------------
@router.get('/tables', response_model=BackupTablesResponse)
async def list_backup_tables(
    user: User = Depends(require_backup_permission('list_backup_tables')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """列出所有可备份的数据库表及行数"""
    try:
        table_info = await backup_query_service.get_backup_table_info(db)
    except (SQLAlchemyError, OperationalError, RuntimeError) as e:
        logger.error(f'列出备份表失败: {e}')
        raise HTTPException(status_code=500, detail='获取表信息失败，请查看服务器日志') from e
    return {'success': True, 'tables': table_info, 'total': len(table_info)}


# ---------------------------------------------------------------------------
# GET /list
# ---------------------------------------------------------------------------
@router.get('/list', response_model=BackupListResponse)
async def list_server_backups(user: User = Depends(require_backup_permission('list_server_backups'))):
    """列出服务器默认路径上的所有备份文件"""
    backups = backup_service.list_backup_files()
    return {'success': True, 'backups': backups, 'total': len(backups)}


# ---------------------------------------------------------------------------
# DELETE /delete-by-name/{filename}
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
# GET /status
# ---------------------------------------------------------------------------
@router.get('/status', response_model=BackupStatusOut)
async def backup_status(user: User = Depends(require_backup_permission('backup_status'))):
    """获取备份系统状态概览"""
    return backup_service.get_backup_status()


# ---------------------------------------------------------------------------
# GET /records
# ---------------------------------------------------------------------------
@router.get('/records', response_model=BackupRecordListOut)
async def get_backup_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(require_backup_permission('get_backup_records')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """备份记录分页列表"""
    records, total = await backup_query_service.get_backup_records_page(db, page, page_size)

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


# ---------------------------------------------------------------------------
# GET /schedule
# ---------------------------------------------------------------------------
@router.get('/schedule', response_model=BackupScheduleOut)
async def get_backup_schedule(user: User = Depends(require_backup_permission('get_backup_schedule'))):
    """定时任务配置（ARQ cron_jobs）"""
    from fastapi_app.core.arq_app import cron_schedules
    tasks = []
    for s in cron_schedules:
        tasks.append({
            'name': s['name'], 'task': s['func'].__name__,
            'schedule': s['schedule'], 'enabled': True,
        })
    return {'success': True, 'tasks': tasks}


# ---------------------------------------------------------------------------
# POST /schedule/trigger
# ---------------------------------------------------------------------------
@router.post('/schedule/trigger', response_model=BackupTriggerOut)
async def trigger_backup_schedule(
    task_name: str = Query(...),
    user: User = Depends(require_backup_permission('trigger_backup_schedule')),
):
    """手动触发定时任务（通过 ARQ 入队）"""
    from fastapi_app.core.arq_app import cron_schedules, get_arq_pool
    schedule = next((s for s in cron_schedules if s['name'] == task_name), None)
    if schedule is None:
        raise HTTPException(status_code=404, detail=f'定时任务 {task_name} 不存在')
    func_name = schedule['func'].__name__
    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(func_name)
    except (RuntimeError, OSError, ConnectionError) as e:
        raise HTTPException(status_code=500, detail='触发任务失败，请查看服务器日志') from e
    return {'success': True, 'task_name': task_name, 'message': f'任务 {task_name} 已触发'}
