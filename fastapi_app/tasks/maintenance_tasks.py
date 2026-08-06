"""系统维护任务

职责：
- 刷新仪表盘物化视图
- 其他低频率维护型任务
"""
import logging

from celery import shared_task
from sqlalchemy import text

from fastapi_app.core.database import get_async_db_context

logger = logging.getLogger(__name__)


async def _refresh_dashboard_materialized_views() -> None:
    """刷新仪表盘每日统计物化视图（CONCURRENTLY 不阻塞读）。"""
    async with get_async_db_context() as db:
        try:
            await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_order_quantity"))
            await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_stockin_quantity"))
            await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_stockout_quantity"))
            logger.info("仪表盘物化视图刷新完成")
        except Exception:
            logger.exception("仪表盘物化视图刷新失败")
            raise


@shared_task(name="refresh_dashboard_mv_task", bind=True, max_retries=3, default_retry_delay=60)
def refresh_dashboard_mv_task(self) -> dict:
    """Celery 任务入口：刷新仪表盘物化视图。"""
    import asyncio
    try:
        asyncio.run(_refresh_dashboard_materialized_views())
        return {"success": True, "message": "仪表盘物化视图刷新完成"}
    except Exception as exc:
        logger.exception("refresh_dashboard_mv_task 失败")
        raise self.retry(exc=exc)
