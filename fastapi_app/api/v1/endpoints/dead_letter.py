"""
死信队列(DLQ)管理端点

提供失败任务查看、重试、清除等操作
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.shared_models import User

router = APIRouter()


class DeadLetterListResponse(BaseModel):
    total: int = 0
    offset: int = 0
    limit: int = 50
    entries: list[dict] = []


class DeadLetterRetryResponse(BaseModel):
    status: str = "retried"
    original_task_id: str = ""
    new_task_id: str = ""
    task_name: str = ""


class DeadLetterRemoveResponse(BaseModel):
    status: str = "removed"
    task_id: str = ""


class DeadLetterStatsResponse(BaseModel):
    total_failed: int = 0
    queue_key: str = "celery:dead_letter"


@router.get('/dead-letter', response_model=DeadLetterListResponse, summary='查看死信队列中的失败任务')
async def list_dead_letter(
    limit: int = Query(50, ge=1, le=200, description='返回条数'),
    offset: int = Query(0, ge=0, description='偏移量'),
    _user: User = Depends(require_permission('admin')),
):
    try:
        from utils.redis_cache import redis_cache
        if not redis_cache.redis_client:
            raise HTTPException(503, 'Redis不可用')
        total = await redis_cache.redis_client.llen('celery:dead_letter')
        entries_raw = await redis_cache.redis_client.lrange(
            'celery:dead_letter', offset, offset + limit - 1,
        )
        import json
        entries = [json.loads(e) for e in entries_raw]
        return {'total': total, 'offset': offset, 'limit': limit, 'entries': entries}
    except HTTPException:
        raise
    except Exception as e:
        logger.error('查询死信队列失败: %s', e)
        raise HTTPException(500, f'查询失败: {e}')


@router.post('/dead-letter/{task_id}/retry', response_model=DeadLetterRetryResponse, summary='重试死信队列中的失败任务')
async def retry_dead_letter_task(task_id: str, _user: User = Depends(require_permission('admin'))):
    try:
        from utils.redis_cache import redis_cache
        if not redis_cache.redis_client:
            raise HTTPException(503, 'Redis不可用')
        import json
        entries_raw = await redis_cache.redis_client.lrange('celery:dead_letter', 0, -1)
        target_idx = None
        target_entry = None
        for i, raw in enumerate(entries_raw):
            entry = json.loads(raw)
            if entry.get('task_id') == task_id:
                target_idx = i
                target_entry = entry
                break
        if target_idx is None:
            raise HTTPException(404, f'任务 {task_id} 不在死信队列中')
        task_name = target_entry.get('task_name')
        args = target_entry.get('args', [])
        kwargs = target_entry.get('kwargs', {})
        from fastapi_app.core.celery_app import celery_app
        task_func = celery_app.tasks.get(task_name)
        if not task_func:
            raise HTTPException(400, f'任务 {task_name} 未注册')
        new_result = task_func.apply_async(args=args, kwargs=kwargs)
        await redis_cache.redis_client.lrem('celery:dead_letter', 1, entries_raw[target_idx])
        logger.info('重试死信任务: %s -> new_id=%s', task_id, new_result.id)
        return {
            'status': 'retried',
            'original_task_id': task_id,
            'new_task_id': new_result.id,
            'task_name': task_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error('重试死信任务失败: %s', e)
        raise HTTPException(500, f'重试失败: {e}')


@router.delete('/dead-letter/{task_id}', response_model=DeadLetterRemoveResponse, summary='从死信队列中移除失败任务')
async def remove_dead_letter_task(task_id: str, _user: User = Depends(require_permission('admin'))):
    try:
        from utils.redis_cache import redis_cache
        if not redis_cache.redis_client:
            raise HTTPException(503, 'Redis不可用')
        import json
        entries_raw = await redis_cache.redis_client.lrange('celery:dead_letter', 0, -1)
        removed = False
        for raw in entries_raw:
            entry = json.loads(raw)
            if entry.get('task_id') == task_id:
                await redis_cache.redis_client.lrem('celery:dead_letter', 1, raw)
                removed = True
                break
        if not removed:
            raise HTTPException(404, f'任务 {task_id} 不在死信队列中')
        return {'status': 'removed', 'task_id': task_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error('移除死信任务失败: %s', e)
        raise HTTPException(500, f'移除失败: {e}')


@router.get('/dead-letter/stats', response_model=DeadLetterStatsResponse, summary='死信队列统计')
async def dead_letter_stats(_user: User = Depends(require_permission('admin'))):
    try:
        from utils.redis_cache import redis_cache
        if not redis_cache.redis_client:
            raise HTTPException(503, 'Redis不可用')
        total = await redis_cache.redis_client.llen('celery:dead_letter')
        return {'total_failed': total, 'queue_key': 'celery:dead_letter'}
    except HTTPException:
        raise
    except Exception as e:
        logger.error('死信队列统计失败: %s', e)
        raise HTTPException(500, f'统计失败: {e}')
