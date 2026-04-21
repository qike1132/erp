"""
Taskiq Broker 配置
整改: 替代 Celery，提供异步任务队列支持
"""
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker
import os

# Redis 连接配置
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# 创建 Broker
broker = ListQueueBroker(url=REDIS_URL)

# 创建 Scheduler（替代 Celery Beat）
scheduler = TaskiqScheduler(
    broker=broker,
    sources=[LabelScheduleSource(broker)],
)

# 任务注册示例
@broker.task
def example_task(name: str) -> str:
    """示例任务"""
    return f"Hello, {name}!"

# 定时任务示例（使用 label 定义）
@broker.task(schedule=[{"cron": "0 0 * * *"}])  # 每天凌晨执行
def daily_cleanup() -> None:
    """每日清理任务"""
    pass
