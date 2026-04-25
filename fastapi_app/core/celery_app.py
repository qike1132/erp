"""
Celery 应用配置
使用 Redis 作为 Broker 和 Result Backend
优化: Worker 并发、任务路由、事件监控、Redis 连接池
"""
from celery import Celery
from celery.schedules import crontab
from fastapi_app.core.config import settings

celery_app = Celery(
    "erp_system",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    # 序列化（已强制 JSON，禁用 pickle RCE 风险）
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,

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

    # 任务路由（按业务类型分队列）
    task_routes={
        "fastapi_app.tasks.batch_tasks.*": {"queue": "batch"},
        "fastapi_app.tasks.report_tasks.*": {"queue": "reports"},
        "fastapi_app.tasks.plan_tasks.*": {"queue": "batch"},
    },

    # 队列定义（显式声明所有队列，确保队列存在）
    task_queues={
        "celery": {
            "exchange": "tasks",
            "routing_key": "task.default",
        },
        "batch": {
            "exchange": "tasks",
            "routing_key": "task.batch",
        },
        "reports": {
            "exchange": "tasks",
            "routing_key": "task.reports",
        },
    },

    # Redis Broker 连接优化
    broker_transport_options={
        "visibility_timeout": 7200,     # 2小时可见性超时（长任务防丢失）
        "max_connections": 20,          # 连接池上限
        "fanout_prefix": True,          # 广播前缀优化
        "fanout_patterns": True,        # 广播模式优化
    },
    broker_connection_retry_on_startup=True,  # 启动时自动重连Broker

    # 事件监控（Flower + Prometheus 需要）
    task_send_sent_event=True,          # 发送任务发送事件
    worker_send_task_events=True,       # Worker 发送任务事件

    # 自动发现任务模块
    imports=[
        "fastapi_app.tasks.batch_tasks",
        "fastapi_app.tasks.report_tasks",
        "fastapi_app.tasks.plan_tasks",
    ],

    # 定时任务（Celery Beat）
    beat_schedule={
        "sync-shipment-daily": {
            "task": "sync_shipment_records_task",
            "schedule": crontab(hour=1, minute=0),  # 每天凌晨1点
        },
    },
)
