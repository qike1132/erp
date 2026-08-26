"""ARQ 任务队列配置（替代 Celery）。

ARQ 是原生 async 任务队列，与 FastAPI async 架构一致，
消除 Celery 同步任务与 async 事件循环的割裂。

- Worker 启动：`arq fastapi_app.core.arq_app.WorkerSettings`
- Web 进程入队：`await get_arq_pool().enqueue_job(func_name, *args)`
- 定时任务：cron_jobs（内置于 worker，无需独立 beat 进程）
"""
import logging
import os
from typing import ClassVar

from arq import create_pool, cron
from arq.connections import RedisSettings

from fastapi_app.core.arq_callbacks import on_job_end, on_job_failed, on_job_started
from fastapi_app.core.config import settings

logger = logging.getLogger(__name__)

# 队列名称（保持与 Celery 一致的路由语义，供 _queue_name 使用）
QUEUE_BATCH = 'io.batch'
QUEUE_REPORTS = 'io.reports'
QUEUE_BACKUP = 'io.backup'
QUEUE_PLAN = 'io.plan'

# Redis 配置（独立 broker 实例，与缓存实例隔离）
# 优先使用 REDIS_BROKER_URL；未配置时回退到通用 REDIS_HOST/PORT/DB
def _build_redis_settings() -> RedisSettings:
    broker_url = getattr(settings, 'REDIS_BROKER_URL', '') or os.getenv('REDIS_BROKER_URL', '')
    if broker_url:
        return RedisSettings.from_dsn(broker_url)
    return RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=settings.REDIS_PASSWORD or None,
        database=settings.REDIS_DB or 0,
    )


redis_settings = _build_redis_settings()

# 任务注册：ARQ 通过 functions 列表注册，按函数 __name__ 派发
from fastapi_app.tasks.backup_tasks import (
    apply_backup_policy_task,
    auto_daily_backup_task,
    auto_incremental_backup_task,
    backup_cleanup_task,
    backup_health_check_task,
    backup_integrity_check_task,
    backup_metrics_report_task,
    disaster_recovery_test_task,
    manual_full_backup_task,
    manual_incremental_backup_task,
    scheduler_poller,
)
from fastapi_app.tasks.batch_tasks import (
    batch_import_orders_task,
    batch_import_stockins_task,
)
from fastapi_app.tasks.maintenance_tasks import (
    ensure_readonly_grants_task,
    refresh_dashboard_mv_task,
)
from fastapi_app.tasks.plan_tasks import (
    batch_import_plans_task,
    sync_shipment_records_task,
)
from fastapi_app.tasks.report_tasks import export_report_task

# ---------------------------------------------------------------------------
# 定时任务（替代 Celery beat_schedule）
# ---------------------------------------------------------------------------
# cron_schedules 同时供 worker（派生 cron_jobs）与 backup 端点（列出/触发）使用，
# 避免两处维护。ARQ 的 cron() 支持 hour/minute 为 int 或 set。
# max_tries=3 对应 Celery max_retries=2（总尝试次数 = 重试次数 + 1）。
cron_schedules = [
    {
        'name': 'sync-shipment-daily',
        'func': sync_shipment_records_task,
        'cron': {'hour': 1, 'minute': 0},
        'schedule': '1:00',
    },
    {
        # M2: 备份 4 项定时（完整性巡检/全量/增量/清理）已迁入 backup_schedule 表，
        # 由下方 scheduler_poller 每 5 分钟扫描调度执行，保持 02:00/06-22/03:00/04:00 等价。
        'name': 'backup-schedule-poller',
        'func': scheduler_poller,
        'cron': {'minute': set(range(0, 60, 5))},
        'schedule': 'every 5m',
        'timeout': 300,
    },
    {
        # 原 Celery beat: 300.0（每 5 分钟）。ARQ cron 不支持步进值，用 minute 集合表达。
        'name': 'refresh-dashboard-mv',
        'func': refresh_dashboard_mv_task,
        'cron': {'minute': set(range(0, 60, 5))},
        'schedule': 'every 5m',
    },
    {
        # 只读副本授权对账：数据库恢复会清空 erp_readonly 授权（只读接口 500），
        # 此处周期自愈兜底（与恢复完成即自愈双保险）。10 分钟一次，幂等低开销。
        'name': 'readonly-grants-reconcile',
        'func': ensure_readonly_grants_task,
        'cron': {'minute': set(range(0, 60, 10))},
        'schedule': 'every 10m',
    },
]

cron_jobs = [
    cron(s['func'], max_tries=3, timeout=s.get('timeout'), **s['cron'])  # type: ignore[arg-type]
    for s in cron_schedules
]


class WorkerSettings:
    """ARQ Worker 配置（`arq fastapi_app.core.arq_app.WorkerSettings`）。"""

    functions: ClassVar[list] = [
        batch_import_orders_task,
        batch_import_stockins_task,
        scheduler_poller,
        auto_daily_backup_task,
        auto_incremental_backup_task,
        manual_full_backup_task,
        manual_incremental_backup_task,
        backup_integrity_check_task,
        backup_cleanup_task,
        backup_health_check_task,
        apply_backup_policy_task,
        disaster_recovery_test_task,
        backup_metrics_report_task,
        export_report_task,
        sync_shipment_records_task,
        batch_import_plans_task,
        refresh_dashboard_mv_task,
        ensure_readonly_grants_task,
    ]
    cron_jobs = cron_jobs
    redis_settings = redis_settings
    max_jobs = 10
    job_timeout = 1800
    max_tries = 3
    on_job_started = on_job_started
    on_job_end = on_job_end
    on_job_failed = on_job_failed


# ---------------------------------------------------------------------------
# Web 进程入队辅助（FastAPI 端点调用）
# ---------------------------------------------------------------------------
_arq_pool = None


async def get_arq_pool():
    """获取共享 ARQ Redis 连接池，用于在 Web 进程中入队任务。

    连接池在首次调用时创建并复用，避免每次入队都新建连接。
    """
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(redis_settings)
    return _arq_pool


async def check_worker_health() -> tuple[bool, str]:
    """检测 ARQ Worker 是否在线（入队前预检）。

    通过 ARQ 连接池的 health() 命令查询 broker 上的 worker 心跳。
    ARQ Worker 启动后会定期在 Redis broker 上注册自身，
    若无 worker 注册则 health() 返回空 workers 列表。

    Returns:
        (is_healthy, message):
        - (True, 'ARQ Worker 在线，N 个 worker 就绪')
        - (False, 'ARQ Worker 未运行，请启动 erp-arq 服务')
    """
    try:
        pool = await get_arq_pool()
        health = await pool.health()
        # health 返回 dict，包含 'workers' 键（worker 心跳列表）
        workers = health.get('workers', []) if isinstance(health, dict) else []
        if workers:
            return True, f'ARQ Worker 在线，{len(workers)} 个 worker 就绪'
        return False, 'ARQ Worker 未运行，请启动 erp-arq 服务'
    except Exception as e:
        logger.warning('ARQ Worker 健康检测失败: %s', e)
        return False, f'ARQ Worker 健康检测失败: {type(e).__name__}'
