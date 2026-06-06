"""
Celery 任务回调

- on_failure: 任务重试耗尽后，将失败信息写入 dead_letter 队列并触发告警
- on_retry:  记录重试事件到结构化日志
- on_success: 记录任务成功耗时
"""
import json
import time
from datetime import datetime

from fastapi_app.core.logger import logger


def on_task_failure(task_id, task_name, args, kwargs, exc, traceback):
    logger.error(
        '任务失败[DLQ]: task=%s id=%s retries_exhausted exc=%s',
        task_name, task_id, exc,
    )
    dead_letter_entry = {
        'task_id': task_id,
        'task_name': task_name,
        'args': _safe_repr(args),
        'kwargs': _safe_repr(kwargs),
        'exception': str(exc),
        'traceback': _safe_repr(traceback) if traceback else None,
        'failed_at': datetime.now().isoformat(),
        'status': 'FAILED',
    }
    _push_to_dead_letter(dead_letter_entry)
    _send_failure_alert(task_name, task_id, exc)


def on_task_retry(task_id, task_name, args, kwargs, exc, retries, max_retries):
    logger.warning(
        '任务重试: task=%s id=%s retry=%d/%d exc=%s',
        task_name, task_id, retries, max_retries, exc,
    )


def on_task_success(task_id, task_name, args, kwargs, result, runtime):
    if runtime and runtime > 60:
        logger.info(
            '慢任务完成: task=%s id=%s runtime=%.1fs',
            task_name, task_id, runtime,
        )


def _push_to_dead_letter(entry: dict):
    try:
        from utils.redis_cache import redis_cache
        if redis_cache.redis_client:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(
                        lambda: asyncio.run(
                            redis_cache.redis_client.lpush(
                                'celery:dead_letter',
                                json.dumps(entry, ensure_ascii=False, default=str),
                            )
                        )
                    )
            else:
                asyncio.run(
                    redis_cache.redis_client.lpush(
                        'celery:dead_letter',
                        json.dumps(entry, ensure_ascii=False, default=str),
                    )
                )
    except Exception as e:
        logger.warning('死信队列写入失败: %s', e)


def _send_failure_alert(task_name: str, task_id: str, exc):
    try:
        from fastapi_app.core.metrics import TASK_FAILURE_TOTAL
        TASK_FAILURE_TOTAL.labels(task=task_name).inc()
    except Exception:
        pass
    logger.critical(
        'ALERT: Celery任务失败需人工介入 task=%s id=%s exc=%s',
        task_name, task_id, exc,
    )


def _safe_repr(obj, max_len: int = 500) -> str:
    try:
        s = repr(obj)
        return s[:max_len] + '...' if len(s) > max_len else s
    except Exception:
        return '<unrepresentable>'
