"""按授权范围聚合仪表盘核心统计。"""
import asyncio
import contextlib
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import and_, func, select, text
from sqlalchemy.exc import (
    DatabaseError,
    DataError,
    DisconnectionError,
    OperationalError,
    StatementError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.business_time import business_day_range, business_today
from fastapi_app.core.cache import cache_result
from fastapi_app.core.float_utils import round_qty
from fastapi_app.services.dashboard.scope import DashboardReadScope, dashboard_cache_key
from fastapi_app.shared_models import (
    MaterialRegistration,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    StockIn,
    StockOut,
)

logger = logging.getLogger(__name__)


async def _query_today_yesterday_base(
    db: AsyncSession, today_start: datetime, today_end: datetime, yesterday_start: datetime,
    scope: DashboardReadScope,
) -> tuple:
    """今日/昨日基表聚合，只执行获准来源的查询。"""
    # ---- 2. 合并 today+yesterday 基表查询为 SUM FILTER（每表 1 条 SQL）----
    # Order：多 SKU 模型，按 OrderItem 聚合
    order_stmt = (
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
    )
    stockin_stmt = select(
        func.coalesce(func.sum(StockIn.quantity).filter(
            StockIn.stockin_date >= today_start, StockIn.stockin_date < today_end
        ), 0).label('today'),
        func.coalesce(func.sum(StockIn.quantity).filter(
            StockIn.stockin_date >= yesterday_start, StockIn.stockin_date < today_start
        ), 0).label('yesterday'),
    ).where(StockIn.stockin_date >= yesterday_start, StockIn.stockin_date < today_end)
    stockout_stmt = select(
        func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity).filter(
            StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
        ), 0).label('today'),
        func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity).filter(
            StockOut.stockout_date >= yesterday_start, StockOut.stockout_date < today_start
        ), 0).label('yesterday'),
    ).where(StockOut.stockout_date >= yesterday_start, StockOut.stockout_date < today_end)

    if scope.factory:
        # 订单标题可按单据归属显示；件数与移动端一致，只累计当前工厂的 SKU。
        order_stmt = order_stmt.join(Product, Product.id == OrderItem.product_id).where(Product.factory == scope.factory)
        stockin_stmt = stockin_stmt.where(StockIn.product.has(Product.factory == scope.factory))
        stockout_stmt = stockout_stmt.where(StockOut.product.has(Product.factory == scope.factory))

    order = (await db.execute(order_stmt)).one() if scope.orders else None
    stockin = (await db.execute(stockin_stmt)).one() if scope.stockin else None
    stockout = (await db.execute(stockout_stmt)).one() if scope.stockout else None
    return (
        int(order.today) if order else 0, int(order.yesterday) if order else 0,
        int(stockin.today) if stockin else 0, int(stockin.yesterday) if stockin else 0,
        int(stockout.today) if stockout else 0, int(stockout.yesterday) if stockout else 0,
    )

async def _query_today_yesterday_base_with_mv(
    db: AsyncSession, today_start: datetime, today_end: datetime,
    yesterday_start: datetime, scope: DashboardReadScope,
) -> tuple:
    """只为可读三项且不受工厂限制的范围探测全厂物化视图。"""
    if scope.factory or not (scope.orders and scope.stockin and scope.stockout):
        base = await _query_today_yesterday_base(db, today_start, today_end, yesterday_start, scope)
        return (*base, (False, False, False))

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
    base = await _query_today_yesterday_base(db, today_start, today_end, yesterday_start, scope)

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
            "production_completion_rate": round_qty(completed_plans / total_plans, precision_digits=2) if total_plans > 0 else 0.0,
            "pending_shipments": total_plans - completed_plans,
        }
    except (OperationalError, DisconnectionError):
        raise  # M-16 族：连接类异常交全局 503，不得吞成 0 值统计
    except Exception:  # defensive: 仪表盘某个统计项失败时不影响整体返回
        logger.warning("生产排产统计查询失败", exc_info=True)
        return {"production_completion_rate": 0.0, "pending_shipments": 0}

async def _fetch_independent_stats(today_start: datetime, scope: DashboardReadScope) -> dict:
    """独立会话合并获准的计数；无可靠工厂关联的旧表不向绑定工厂用户查询。"""
    from fastapi_app.core.database import get_async_db_context

    counts = {}
    if scope.inventory:
        low_stock_stmt = select(func.count(Product.id)).where(Product.current_stock <= 10)
        if scope.factory:
            low_stock_stmt = low_stock_stmt.where(Product.factory == scope.factory)
        counts['low_stock_count'] = low_stock_stmt
    if scope.purchases and not scope.factory:
        counts['pending_purchases'] = select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status.in_(['pending', 'partial']))
    if scope.materials and not scope.factory:
        counts['pending_materials'] = select(func.count(MaterialRegistration.id)).where(MaterialRegistration.status.in_(['pending', 'partial']))
    can_query_legacy_plans = scope.plans and not scope.factory
    data: dict = {
        'low_stock_count': 0, 'pending_purchases': 0, 'pending_materials': 0,
        'production_completion_rate': 0.0, 'pending_shipments': 0,
    }
    if not counts and not can_query_legacy_plans:
        return data
    async with get_async_db_context() as db2:
        if counts:
            stmt = select(*(query.scalar_subquery().label(name) for name, query in counts.items()))
            counts_row = (await db2.execute(stmt)).one()
            data.update((name, int(getattr(counts_row, name) or 0)) for name in counts)
        if can_query_legacy_plans:
            data.update(await _query_production_stats(db2, today_start))
    return data

@cache_result(key_prefix="dashboard:stats", ttl=30, local_ttl=30, key_builder=dashboard_cache_key)
async def fetch_dashboard_stats(db: AsyncSession, scope: DashboardReadScope) -> dict:
    """查询授权范围内的核心统计；不可见的指标保留默认值。"""
    try:
        # 2026-10-17 审计 AUD-23：统一业务时区（Asia/Shanghai）日界。
        # 此前用 UTC 日界当「今日」，与移动端本地日界不一致（UTC+8 下每天
        # 00:00–08:00 两端数字分叉）；与 timestamptz 列比较用 aware 时间。
        today = business_today()
        today_start, today_end = business_day_range(today)
        yesterday_date = today - timedelta(days=1)
        yesterday_start, _ = business_day_range(yesterday_date)

        # 并行执行：
        # - 主链路（传入 db）：MV 存在性 → today/yesterday 基表 → MV resolve
        # - 独立组（新 session）：3 count scalar_subquery + 生产排产
        # 主链路内部有依赖（MV resolve 依赖 MV 存在性 + 基表值），无法进一步并行；
        # 独立组与主链路无表关联，安全并行。
        # asyncio.gather 返回 2 个结果（每个协程 1 个），需二次解包：
        #   base_result = (order_today, order_yesterday_base, stockin_today,
        #                  stockin_yesterday_base, stockout_today,
        #                  stockout_yesterday_base, mv_flags)
        #   independent = {low_stock_count, pending_purchases, ...}
        base_result, independent = await asyncio.gather(
            _query_today_yesterday_base_with_mv(
                db, today_start, today_end, yesterday_start, scope,
            ),
            _fetch_independent_stats(today_start, scope),
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
