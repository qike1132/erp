"""OCR 导入进度管理（Redis 存储，跨 worker 可见）

2026-10-17 审计 AUD-03：原实现把进度放在模块级 dict，4 个 uvicorn worker 各一份——
轮询请求被分到非创建 worker 时查不到任务，端点静默新建一个全 0 进度，
前端永远「处理中 0%」。现改为 Redis 存储（TTL 1h），Redis 不可用时降级为
进程内字典（单 worker/开发环境仍可用）。

接口为 async：调用方（端点与 OCR 导入链路）均已处于异步上下文。
"""
import json
import logging
import uuid

import redis

from fastapi_app.core.redis_client import get_async_redis_client

logger = logging.getLogger(__name__)

_KEY_PREFIX = 'erp:ocr_progress:'
_PROGRESS_TTL = 3600

# Redis 不可用时的进程内降级（保留给单 worker / 开发环境）
_progress_store: dict[str, dict] = {}

# 与 core/cache.py 同口径：redis-py 异常族不继承内建异常，必须显式纳入 RedisError
_INFRA_ERRORS = (OSError, ConnectionError, redis.RedisError, ValueError)


def _key(task_id: str) -> str:
    return f'{_KEY_PREFIX}{task_id}'


async def _get_client():
    try:
        return await get_async_redis_client()
    except _INFRA_ERRORS:
        return None


async def _write(task_id: str, data: dict) -> None:
    client = await _get_client()
    if client is not None:
        try:
            await client.set(_key(task_id), json.dumps(data, ensure_ascii=False), ex=_PROGRESS_TTL)
            return
        except _INFRA_ERRORS as exc:
            logger.warning('OCR 进度写入 Redis 失败，降级进程内存储: %s', exc)
    _progress_store[task_id] = data


async def create_progress() -> str:
    task_id = uuid.uuid4().hex
    await _write(task_id, {'status': 'pending', 'percent': 0, 'message': '等待处理...', 'filename': ''})
    return task_id


async def get_progress(task_id: str) -> dict | None:
    """返回进度字典；不存在/已过期返回 None（端点据此返回 not_found 终态）。"""
    client = await _get_client()
    if client is not None:
        try:
            raw = await client.get(_key(task_id))
            if raw is not None:
                return json.loads(raw)
            return _progress_store.get(task_id)
        except _INFRA_ERRORS as exc:
            logger.warning('OCR 进度读取 Redis 失败，降级进程内存储: %s', exc)
    return _progress_store.get(task_id)


async def _update_progress(task_id: str, **kwargs) -> None:
    """更新进度；未知 task_id 自动初始化（上传端点可能先于 create-task 被调用）。"""
    current = await get_progress(task_id)
    if current is None:
        current = {'status': 'pending', 'percent': 0, 'message': '', 'filename': ''}
    if kwargs.get('status') != 'error' and 'percent' in kwargs:
        kwargs['percent'] = max(kwargs['percent'], current.get('percent', 0))
    current.update(kwargs)
    await _write(task_id, current)
