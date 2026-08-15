"""Celery → ARQ 迁移兼容层。

本模块原为 Celery 应用配置，已迁移至 ARQ（原生 async 任务队列）：
- Worker 配置：``fastapi_app.core.arq_app.WorkerSettings``
- Redis 配置：``fastapi_app.core.arq_app.redis_settings``
- 定时任务：``fastapi_app.core.arq_app.cron_jobs`` / ``cron_schedules``
- Web 入队：``await fastapi_app.core.arq_app.get_arq_pool().enqueue_job(...)``

保留此模块仅为兼容：仍懒加载 ``celery_app`` 的旧代码（如 tasks 端点的状态/下载
回退路径）会得到 ``None``，从而触发 503 优雅降级，提示调用方改用 ARQ API。
"""
# Celery 已移除（见 requirements/base.txt），celery_app 置为 None 以触发调用方降级。
celery_app = None  # noqa: F841
