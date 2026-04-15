"""
Celery 应用配置
使用 Redis 作为 Broker 和 Result Backend
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
    # 序列化
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

    # 并发
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,

    # 任务路由
    task_routes={
        "fastapi_app.tasks.batch_tasks.*": {"queue": "batch"},
        "fastapi_app.tasks.report_tasks.*": {"queue": "reports"},
        "fastapi_app.tasks.plan_tasks.*": {"queue": "batch"},
    },

    # 自动发现任务模块
    task_modules=[
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
