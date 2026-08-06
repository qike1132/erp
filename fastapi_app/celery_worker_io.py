"""
Celery I/O 密集型 Worker 入口

gevent pool 需要在进程启动时 monkey-patch 标准库，
才能让 asyncpg / asyncio / socket 等 I/O 操作与 greenlet 协作切换。
本模块仅由 gevent worker 导入，Web 应用不引用，避免影响主进程。
"""
from gevent import monkey

monkey.patch_all()

from fastapi_app.core.celery_app import celery_app  # noqa: E402

__all__ = ["celery_app"]
