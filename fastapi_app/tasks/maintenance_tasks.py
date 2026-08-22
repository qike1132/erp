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

    独立 session 中执行，各 MV 之间无表关联，可安全并行 asyncio.gather。
    CONCURRENTLY 要求 MV 有唯一索引（已在对应 migration 中创建）。
    视图不存在时（迁移未执行）记录警告并跳过，不影响其他视图。
    """
    exists = (await db.execute(
        text("SELECT to_regclass(:name)"), {"name": mv_name}
    )).scalar()
    if exists is None:
        logger.warning("物化视图 %s 不存在，跳过刷新（请确认迁移 pg_standalone_017 已执行）", mv_name)
        return
    await db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv_name}"))  # nosec B608: 常量字符串
    await db.commit()


# 全部物化视图（含日统计 + 产品聚合）
_DASHBOARD_MV_NAMES = [
    "mv_daily_order_quantity",
    "mv_daily_stockin_quantity",
    "mv_daily_stockout_quantity",
]
_PRODUCT_MV_NAMES = [
    "mv_product_aggregate",
]


async def _refresh_materialized_views(mv_names: list[str], label: str) -> None:
    """并行刷新一组物化视图（CONCURRENTLY 不阻塞读）。

    mv_names 内各 MV 基于不同基表或不同聚合维度，CONCURRENTLY 刷新互不
    冲突（产品聚合 MV 与日统计 MV 无共享写锁），可安全并行。
    每个 MV 使用独立 session（get_async_db_context），通过 asyncio.gather 并行。
    """
    async def _refresh_one(mv_name: str) -> None:
        async with get_async_db_context() as db:
            await _refresh_single_mv(db, mv_name)

    await asyncio.gather(*(_refresh_one(name) for name in mv_names))
    logger.info("%s物化视图刷新完成（%d 个并行）", label, len(mv_names))


async def refresh_dashboard_mv_task(ctx) -> dict:
    """ARQ 任务入口：刷新全部物化视图（日统计 + 产品聚合）。"""
    try:
        await _refresh_materialized_views(_DASHBOARD_MV_NAMES, "仪表盘")
        await _refresh_materialized_views(_PRODUCT_MV_NAMES, "产品聚合")
        return {"success": True, "message": "物化视图刷新完成"}
    except Exception as exc:  # broad-except: 定时任务容错，异常不传播以避免调度器崩溃
        logger.exception("refresh_dashboard_mv_task 失败")
        raise exc
