"""ARQ 任务队列配置（替代 Celery）。

ARQ 是原生 async 任务队列，与 FastAPI async 架构一致，
消除 Celery 同步任务与 async 事件循环的割裂。

- Worker 启动：`arq fastapi_app.core.arq_app.WorkerSettings`
- Web 进程入队：`await get_arq_pool().enqueue_job(func_name, *args)`
- 定时任务：cron_jobs（内置于 worker，无需独立 beat 进程）
"""
import asyncio
import contextlib
import logging
import os
from typing import ClassVar

from arq import create_pool, cron
from arq.connections import RedisSettings
from arq.constants import default_queue_name, health_check_key_suffix

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
    redis_pwd = settings.REDIS_PASSWORD or None
    return RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        password=redis_pwd,
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
    rotate_nginx_logs_task,
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
    {
        # nginx 日志轮转：prod_runner 不再托管 nginx 后的轮转归属。
        # ARQ 停摆仅意味着暂不轮转(优雅降级),阈值 100MB。
        'name': 'nginx-log-rotation',
        'func': rotate_nginx_logs_task,
        'cron': {'hour': 4, 'minute': 30},
        'schedule': '4:30',
        'timeout': 120,
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
    # 哨兵键刷新周期（秒）：默认 3600 意味着 worker 硬崩溃后最长 1 小时仍误报在线，
    # 显式缩短到 60s（TTL = interval + 1s，见 check_worker_health）。
    health_check_interval = 60
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
_pool_lock = asyncio.Lock()


async def get_arq_pool():
    """获取共享 ARQ Redis 连接池，用于在 Web 进程中入队任务。

    连接池在首次调用时创建并复用，避免每次入队都新建连接。
    使用 asyncio.Lock + 双重检查防止并发首次调用创建多个连接池。
    """
    global _arq_pool
    if _arq_pool is None:
        async with _pool_lock:
            if _arq_pool is None:
                _arq_pool = await create_pool(redis_settings)
    return _arq_pool


# 健康探测超时上限（秒）：broker 假死（TCP 可连不回包）时，探测须在该时长内返回
_HEALTH_PROBE_TIMEOUT = 2.0


def _health_check_key(pool) -> str:
    """返回 ARQ 健康哨兵键：queue_name + ':health-check'。

    优先取连接池自身的 default_queue_name（与 enqueue_job 实际入队的队列一致），
    取不到时回退到 arq 的模块级默认值。
    """
    queue_name = getattr(pool, 'default_queue_name', None) or default_queue_name
    return queue_name + health_check_key_suffix


async def check_worker_health() -> tuple[bool, str]:
    """检测 ARQ Worker 是否在线（入队前预检）。

    通过读取 ARQ 官方健康检查哨兵键（queue_name + ':health-check'）判定：
    Worker 存活期间按 health_check_interval 周期刷新该键
    （TTL = health_check_interval + 1s），正常退出时主动删除，
    进程硬崩溃后键在 TTL 内自然过期。

    ⚠️ arq 0.28 的 ``ArqRedis`` **没有** ``health()`` 方法；哨兵键是唯一官方
    可用的探测手段（arq CLI 的 ``--check`` 走的也是同一个键）。曾因误用
    ``pool.health()`` 导致所有手动备份被 503 误拦截，勿再改回。

    Returns:
        (is_healthy, message):
        - (True, 'ARQ Worker 在线（<心跳详情>）')
        - (False, 'ARQ Worker 未运行，请启动 erp-arq 服务')
        - (False, 'ARQ Worker 健康探测超时/失败: ...')  探测自身异常时的降级返回
    """
    try:
        pool = await get_arq_pool()
        value = await asyncio.wait_for(
            pool.get(_health_check_key(pool)),
            timeout=_HEALTH_PROBE_TIMEOUT,
        )
        if value:
            detail = value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)
            return True, f'ARQ Worker 在线（{detail}）'
        return False, 'ARQ Worker 未运行，请启动 erp-arq 服务'
    except TimeoutError:
        logger.warning('ARQ Worker 健康探测超时(>%ss)，broker 疑似不可达', _HEALTH_PROBE_TIMEOUT)
        return False, f'ARQ Worker 健康探测超时（>{_HEALTH_PROBE_TIMEOUT:g}s），请检查 erp-redis-broker 服务'
    except Exception as e:  # broad-except: 健康探测自身不得抛出，任何异常都须转成"不健康"返回值
        logger.warning('ARQ Worker 健康检测失败: %s', e)
        return False, f'ARQ Worker 健康检测失败: {type(e).__name__}'


async def probe_worker_health_isolated(timeout: float = 1.0) -> bool:
    """健康端点专用：用**短命连接池**判定 ARQ worker 是否在线，绝不触碰全局池。

    为什么必须隔离：``get_arq_pool()`` 的池在首次调用时创建，并**绑定当时的事件循环**
    后被长期缓存。``/api/health`` 被高频调用、也可能在不同事件循环下被调用（测试、
    多 loop 场景），复用绑定在已关闭 loop 上的连接会抛
    ``Event loop is closed`` / ``'NoneType' object has no attribute 'send'``，
    污染整条健康探测链路。探测只是一次 GET，短命连接的代价由 /api/health 的
    10s 缓存兜住。
    """
    pool = None
    try:
        pool = await create_pool(redis_settings)
        value = await asyncio.wait_for(pool.get(_health_check_key(pool)), timeout=timeout)
        return bool(value)
    except Exception as e:  # broad-except: 探测自身不得抛出，任何异常一律按"不在线"处理
        logger.debug('ARQ 隔离探针失败(按不在线处理): %s', e)
        return False
    finally:
        if pool is not None:
            with contextlib.suppress(Exception):
                await pool.aclose()
