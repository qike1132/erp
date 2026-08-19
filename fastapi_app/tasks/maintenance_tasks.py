"""系统维护任务

职责：
- 刷新仪表盘物化视图
- 其他低频率维护型任务
"""
import asyncio
import logging

from sqlalchemy import text

from fastapi_app.core.database import get_async_db_context

logger = logging.getLogger(__name__)


async def _refresh_single_mv(db, mv_name: str) -> None:
    """刷新单个物化视图（CONCURRENTLY 不阻塞读）。

    独立 session 中执行，3 个 MV 之间无表关联，可安全并行 asyncio.gather。
    CONCURRENTLY 要求 MV 有唯一索引（已在 migration pg_standalone_016 中创建）。
    """
    await db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}"))  # nosec B608: 常量字符串
    await db.commit()


async def _refresh_dashboard_materialized_views() -> None:
    """刷新仪表盘每日统计物化视图（3 个 MV 并行刷新，CONCURRENTLY 不阻塞读）。

    优化：原串行刷新 3 个 MV（单 session 顺序执行），改为 3 个独立 session 并行
    asyncio.gather。3 个 MV 基于不同基表（order/stock_in/stock_out），CONCURRENTLY
    刷新不互斥，可安全并行。刷新总耗时从 3×T 降至 max(T)。
    """
    mv_names = [
        "mv_daily_order_quantity",
        "mv_daily_stockin_quantity",
        "mv_daily_stockout_quantity",
    ]
    try:
        # 每个MV使用独立session，并行刷新
        async with (
            get_async_db_context() as db1,
            get_async_db_context() as db2,
            get_async_db_context() as db3,
        ):
            await asyncio.gather(
                _refresh_single_mv(db1, mv_names[0]),
                _refresh_single_mv(db2, mv_names[1]),
                _refresh_single_mv(db3, mv_names[2]),
            )
        logger.info("仪表盘物化视图刷新完成（3 个并行）")
    except Exception:  # broad-except: 定时任务容错，异常不传播以避免调度器崩溃
        logger.exception("仪表盘物化视图刷新失败")
        raise


async def refresh_dashboard_mv_task(ctx) -> dict:
    """ARQ 任务入口：刷新仪表盘物化视图。"""
    try:
        await _refresh_dashboard_materialized_views()
        return {"success": True, "message": "仪表盘物化视图刷新完成"}
    except Exception as exc:  # broad-except: 定时任务容错，异常不传播以避免调度器崩溃
        logger.exception("refresh_dashboard_mv_task 失败")
        raise exc
