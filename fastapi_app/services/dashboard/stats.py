"""仪表盘核心统计(今日/昨日/生产/待办聚合)

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import asyncio
import contextlib
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import (
    DatabaseError,
    DataError,
    DisconnectionError,
    OperationalError,
    ProgrammingError,
    StatementError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.shared_models import (
    ApprovalRequest,
    MaterialRegistration,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    StockIn,
    StockOut,
)

logger = logging.getLogger(__name__)


async def _get_mv_daily_quantity(db: AsyncSession, mv_name: str, stat_date: date) -> int | None:
    """从物化视图读取某日聚合数量，不存在或无数据时返回 None（自动降级到基表）。"""
    try:
        # 先检查表是否存在，避免直接查询不存在的物化视图导致事务失败
        exists_result = await db.execute(
            text("SELECT to_regclass(:name)"), {"name": mv_name}
        )
        if exists_result.scalar() is None:
            return None

        result = await db.execute(
            text(f"SELECT total_quantity FROM {mv_name} WHERE stat_date = :stat_date"),  # nosec B608
            {"stat_date": stat_date},
        )
        row = result.scalar_one_or_none()
        return int(row) if row is not None else None
    except ProgrammingError:
        # 物化视图尚未创建时自动降级；回滚失败事务以保证同一 session 后续查询可用
        with contextlib.suppress(OperationalError, StatementError):
            await db.rollback()  # manual-tx: try/except 内显式事务控制
        return None
    except (OperationalError, DataError, DatabaseError):
        logger.warning(f"读取物化视图 {mv_name} 失败，降级到基表查询", exc_info=True)
        with contextlib.suppress(OperationalError, StatementError):
            await db.rollback()  # manual-tx: try/except 内显式事务控制
        return None

async def _query_today_yesterday_base(db: AsyncSession, today_start: datetime, today_end: datetime, yesterday_start: datetime) -> tuple:
    # ---- 2. 合并 today+yesterday 基表查询为 SUM FILTER（每表 1 条 SQL）----
    # Order：多 SKU 模型，按 OrderItem 聚合
    order_row = (await db.execute(
        select(
            func.coalesce(func.sum(OrderItem.quantity).filter(
                Order.order_date >= today_start, Order.order_date < today_end
            ), 0).label('today'),
            func.coalesce(func.sum(OrderItem.quantity).filter(
                Order.order_date >= yesterday_start, Order.order_date < today_start
            ), 0).label('yesterday'),
        )
        .select_from(Order)
        .outerjoin(OrderItem, OrderItem.order_id == Order.id)
        .where(Order.is_deleted.isnot(True))
        .where(Order.order_date >= yesterday_start, Order.order_date < today_end)
    )).one()
    order_today = int(order_row.today)
    order_yesterday_base = int(order_row.yesterday)

    # StockIn
    stockin_row = (await db.execute(
        select(
            func.coalesce(func.sum(StockIn.quantity).filter(
                StockIn.stockin_date >= today_start, StockIn.stockin_date < today_end
            ), 0).label('today'),
            func.coalesce(func.sum(StockIn.quantity).filter(
                StockIn.stockin_date >= yesterday_start, StockIn.stockin_date < today_start
            ), 0).label('yesterday'),
        ).where(StockIn.stockin_date >= yesterday_start, StockIn.stockin_date < today_end)
    )).one()
    stockin_today = int(stockin_row.today)
    stockin_yesterday_base = int(stockin_row.yesterday)

    # StockOut
    stockout_row = (await db.execute(
        select(
            func.coalesce(func.sum(StockOut.quantity).filter(
                StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
            ), 0).label('today'),
            func.coalesce(func.sum(StockOut.quantity).filter(
                StockOut.stockout_date >= yesterday_start, StockOut.stockout_date < today_start
            ), 0).label('yesterday'),
        ).where(StockOut.stockout_date >= yesterday_start, StockOut.stockout_date < today_end)
    )).one()
    stockout_today = int(stockout_row.today)
    stockout_yesterday_base = int(stockout_row.yesterday)

    return order_today, order_yesterday_base, stockin_today, stockin_yesterday_base, stockout_today, stockout_yesterday_base

async def _query_today_yesterday_base_with_mv(
    db: AsyncSession, today_start: datetime, today_end: datetime,
    yesterday_start: datetime, yesterday_date: date,
) -> tuple:
    """主链路：MV 存在性检查 + today/yesterday 基表查询（单 session 顺序执行）。

    合并为一个协程以便与 _fetch_independent_stats 并行 asyncio.gather。
    内部存在数据依赖（MV resolve 依赖 MV 存在性 + 基表值），故不可进一步并行。
    返回 (order_today, order_yesterday_base, stockin_today, stockin_yesterday_base,
           stockout_today, stockout_yesterday_base, (mv_order_ok, mv_stockin_ok, mv_stockout_ok))
    """
    # MV 存在性检查（3→1）
    mv_exists = await db.execute(text(
        "SELECT to_regclass('mv_daily_order_quantity') AS mv_order, "
        "to_regclass('mv_daily_stockin_quantity') AS mv_stockin, "
        "to_regclass('mv_daily_stockout_quantity') AS mv_stockout"
    ))
    mv_row = mv_exists.one()
    mv_flags = (
        mv_row.mv_order is not None,
        mv_row.mv_stockin is not None,
        mv_row.mv_stockout is not None,
    )

    # today/yesterday 基表查询
    base = await _query_today_yesterday_base(db, today_start, today_end, yesterday_start)

    return (*base, mv_flags)

async def _resolve_yesterday_from_mv(db: AsyncSession, mv_order_ok: bool, mv_stockin_ok: bool, mv_stockout_ok: bool, yesterday_date: date, order_yesterday_base: int, stockin_yesterday_base: int, stockout_yesterday_base: int) -> tuple:
    # ---- 3. MV 数据覆盖 yesterday 基表值（MV 优先）----
    # 所有 MV 都存在时用 UNION ALL 一次查 3 个（3→1），否则逐个查
    if mv_order_ok and mv_stockin_ok and mv_stockout_ok:
        mv_data = await db.execute(text(
            "SELECT 'order' AS type, total_quantity FROM mv_daily_order_quantity WHERE stat_date = :d "
            "UNION ALL "
            "SELECT 'stockin' AS type, total_quantity FROM mv_daily_stockin_quantity WHERE stat_date = :d "
            "UNION ALL "
            "SELECT 'stockout' AS type, total_quantity FROM mv_daily_stockout_quantity WHERE stat_date = :d"
        ), {"d": yesterday_date})
        mv_map = {r.type: int(r.total_quantity) for r in mv_data if r.total_quantity is not None}
        order_yesterday = mv_map.get('order', order_yesterday_base)
        stockin_yesterday = mv_map.get('stockin', stockin_yesterday_base)
        stockout_yesterday = mv_map.get('stockout', stockout_yesterday_base)
    else:
        order_yesterday = await _mv_or_base(db, 'mv_daily_order_quantity', mv_order_ok, yesterday_date, order_yesterday_base)
        stockin_yesterday = await _mv_or_base(db, 'mv_daily_stockin_quantity', mv_stockin_ok, yesterday_date, stockin_yesterday_base)
        stockout_yesterday = await _mv_or_base(db, 'mv_daily_stockout_quantity', mv_stockout_ok, yesterday_date, stockout_yesterday_base)
    return order_yesterday, stockin_yesterday, stockout_yesterday

async def _query_production_stats(db: AsyncSession, today_start: datetime) -> dict:
    """查询生产排产统计，返回可合并入 DashboardStats 的字段 dict。

    重构自原 mutate-data 版本：返回值而非副作用，便于 asyncio.gather 并行调用
    （独立 session 中执行，不共享调用方 data dict）。
    """
    try:
        from fastapi_app.shared_models.production_plan import ProductionPlan
        prod_stats = (await db.execute(
            select(
                func.count(ProductionPlan.id).filter(ProductionPlan.plan_date >= today_start),
                func.count(ProductionPlan.id).filter(and_(ProductionPlan.plan_date >= today_start, ProductionPlan.status == "completed")),
            )
        )).one()
        total_plans = prod_stats[0] or 0
        completed_plans = prod_stats[1] or 0
        return {
            "production_completion_rate": round(completed_plans / total_plans, 2) if total_plans > 0 else 0.0,
            "pending_shipments": total_plans - completed_plans,
        }
    except Exception:  # defensive: 仪表盘某个统计项失败时不影响整体返回
        logger.warning("生产排产统计查询失败", exc_info=True)
        return {"production_completion_rate": 0.0, "pending_shipments": 0}

async def _fetch_independent_stats(today_start: datetime) -> dict:
    """独立查询组：4 个 count 标量子查询 + 生产排产统计。

    使用独立 session（get_async_db_context），可与主链路（MV 存在性 →
    today/yesterday → MV resolve）并行 asyncio.gather 执行。

    独立性：counts 查询的 4 张表（approval_request/product/purchase_order/
    material_registration）与 production_plan 均与主链路的 order/stock_in/
    stock_out 表无关联，无数据依赖。
    """
    from fastapi_app.core.database import get_async_db_context

    async with get_async_db_context() as db2:
        # 4 个 count 合并为 1 个 scalar_subquery（4→1，PostgreSQL 并行执行子查询）
        counts_row = (await db2.execute(
            select(
                select(func.count(ApprovalRequest.id))
                .where(ApprovalRequest.status == "pending")
                .scalar_subquery().label('pending_approvals'),
                select(func.count(Product.id))
                .where(Product.current_stock <= 10)
                .scalar_subquery().label('low_stock_count'),
                select(func.count(PurchaseOrder.id))
                .where(PurchaseOrder.status.in_(["pending", "partial"]))
                .scalar_subquery().label('pending_purchases'),
                select(func.count(MaterialRegistration.id))
                .where(MaterialRegistration.status.in_(["pending", "partial"]))
                .scalar_subquery().label('pending_materials'),
            )
        )).one()

        prod_stats = await _query_production_stats(db2, today_start)

        return {
            "pending_approvals": int(counts_row.pending_approvals or 0),
            "low_stock_count": int(counts_row.low_stock_count or 0),
            "pending_purchases": int(counts_row.pending_purchases or 0),
            "pending_materials": int(counts_row.pending_materials or 0),
            **prod_stats,
        }

@cache_result(key_prefix="dashboard:stats", ttl=30, local_ttl=30,
              key_builder=lambda *args, **kwargs: "global")
async def fetch_dashboard_stats(db: AsyncSession) -> dict:
    """查询仪表盘核心统计数据，返回可构造 DashboardStats 的字典。

    优化：合并 MV 存在性检查（3→1）、合并 today+yesterday 为 SUM FILTER（每表 1 条
    替代 2 条）、合并 MV 数据查询（3→1 UNION ALL）、合并 4 个独立 count 查询为
    1 个 scalar_subquery（4→1）、独立查询组与主链路 asyncio.gather 并行。
    总往返从 14~17 次降至 6~7 次，关键路径从 6~7 次降至 4~5 次（独立组并行）。

    TTL：30s（原 10s）。今日备货/出货等模块数据变更频率远低于 30s 窗口，
    延长 TTL 将冷启动频率降低 3x（4 worker × 6/min → 4 worker × 2/min），
    同时保持用户感知"近实时"。
    """
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        today_start = datetime(now.year, now.month, now.day, 0, 0, 0)
        tomorrow = now + timedelta(days=1)
        today_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
        yesterday_start = today_start - timedelta(days=1)
        yesterday_date = yesterday_start.date()

        # 并行执行：
        # - 主链路（传入 db）：MV 存在性 → today/yesterday 基表 → MV resolve
        # - 独立组（新 session）：4 count scalar_subquery + 生产排产
        # 主链路内部有依赖（MV resolve 依赖 MV 存在性 + 基表值），无法进一步并行；
        # 独立组与主链路无表关联，安全并行。
        # asyncio.gather 返回 2 个结果（每个协程 1 个），需二次解包：
        #   base_result = (order_today, order_yesterday_base, stockin_today,
        #                  stockin_yesterday_base, stockout_today,
        #                  stockout_yesterday_base, mv_flags)
        #   independent = {pending_approvals, low_stock_count, ...}
        base_result, independent = await asyncio.gather(
            _query_today_yesterday_base_with_mv(db, today_start, today_end, yesterday_start, yesterday_date),
            _fetch_independent_stats(today_start),
        )
        (order_today, order_yesterday_base, stockin_today, stockin_yesterday_base,
         stockout_today, stockout_yesterday_base, mv_flags) = base_result

        mv_order_ok, mv_stockin_ok, mv_stockout_ok = mv_flags
        order_yesterday, stockin_yesterday, stockout_yesterday = await _resolve_yesterday_from_mv(
            db, mv_order_ok, mv_stockin_ok, mv_stockout_ok,
            yesterday_date, order_yesterday_base, stockin_yesterday_base, stockout_yesterday_base,
        )

        data = {
            "order_today": order_today,
            "stockin_today": stockin_today,
            "stockout_today": stockout_today,
            "pending_approvals": independent["pending_approvals"],
            "order_yesterday": order_yesterday,
            "stockin_yesterday": stockin_yesterday,
            "stockout_yesterday": stockout_yesterday,
            "low_stock_count": independent["low_stock_count"],
            "pending_purchases": independent["pending_purchases"],
            "pending_materials": independent["pending_materials"],
            "production_completion_rate": independent["production_completion_rate"],
            "pending_shipments": independent["pending_shipments"],
        }

        data["total_orders_today"] = data["order_today"]
        data["total_shipments_today"] = data["stockout_today"]
        return data
    except (OperationalError, DisconnectionError):
        # 不缓存降级值：re-raise 让装饰器跳过缓存写入，endpoint 层负责降级
        logger.warning("仪表盘异步统计加载失败", exc_info=True)
        raise

async def _mv_or_base(db: AsyncSession, mv_name: str, mv_exists: bool,
                      stat_date: date, fallback: int) -> int:
    """MV 存在且有数据时返回 MV 值，否则返回 fallback。"""
    if not mv_exists:
        return fallback
    try:
        result = await db.execute(
            text(f"SELECT total_quantity FROM {mv_name} WHERE stat_date = :d"),  # nosec B608
            {"d": stat_date},
        )
        row = result.scalar_one_or_none()
        return int(row) if row is not None else fallback
    except (OperationalError, DataError, DatabaseError):
        logger.warning(f"读取物化视图 {mv_name} 失败，降级到基表值", exc_info=True)
        with contextlib.suppress(OperationalError, StatementError):
            await db.rollback()  # manual-tx: try/except 内显式事务控制
        return fallback