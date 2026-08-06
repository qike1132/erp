"""
Celery 应用配置
使用 Redis 作为 Broker 和 Result Backend
优化: Worker 并发、任务路由、事件监控、Redis 连接池、死信队列(DLQ)
"""
from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from fastapi_app.core.config import settings

celery_app = Celery(
    "erp_system",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

DEFAULT_EXCHANGE = Exchange('tasks', type='direct')
DLX_EXCHANGE = Exchange('dlx', type='direct')
# I/O 密集型任务专用队列：备份、报表导出、批量导入、计划同步等
# 由 gevent pool worker 消费，以高并发处理等待型任务（DB/文件/网络 I/O）
IO_QUEUE = 'io'
# I/O 子队列：按业务类型隔离，避免长任务互相阻塞（如备份不阻塞报表导出）
IO_QUEUE_REPORTS = 'io.reports'
IO_QUEUE_BACKUP = 'io.backup'
IO_QUEUE_BATCH = 'io.batch'
IO_QUEUE_PLAN = 'io.plan'

celery_app.conf.update(
    # 序列化（已强制 JSON，禁用 pickle RCE 风险）
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,  # 以UTC存储时间戳，按时区调度crontab

    # 结果过期时间（1小时后自动清理）
    result_expires=3600,

    # 任务限制
    task_soft_time_limit=300,   # 5分钟软超时
    task_time_limit=600,        # 10分钟硬超时

    # 重试策略
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Worker 并发优化
    worker_prefetch_multiplier=1,       # 每次只取1个任务，避免长任务阻塞短任务
    worker_max_tasks_per_child=1000,    # 每1000个任务重启Worker进程，防止内存泄漏
    worker_max_memory_per_child=300000, # 300MB 内存上限后重启子进程
    worker_disable_rate_limits=True,    # 禁用速率限制（减少Redis开销，由SlowAPI在API层限流）

    # 默认队列（未路由的任务进入 celery 队列）
    task_default_queue="celery",
    task_default_exchange="tasks",
    task_default_routing_key="task.default",

    # 任务路由：I/O 密集型任务按业务类型进入不同子队列，避免长任务互相阻塞
    # 其他任务进入默认 celery 队列，由 prefork worker 处理
    task_routes={
        "fastapi_app.tasks.batch_tasks.*": {"queue": IO_QUEUE_BATCH},
        "fastapi_app.tasks.report_tasks.*": {"queue": IO_QUEUE_REPORTS},
        "fastapi_app.tasks.plan_tasks.*": {"queue": IO_QUEUE_PLAN},
        "fastapi_app.tasks.backup_tasks.*": {"queue": IO_QUEUE_BACKUP},
        "fastapi_app.tasks.maintenance_tasks.*": {"queue": IO_QUEUE_PLAN},
    },

    # 队列定义（显式声明所有队列，确保队列存在）
    # dead_letter 队列用于接收重试耗尽的任务，供人工介入/告警
    task_queues=(
        Queue("celery", DEFAULT_EXCHANGE, routing_key="task.default"),
        Queue("batch", DEFAULT_EXCHANGE, routing_key="task.batch"),
        Queue("reports", DEFAULT_EXCHANGE, routing_key="task.reports"),
        Queue(IO_QUEUE, DEFAULT_EXCHANGE, routing_key="task.io"),
        Queue(IO_QUEUE_REPORTS, DEFAULT_EXCHANGE, routing_key="task.io.reports"),
        Queue(IO_QUEUE_BACKUP, DEFAULT_EXCHANGE, routing_key="task.io.backup"),
        Queue(IO_QUEUE_BATCH, DEFAULT_EXCHANGE, routing_key="task.io.batch"),
        Queue(IO_QUEUE_PLAN, DEFAULT_EXCHANGE, routing_key="task.io.plan"),
        Queue("dead_letter", DLX_EXCHANGE, routing_key="dlx.failed"),
    ),

    # Redis Broker 连接优化
    broker_transport_options={
        "visibility_timeout": 7200,     # 2小时可见性超时（长任务防丢失）
        "max_connections": 20,          # 连接池上限
        "fanout_prefix": True,          # 广播前缀优化
        "fanout_patterns": True,        # 广播模式优化
    },
    broker_connection_retry_on_startup=True,  # 启动时自动重连Broker

    # 事件监控（celery-exporter / Prometheus 需要）
    task_send_sent_event=True,          # 发送任务发送事件
    worker_send_task_events=True,       # Worker 发送任务事件

    # 任务失败回调（重试耗尽后触发）
    task_on_failure=lambda sender, task_id, args, kwargs, retval, exc, traceback, **kw:
        __import__('fastapi_app.core.task_callbacks', fromlist=['on_task_failure'])
        .on_task_failure(task_id, sender.name, args, kwargs, exc, traceback),

    # 自动发现任务模块
    imports=[
        "fastapi_app.tasks.batch_tasks",
        "fastapi_app.tasks.report_tasks",
        "fastapi_app.tasks.plan_tasks",
        "fastapi_app.tasks.backup_tasks",
        "fastapi_app.tasks.maintenance_tasks",
    ],

    # 定时任务（Celery Beat）
    beat_schedule={
        "sync-shipment-daily": {
            "task": "sync_shipment_records_task",
            "schedule": crontab(hour=1, minute=0),
        },
        "backup-integrity-check": {
            "task": "backup_integrity_check_task",
            "schedule": crontab(hour=3, minute=0),
        },
        "auto-daily-full-backup": {
            "task": "auto_daily_backup_task",
            "schedule": crontab(hour=2, minute=0),
        },
        "auto-incremental-backup": {
            "task": "auto_incremental_backup_task",
            "schedule": crontab(hour='6,10,14,18,22', minute=0),
        },
        "backup-cleanup": {
            "task": "backup_cleanup_task",
            "schedule": crontab(hour=4, minute=0),
        },
        "refresh-dashboard-mv": {
            "task": "refresh_dashboard_mv_task",
            "schedule": 300.0,  # 每 5 分钟刷新一次仪表盘物化视图
        },
    },
)
