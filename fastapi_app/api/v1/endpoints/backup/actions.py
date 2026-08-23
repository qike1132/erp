"""备份任务化触发路由(M1)。

- POST /full          手动全量备份 → 202 {task_id}(ARQ 入队)
- POST /incremental   手动增量备份 → 202 {task_id}(ARQ 入队)

设计要点(v2 方案 §4.2):
- API 进程只做 鉴权/互斥检查/入队,不再同步执行长任务(原 POST /save 同步执行,
  全量耗时可达 1800s,Nginx 层易超时 → 本模块为替代入口)
- 互斥:PG advisory lock 为真相源(跨 4 worker);执行中返回 409 {code:"TASK_RUNNING"}
- 进度:任务内部写 Redis(erp:backup_progress:*),前端轮询 /progress/{task_id}
"""
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.api.v1.endpoints.backup._deps import require_backup_permission
from fastapi_app.core.database import get_async_db
from fastapi_app.schemas.backup import (
    BackupFullRequest,
    BackupIncrementalRequest,
    BackupTaskTriggerOut,
)
from fastapi_app.services import backup as backup_service
from fastapi_app.shared_models import User

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# 互斥检查
# ---------------------------------------------------------------------------
async def _check_task_mutex(db: AsyncSession) -> None:
    """任务互斥:备份/还原同时仅允许一个任务(409)。

    - 备份进行中:PG advisory lock(BACKUP_LOCK_ID)被持有 → 409
    - 还原进行中:Redis 还原锁存在 → 409

    注意(P0-5):本检查是 UX 级预检——"探测后释放、任务真正执行时再取锁"之间存在
    固定 TOCTOU 窗口。强互斥由任务内部的锁保证(备份取 advisory 锁、还原取 Redis
    锁),此处仅用于在入队前给用户快速反馈,不作为正确性依据。
    """
    backup_busy = await backup_service.acquire_backup_lock(db)
    if not backup_busy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={'code': 'TASK_RUNNING', 'message': '已有备份任务正在执行中，请稍后重试'},
        )
    await backup_service.release_backup_lock(db)

    restore_busy = await backup_service.is_restore_in_progress()
    if restore_busy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={'code': 'TASK_RUNNING', 'message': '已有还原任务正在执行中，请稍后重试'},
        )


async def _enqueue_task(
    func_name: str,
    **kwargs,
) -> str:
    """入队 ARQ 任务,返回 task_id。"""
    from fastapi_app.core.arq_app import get_arq_pool

    pool = await get_arq_pool()
    await pool.enqueue_job(func_name, **kwargs)
    return kwargs.get('task_id', '')


# ---------------------------------------------------------------------------
# POST /full
# ---------------------------------------------------------------------------
@router.post('/full', response_model=BackupTaskTriggerOut, status_code=status.HTTP_202_ACCEPTED)
async def trigger_full_backup(
    payload: BackupFullRequest,
    x_backup_password: str | None = Header(None, alias='X-Backup-Password'),
    user: User = Depends(require_backup_permission('trigger_full_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """手动全量备份(异步)。

    参数:
    - remark: 备份备注
    - encrypt: 是否启用加密,默认 True(未配置密码时降级为不加密)
    - password / X-Backup-Password: 加密密码

    返回 202 + task_id,前端轮询 GET /progress/{task_id} 获取进度。
    权限:backup_create
    """
    from fastapi_app.core.backup_progress import generate_task_id

    await _check_task_mutex(db)

    task_id = generate_task_id()
    password = payload.password or x_backup_password
    try:
        await _enqueue_task(
            'manual_full_backup_task',
            task_id=task_id,
            remark=payload.remark,
            encrypt=payload.encrypt,
            password=password,
        )
    except (RuntimeError, OSError, ConnectionError) as e:
        logger.error('入队全量备份任务失败: %s', e)
        raise HTTPException(status_code=500, detail='触发备份失败，请查看服务器日志') from e

    logger.info('全量备份已入队 task_id=%s operator=%s', task_id, getattr(user, 'username', '?'))
    return BackupTaskTriggerOut(
        task_id=task_id,
        message='全量备份任务已触发',
        task_name='manual_full_backup_task',
    )


# ---------------------------------------------------------------------------
# POST /incremental
# ---------------------------------------------------------------------------
@router.post('/incremental', response_model=BackupTaskTriggerOut, status_code=status.HTTP_202_ACCEPTED)
async def trigger_incremental_backup(
    payload: BackupIncrementalRequest,
    user: User = Depends(require_backup_permission('trigger_incremental_backup')),
    db: AsyncSession = Depends(get_async_db),
):
    """手动增量备份(异步)。

    参数:
    - remark: 备份备注
    - since: 增量基线时间戳,为空时自动取上次备份时间

    返回 202 + task_id,前端轮询 GET /progress/{task_id} 获取进度。
    权限:backup_create
    """
    from fastapi_app.core.backup_progress import generate_task_id

    await _check_task_mutex(db)

    task_id = generate_task_id()
    try:
        await _enqueue_task(
            'manual_incremental_backup_task',
            task_id=task_id,
            remark=payload.remark,
            since=payload.since,
        )
    except (RuntimeError, OSError, ConnectionError) as e:
        logger.error('入队增量备份任务失败: %s', e)
        raise HTTPException(status_code=500, detail='触发增量备份失败，请查看服务器日志') from e

    logger.info('增量备份已入队 task_id=%s operator=%s', task_id, getattr(user, 'username', '?'))
    return BackupTaskTriggerOut(
        task_id=task_id,
        message='增量备份任务已触发',
        task_name='manual_incremental_backup_task',
    )
