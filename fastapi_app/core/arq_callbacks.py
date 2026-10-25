"""
ARQ 任务生命周期回调

ARQ 0.28 只认 ``on_job_start`` / ``on_job_end`` 两个钩子，没有 ``on_job_failed``。
任务成败由 ``arq_app._tracked_job`` 在任务边界写进 ``ctx['_job_outcome']``，
本模块的 ``on_job_end`` 据此分流：

- success：回写调度终态 success + 记录耗时指标
- failed：写死信队列 + 失败指标 + 回写调度终态 failed + 严重告警
- retrying：本次只是重放前的一跳，保持 running，不落终态
"""
import json
import time
from datetime import datetime

from fastapi_app.core.logger import logger
from fastapi_app.core.schedule_status import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    mark_schedule_finished,
)

DLQ_KEY = 'arq:dead_letter'


async def _mark_schedule_outcome(ctx, status: str) -> None:
    """调度任务的终态回写；非调度任务（job id 无前缀）直接跳过。

    状态回写是**附带**动作：失败只告警，绝不能影响任务收尾或失败告警链路。
    """
    try:
        await mark_schedule_finished(ctx.get('job_id'), status)
    except Exception as e:  # broad-except: 回写失败不得影响回调主职责
        logger.warning('调度状态回写异常: %s', e)


async def on_job_start(ctx):
    """任务开始回调"""
    func_name = ctx.get('_job_function') or ctx.get('function', '')
    if callable(func_name):
        func_name = func_name.__name__
    job_id = ctx.get('job_id', '')
    job_try = ctx.get('job_try', 1)
    logger.debug('ARQ任务开始: func=%s id=%s try=%d', func_name, job_id, job_try)
    ctx['_start_time'] = time.time()


async def on_job_end(ctx):
    """任务结束回调：按任务边界记录的 outcome 分流（成败都要经过这里）。"""
    outcome = ctx.get('_job_outcome')
    if outcome == 'failed':
        await _handle_job_failure(ctx, ctx.get('_job_exception'))
    elif outcome == 'retrying':
        # ARQ 的 Retry/取消重放会再次调用本回调；此刻落终态会把「还在跑」误报成败。
        logger.debug('ARQ任务重放中: id=%s try=%s', ctx.get('job_id', ''), ctx.get('job_try', 1))
    else:
        # 未包 _tracked_job 的调用方保持旧语义；WorkerSettings 注册的任务全部已包。
        await _mark_schedule_outcome(ctx, STATUS_SUCCESS)
        await _mark_daily_cron_success(ctx)
    _record_runtime(ctx)


async def _mark_daily_cron_success(ctx) -> None:
    """日级 cron 成功后写当日标记，供 catch_up_daily_crons 判断是否需要补跑。"""
    from fastapi_app.core.arq_app import (
        _CRON_LAST_OK_PREFIX,
        _DAILY_CRON_NAMES,
        cron_schedules,
    )
    from fastapi_app.core.business_time import business_today
    from fastapi_app.core.redis_wrapper import safe_set

    func_name = ctx.get('_job_function') or ctx.get('function', '')
    if callable(func_name):
        func_name = func_name.__name__
    for entry in cron_schedules:
        if entry['name'] in _DAILY_CRON_NAMES and entry['func'].__name__ == func_name:
            await safe_set(
                f"{_CRON_LAST_OK_PREFIX}{entry['name']}",
                business_today().isoformat(),
                timeout=86400 * 2,
                context="日级 cron 补跑标记",
            )


def _record_runtime(ctx) -> None:
    start = ctx.get('_start_time')
    if start is None:
        return
    runtime = time.time() - start
    func_name = ctx.get('_job_function') or ctx.get('function', '')
    if callable(func_name):
        func_name = func_name.__name__
    func_name = str(func_name)

    try:
        from fastapi_app.core.metrics import TASK_RUNTIME_SECONDS
        TASK_RUNTIME_SECONDS.labels(task=func_name).observe(runtime)
    except Exception:  # noqa: S110 - defensive: metrics 未启用/初始化失败时任务指标静默降级，不影响任务执行
        pass

    if runtime > 60:
        logger.info('慢任务完成: func=%s id=%s runtime=%.1fs', func_name, ctx.get('job_id', ''), runtime)


async def _handle_job_failure(ctx, exc) -> None:
    """任务失败处理 - 写入死信队列+告警+指标（由 on_job_end 在 failed 分支调用）。"""
    if exc is None:
        exc = RuntimeError('任务失败（未捕获异常信息）')

    func_name = ctx.get('_job_function') or ctx.get('function', '')
    if callable(func_name):
        func_name = func_name.__name__
    func_name = str(func_name)
    job_id = ctx.get('job_id', '')
    job_try = ctx.get('job_try', 1)
    max_tries = ctx.get('_max_tries', ctx.get('max_tries', 3))

    logger.error(
        'ARQ任务失败[DLQ]: func=%s id=%s try=%d/%d exc=%s',
        func_name, job_id, job_try, max_tries, exc,
    )

    args = ctx.get('_job_args', ())
    kwargs = ctx.get('_job_kwargs', {})

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
    await _mark_schedule_outcome(ctx, STATUS_FAILED)
    logger.critical(
        'ALERT: ARQ任务失败需人工介入 func=%s id=%s exc=%s',
        func_name, job_id, exc,
    )
    # M-C（2026-10-25 审计）：接入 alert_service（critical 恒通知）。此前告警只有
    # 日志行——H-1 出货同步断流 3 天、408 条错误日志无人发现即后果。owner 配置
    # BACKUP_ALERT_EMAIL_/WEBHOOK_ 后自动外推；未配置时失败计数/冷却逻辑照常工作。
    try:
        from fastapi_app.services.backup.metrics.alert_service import alert_service
        await alert_service.send_alert(
            task_name=f'arq:{func_name}',
            # 异常消息可能携带整段 SQL/超长 payload，告警通道（邮件/Webhook）截断
            error=f'{type(exc).__name__}: {exc}'[:300],
            task_type='arq_task',
            severity='critical',
            additional_info={'job_id': job_id, 'job_try': job_try, 'max_tries': max_tries},
        )
    except Exception as alert_exc:  # defensive: 告警失败不得影响失败收尾链路
        logger.warning('ARQ 任务失败告警发送异常（忽略）: %s', alert_exc)


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
