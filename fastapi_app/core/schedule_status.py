"""backup_schedule.last_status 的终态回写。

问题（/backup 审计，high）
-------------------------
`scheduler_poller` 入队时写 `last_status='running'`，**此后再没有任何代码改它**——
生产库里 full / incremental 两行的状态永远停在 'running'，界面显示的"上次执行结果"
因此恒为"执行中"，运维据此判断会误以为任务卡死。

修法：调度入队时给 ARQ job 一个可解析的 id（`sched:{schedule_id}:{窗口}`），
任务结束/失败的 ARQ 回调再从 job_id 反解出 schedule_id 把终态写回。
不改动任何任务函数签名 —— 回调侧本就拿得到 job_id。
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

SCHEDULE_JOB_ID_PREFIX = 'sched:'

# 与 backup_schedule.last_status 列宽(20)及模型注释一致
STATUS_SUCCESS = 'success'
STATUS_FAILED = 'failed'
STATUS_RUNNING = 'running'


def schedule_job_id(schedule_id: int, when: datetime) -> str:
    """调度入队用的确定性 job id。

    带小时窗口：同一调度同一小时内重复入队会被 ARQ 以同名 job 去重（返回 None），
    这正是轮询器「本小时窗口已执行过」判定的原子版本；下一小时换新 id 照常执行。
    """
    return f'{SCHEDULE_JOB_ID_PREFIX}{schedule_id}:{when.strftime("%Y%m%d%H")}'


def parse_schedule_job_id(job_id: str | None) -> int | None:
    """从 job id 反解 schedule_id；不是调度任务则返回 None。"""
    if not job_id or not job_id.startswith(SCHEDULE_JOB_ID_PREFIX):
        return None
    rest = job_id[len(SCHEDULE_JOB_ID_PREFIX):]
    head = rest.split(':', 1)[0]
    try:
        return int(head)
    except ValueError:
        logger.warning('调度 job id 无法解析出 schedule_id: %r', job_id)
        return None


async def mark_schedule_finished(job_id: str | None, status: str) -> bool:
    """把某个调度任务的终态写回 backup_schedule。

    返回是否确实更新了一行。仅供 ARQ 回调调用，**绝不抛异常** ——
    状态回写失败不该影响任务收尾或告警链路。
    """
    schedule_id = parse_schedule_job_id(job_id)
    if schedule_id is None:
        return False
    try:
        from sqlalchemy import select

        from fastapi_app.core.database import get_async_db_context
        from fastapi_app.shared_models.backup_schedule import BackupSchedule

        async with get_async_db_context() as db:
            row = (await db.execute(
                select(BackupSchedule).where(BackupSchedule.id == schedule_id)
            )).scalar_one_or_none()
            if row is None:
                logger.warning('调度记录不存在，状态未回写: schedule_id=%s', schedule_id)
                return False
            row.last_status = status
            await db.commit()
            logger.info('调度状态回写: schedule_id=%s status=%s', schedule_id, status)
            return True
    except Exception as e:  # broad-except: 回调内不得因状态回写失败而中断任务收尾/告警
        logger.warning('调度状态回写失败（schedule_id=%s, status=%s）: %s', schedule_id, status, e)
        return False
