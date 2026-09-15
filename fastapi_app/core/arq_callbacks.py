"""
ARQ 任务生命周期回调

- on_job_failed: 任务重试耗尽后，将失败信息写入死信队列并触发告警+指标
- on_job_started: 记录任务开始事件
- on_job_end: 记录任务耗时指标
"""
import json
import time
from datetime import datetime

from fastapi_app.core.logger import logger

DLQ_KEY = 'arq:dead_letter'


async def on_job_started(ctx):
    """任务开始回调"""
    func_name = ctx.get('function', '').__name__ if callable(ctx.get('function')) else str(ctx.get('function', ''))
    job_id = ctx.get('job_id', '')
    job_try = ctx.get('job_try', 1)
    logger.debug('ARQ任务开始: func=%s id=%s try=%d', func_name, job_id, job_try)
    ctx['_start_time'] = time.time()


async def on_job_end(ctx):
    """任务结束回调 - 记录耗时指标"""
    start = ctx.get('_start_time')
    if start is None:
        return
    runtime = time.time() - start
    func_name = ctx.get('function', '')
    func_name = func_name.__name__ if callable(func_name) else str(func_name)

    try:
        from fastapi_app.core.metrics import TASK_RUNTIME_SECONDS
        TASK_RUNTIME_SECONDS.labels(task=func_name).observe(runtime)
    except Exception:  # noqa: S110 - defensive: metrics 未启用/初始化失败时任务指标静默降级，不影响任务执行
        pass

    if runtime > 60:
        logger.info('慢任务完成: func=%s id=%s runtime=%.1fs', func_name, ctx.get('job_id', ''), runtime)


async def on_job_failed(ctx, exc):
    """任务失败回调 - 写入死信队列+告警+指标

    ARQ在max_tries耗尽后调用此回调。
    """
    func = ctx.get('function', '')
    func_name = func.__name__ if callable(func) else str(func)
    job_id = ctx.get('job_id', '')
    job_try = ctx.get('job_try', 1)
    max_tries = ctx.get('max_tries', 3)

    logger.error(
        'ARQ任务失败[DLQ]: func=%s id=%s try=%d/%d exc=%s',
        func_name, job_id, job_try, max_tries, exc,
    )

    args = ctx.get('args', ())
    kwargs = ctx.get('kwargs', {})

    dead_letter_entry = {
        'task_id': job_id,
        'task_name': func_name,
        'args': _safe_repr(args),
        'kwargs': _safe_repr(kwargs),
        'exception': str(exc),
        'exception_type': type(exc).__name__,
        'failed_at': datetime.now().isoformat(),
        'status': 'FAILED',
        'job_try': job_try,
        'max_tries': max_tries,
    }

    await _push_to_dead_letter(dead_letter_entry)
    _emit_failure_metric(func_name)
    logger.critical(
        'ALERT: ARQ任务失败需人工介入 func=%s id=%s exc=%s',
        func_name, job_id, exc,
    )


async def _push_to_dead_letter(entry: dict):
    """将失败任务信息写入Redis死信队列"""
    try:
        from fastapi_app.core.redis_wrapper import safe_lpush
        await safe_lpush(DLQ_KEY, json.dumps(entry, ensure_ascii=False, default=str), context="死信队列")
    except Exception as e:  # broad-except: 死信队列是失败任务的最后兜底，写入失败只能告警，不得掩盖原始失败
        logger.warning('死信队列写入失败: %s', e)


def _emit_failure_metric(task_name: str):
    """发送Prometheus失败指标"""
    try:
        from fastapi_app.core.metrics import TASK_FAILURE_TOTAL
        TASK_FAILURE_TOTAL.labels(task=task_name).inc()
    except Exception:  # noqa: S110 - defensive: 失败指标上报静默降级，不影响告警主链路
        pass


def _safe_repr(obj, max_len: int = 500) -> str:
    try:
        s = repr(obj)
        return s[:max_len] + '...' if len(s) > max_len else s
    except Exception:  # broad-except: 任意对象的 __repr__ 都可能抛错，序列化告警信息时不得中断
        return '<unrepresentable>'
