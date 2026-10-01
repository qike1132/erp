"""
死信队列(DLQ)管理端点

提供失败任务查看、重试、清除等操作

注意：失败任务的 args/kwargs 以 repr 字符串存储，
因此读取时需要 ast.literal_eval 反序列化，以便 enqueue_job 收到正确的参数类型。
"""
import ast
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from fastapi_app.core.deps import require_permission
from fastapi_app.core.logger import logger
from fastapi_app.core.redis_wrapper import get_client, safe_llen, safe_lrange, safe_lrem
from fastapi_app.shared_models import User

router = APIRouter()

DLQ_KEY = 'arq:dead_letter'


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
    queue_key: str = "arq:dead_letter"


def _require_redis():
    client = get_client()
    if not client:
        raise HTTPException(503, 'Redis不可用')
    return client


def _parse_dead_letter_args(args_raw) -> list:
    """将 repr 存储的 args 字符串还原为参数列表。

    失败任务使用 repr() 序列化 args/kwargs，
    ast.literal_eval 可安全地将 repr 字符串还原为原始 Python 对象。
    """
    if isinstance(args_raw, (list, tuple)):
        return list(args_raw)
    if not isinstance(args_raw, str):
        return []
    try:
        parsed = ast.literal_eval(args_raw)
        if isinstance(parsed, tuple):
            return list(parsed)
        return parsed if isinstance(parsed, list) else [parsed]
    except (ValueError, SyntaxError):
        logger.warning('无法解析死信任务参数: %s', args_raw[:200])
        return [args_raw]


def _parse_dead_letter_kwargs(kwargs_raw) -> dict:
    """将 repr 存储的 kwargs 字符串还原为参数字典。"""
    if isinstance(kwargs_raw, dict):
        return kwargs_raw
    if not isinstance(kwargs_raw, str):
        return {}
    try:
        parsed = ast.literal_eval(kwargs_raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, SyntaxError):
        logger.warning('无法解析死信任务关键字参数: %s', kwargs_raw[:200])
        return {}


@router.get('/dead-letter', response_model=DeadLetterListResponse, summary='查看死信队列中的失败任务')
async def list_dead_letter(
    limit: int = Query(50, ge=1, le=200, description='返回条数'),
    offset: int = Query(0, ge=0, description='偏移量'),
    _user: User = Depends(require_permission('admin')),
):
    try:
        _require_redis()
        total = await safe_llen(DLQ_KEY, context="死信队列")
        entries_raw = await safe_lrange(DLQ_KEY, offset, offset + limit - 1, context="死信队列")
        entries = [json.loads(e) for e in entries_raw]
        return {'total': total, 'offset': offset, 'limit': limit, 'entries': entries}
    except HTTPException:
        raise
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error('查询死信队列失败: %s', e)
        raise HTTPException(500, f'查询失败: {e}') from e


@router.post('/dead-letter/{task_id}/retry', response_model=DeadLetterRetryResponse, summary='重试死信队列中的失败任务')
async def retry_dead_letter_task(task_id: str, _user: User = Depends(require_permission('admin'))):
    try:
        _require_redis()
        entries_raw = await safe_lrange(DLQ_KEY, 0, -1, context="死信队列")
        target_idx = None
        target_entry = None
        for i, raw in enumerate(entries_raw):
            entry = json.loads(raw)
            if entry.get('task_id') == task_id:
                target_idx = i
                target_entry = entry
                break
        if target_idx is None or target_entry is None:
            raise HTTPException(404, f'任务 {task_id} 不在死信队列中')
        task_name = target_entry.get('task_name')
        args = _parse_dead_letter_args(target_entry.get('args', []))
        kwargs = _parse_dead_letter_kwargs(target_entry.get('kwargs', {}))
        from fastapi_app.core.arq_app import get_arq_pool
        pool = await get_arq_pool()
        job = await pool.enqueue_job(task_name, *args, **kwargs)
        new_id = job.job_id if job else ''
        await safe_lrem(DLQ_KEY, 1, entries_raw[target_idx], context="死信队列")
        logger.info('重试死信任务: %s -> new_id=%s', task_id, new_id)
        return {
            'status': 'retried',
            'original_task_id': task_id,
            'new_task_id': new_id,
            'task_name': task_name,
        }
    except HTTPException:
        raise
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error('重试死信任务失败: %s', e)
        raise HTTPException(500, f'重试失败: {e}') from e


@router.delete('/dead-letter/{task_id}', response_model=DeadLetterRemoveResponse, summary='从死信队列中移除失败任务')
async def remove_dead_letter_task(task_id: str, _user: User = Depends(require_permission('admin'))):
    try:
        _require_redis()
        entries_raw = await safe_lrange(DLQ_KEY, 0, -1, context="死信队列")
        removed = False
        for raw in entries_raw:
            entry = json.loads(raw)
            if entry.get('task_id') == task_id:
                await safe_lrem(DLQ_KEY, 1, raw, context="死信队列")
                removed = True
                break
        if not removed:
            raise HTTPException(404, f'任务 {task_id} 不在死信队列中')
        return {'status': 'removed', 'task_id': task_id}
    except HTTPException:
        raise
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error('移除死信任务失败: %s', e)
        raise HTTPException(500, f'移除失败: {e}') from e


@router.get('/dead-letter/stats', response_model=DeadLetterStatsResponse, summary='死信队列统计')
async def dead_letter_stats(_user: User = Depends(require_permission('admin'))):
    try:
        _require_redis()
        total = await safe_llen(DLQ_KEY, context="死信队列")
        return {'total_failed': total, 'queue_key': DLQ_KEY}
    except HTTPException:
        raise
    except Exception as e:  # broad-except: 端点层兜底捕获所有异常并转为 HTTP 响应
        logger.error('死信队列统计失败: %s', e)
        raise HTTPException(500, f'统计失败: {e}') from e
