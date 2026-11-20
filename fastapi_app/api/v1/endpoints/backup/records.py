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
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path
from types import FunctionType

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import (
    _resolve_encryption,
    require_backup_permission,
    require_superuser_for_encrypted_backup,
)
from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.exceptions import db_transaction
from fastapi_app.schemas.backup import (
    BackupDeleteResponse,
    BackupListResponse,
    BackupPingResponse,
    BackupRecordListOut,
    BackupScheduleCreate,
    BackupScheduleOut,
    BackupScheduleUpdate,
    BackupStatusOut,
    BackupTablesResponse,
    BackupTriggerOut,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.services.backup import BackupFileError, schedule_service
from fastapi_app.services.backup.verify import query_service as backup_query_service
from fastapi_app.shared_models import User


def _iso_or_raw(value: object) -> object:
    """datetime 转 ISO 字符串，其余原样返回（与内联三元的输出形状一致）。"""
    return value.isoformat() if isinstance(value, datetime) else value


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
        'timestamp': datetime.now(UTC).isoformat(),
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
    # 逐 zip 读 manifest / 逐 json 解析是同步 IO，必须离开事件循环（审计 M-07）
    backups = await asyncio.to_thread(backup_service.list_backup_files)
    return {'success': True, 'backups': backups, 'total': len(backups)}


# ---------------------------------------------------------------------------
# DELETE /delete-by-name/{filename}
# ---------------------------------------------------------------------------
@router.delete('/delete-by-name/{filename}', response_model=BackupDeleteResponse)
async def delete_server_backup(
    filename: str,
    user: User = Depends(require_backup_permission('delete_server_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """删除服务器默认路径上的指定备份文件

    幂等删除：文件若已被保留策略清理，不再报 404，而是仅清理同名备份记录，
    避免记录列表残留"幽灵"备份导致重复删除报错；文件存在时同时清理记录，
    保持记录列表与磁盘文件一致。
    """
    # 路径遍历校验：禁止文件名包含路径分隔符或上级目录引用
    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail='文件名包含非法路径字符')
    deleted = ''
    try:
        deleted = backup_service.delete_backup_file(safe_name)
    except BackupFileError as e:
        if '不存在' not in str(e):
            raise HTTPException(status_code=400, detail=str(e)) from e
        # 文件已不存在（例如被保留策略清理）——幂等处理，继续清理同名记录
    try:
        from sqlalchemy import delete as _sa_delete

        from fastapi_app.shared_models.backup_record import BackupRecord
        # 写库必须在本端点内提交（依赖收尾 commit 晚于响应发送，见 get_async_db docstring）
        async with db_transaction(db):
            await db.execute(_sa_delete(BackupRecord).where(BackupRecord.filename == safe_name))
    except HTTPException as e:
        # 记录清理失败不影响「文件删除」的成功语义（改造前只记日志后照样返回成功）；
        # db_transaction 已把 SQLAlchemyError 收敛成 500，这里降级为日志。
        if e.status_code < 500:
            raise
        logger.error(f'清理备份记录 {safe_name} 失败: {e.detail}')
    return {'success': True, 'deleted': deleted}


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------
@router.get('/status', response_model=BackupStatusOut)
async def backup_status(user: User = Depends(require_backup_permission('backup_status'))):
    """获取备份系统状态概览"""
    return await asyncio.to_thread(backup_service.get_backup_status)


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
    """备份记录分页列表

    以文件系统扫描为基准，左连接数据库 backup_record 表补充元信息，
    确保管理列表与还原向导(/backup/list)数据源一致。
    """
    records, total = await backup_query_service.get_merged_backup_records(db, page, page_size)

    return {
        'success': True,
        'records': [
            {
                'id': r.get('id'),
                'type': r.get('type'),
                'trigger_type': r.get('trigger_type'),
                'filename': r.get('filename'),
                'size': r.get('size'),
                'table_count': r.get('table_count'),
                'total_rows': r.get('total_rows'),
                'operator': r.get('operator'),
                'remark': r.get('remark'),
                'status': r.get('status'),
                'error_message': r.get('error_message'),
                'duration_seconds': r.get('duration_seconds'),
                'ip_address': r.get('ip_address'),
                'user_agent': r.get('user_agent'),
                'parent_record_id': r.get('parent_record_id'),
                'created_at': _iso_or_raw(r.get('created_at')),
                'updated_at': _iso_or_raw(r.get('updated_at')),
                'source': r.get('source', 'db'),
                'encrypted': r.get('encrypted'),
            }
            for r in records
        ],
        'total': total, 'page': page, 'page_size': page_size,
    }


# ---------------------------------------------------------------------------
# GET /schedule
# ---------------------------------------------------------------------------
@router.get('/schedule', response_model=BackupScheduleOut)
async def get_backup_schedule(
    user: User = Depends(require_backup_permission('get_backup_schedule')),
    db: AsyncSession = Depends(get_async_read_db),
):
    """定时任务配置（M2 起读 backup_schedule 表）"""
    rows = await schedule_service.list_schedules(db)
    tasks = [
        {
            'id': r.id,
            'name': r.name,
            'task': schedule_service.TASK_TYPE_TO_FUNC.get(r.task_type, ''),
            'task_type': r.task_type,
            'cron_expr': r.cron_expr,
            'schedule': r.cron_expr,
            'enabled': r.enabled,
            'last_run': r.last_run_at,
            'last_status': r.last_status,
        }
        for r in rows
    ]
    return {'success': True, 'tasks': tasks}


# ---------------------------------------------------------------------------
# POST /schedule  新增
# PUT /schedule/{id}  更新
# DELETE /schedule/{id}  删除
# ---------------------------------------------------------------------------
@router.post('/schedule', response_model=BackupScheduleOut, status_code=201)
async def create_backup_schedule(
    payload: BackupScheduleCreate,
    user: User = Depends(require_backup_permission('create_backup_schedule')),
    db: AsyncSession = Depends(get_async_db),
):
    """新增定时任务（backup_manage）"""
    try:
        # 写库必须在本端点内提交（依赖收尾 commit 晚于响应发送，见 get_async_db docstring）
        async with db_transaction(db):
            row = await schedule_service.create_schedule(
                db, name=payload.name, task_type=payload.task_type,
                cron_expr=payload.cron_expr, enabled=payload.enabled,
            )
    except schedule_service.BackupSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        'success': True,
        'tasks': [{
            'id': row.id, 'name': row.name,
            'task': schedule_service.TASK_TYPE_TO_FUNC.get(row.task_type, ''),
            'task_type': row.task_type, 'cron_expr': row.cron_expr,
            'schedule': row.cron_expr, 'enabled': row.enabled,
            'last_run': row.last_run_at, 'last_status': row.last_status,
        }],
    }


@router.put('/schedule/{schedule_id}', response_model=BackupScheduleOut)
async def update_backup_schedule(
    schedule_id: int,
    payload: BackupScheduleUpdate,
    user: User = Depends(require_backup_permission('update_backup_schedule')),
    db: AsyncSession = Depends(get_async_db),
):
    """更新定时任务（backup_manage）"""
    try:
        # 写库必须在本端点内提交（依赖收尾 commit 晚于响应发送，见 get_async_db docstring）
        async with db_transaction(db):
            row = await schedule_service.update_schedule(
                db, schedule_id, name=payload.name, task_type=payload.task_type,
                cron_expr=payload.cron_expr, enabled=payload.enabled,
            )
    except schedule_service.BackupSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        'success': True,
        'tasks': [{
            'id': row.id, 'name': row.name,
            'task': schedule_service.TASK_TYPE_TO_FUNC.get(row.task_type, ''),
            'task_type': row.task_type, 'cron_expr': row.cron_expr,
            'schedule': row.cron_expr, 'enabled': row.enabled,
            'last_run': row.last_run_at, 'last_status': row.last_status,
        }],
    }


@router.delete('/schedule/{schedule_id}', response_model=BackupTriggerOut)
async def delete_backup_schedule(
    schedule_id: int,
    user: User = Depends(require_backup_permission('delete_backup_schedule')),
    db: AsyncSession = Depends(get_async_db),
):
    """删除定时任务（backup_manage）

    校验类任务（完整性巡检 / 灾备演练）整类受保护、不允许删除，见
    schedule_service.GUARDED_TASK_TYPES —— 误删会静默失去备份可用性保障。
    """
    try:
        # 写库必须在本端点内提交（依赖收尾 commit 晚于响应发送，见 get_async_db docstring）；
        # 404 在事务内抛出 → 回滚，不会留下「报错但已删」的中间态。
        async with db_transaction(db):
            deleted = await schedule_service.delete_schedule(db, schedule_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=f'调度任务 {schedule_id} 不存在')
    except schedule_service.BackupSettingsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {'success': True, 'task_name': str(schedule_id), 'message': '调度任务已删除'}


# ---------------------------------------------------------------------------
# POST /schedule/trigger
# ---------------------------------------------------------------------------
@router.post('/schedule/trigger', response_model=BackupTriggerOut)
async def trigger_backup_schedule(
    task_name: str = Query(...),
    user: User = Depends(require_backup_permission('trigger_backup_schedule')),
):
    """手动触发定时任务（通过 ARQ 入队）

    M2 起优先匹配 backup_schedule 表（按 name），再回退到内置 cron_schedules。
    """
    from fastapi_app.core.arq_app import cron_schedules, get_arq_pool

    #: 会产出整库备份包的任务函数。其余三类（integrity_check / cleanup /
    #: disaster_recovery_test）不产出含凭据的包，不必拦。
    _BACKUP_FUNCS = frozenset({'auto_daily_backup_task', 'manual_full_backup_task'})

    def _gate_if_backup(func_name: str) -> None:
        """2026-11-18 评审 High2：备份类定时任务也要过凭据闸门。

        它用**环境变量里的**加密口令产出整库加密包（含现役 JWT 私钥与运行时
        `.env`）。手动触发它等于绕过 `POST /full` 上的那道闸 —— 同一个产物，
        两条入口只堵一条等于没堵。
        """
        if func_name not in _BACKUP_FUNCS:
            return
        # 第一实参必须传 True（意图=「本次产物是加密包」）：resolver 对
        # `encrypt is False` 直接短路返回 (False, None)，传 False 会让 effective
        # 恒 False、闸门恒不生效（2026-11-21 审计 records-H3）。任务侧口令
        # 继承 env（第二/三实参 None）；总开关关闭时 resolver 返回 False，
        # 明文包不含凭据，不拦是正确语义。
        effective, _ = _resolve_encryption(True, None, None)
        require_superuser_for_encrypted_backup(user, effective_encrypt=effective)

    # 1) 内置 cron_schedules（sync-shipment/级联等）
    schedule = next((s for s in cron_schedules if s['name'] == task_name), None)
    if schedule is not None:
        func = schedule['func']
        if not isinstance(func, FunctionType):
            raise HTTPException(status_code=500, detail='定时任务配置无效')
        func_name = func.__name__
        _gate_if_backup(func_name)
        try:
            pool = await get_arq_pool()
            await pool.enqueue_job(func_name)
        except (RuntimeError, OSError, ConnectionError) as e:
            raise HTTPException(status_code=500, detail='触发任务失败，请查看服务器日志') from e
        return {'success': True, 'task_name': task_name, 'message': f'任务 {task_name} 已触发'}

    # 2) backup_schedule 表（M2 起定时备份走这里）
    from fastapi_app.core.database import get_async_db_context

    async with get_async_db_context() as db:
        rows = await schedule_service.list_schedules(db)
        row = next((r for r in rows if r.name == task_name), None)
        if row is None:
            raise HTTPException(status_code=404, detail=f'定时任务 {task_name} 不存在')
        func_name = schedule_service.TASK_TYPE_TO_FUNC.get(row.task_type, '')
    if not func_name:
        raise HTTPException(status_code=400, detail=f'任务类型 {row.task_type} 无对应任务函数')
    # 备份类任务会用 env 口令产出加密包，必须过同一道凭据闸门。
    # 放在 400 校验之后：不存在的任务类型该报 400，不该先撞 403。
    _gate_if_backup(func_name)
    try:
        pool = await get_arq_pool()
        await pool.enqueue_job(func_name)
    except (RuntimeError, OSError, ConnectionError) as e:
        raise HTTPException(status_code=500, detail='触发任务失败，请查看服务器日志') from e
    return {'success': True, 'task_name': task_name, 'message': f'任务 {task_name} 已触发'}
