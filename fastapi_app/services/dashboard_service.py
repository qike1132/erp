"""仪表盘统计服务

P2-15: 将仪表盘核心统计逻辑下沉到服务层，供 v1/v2 复用，保持 API 版本间行为一致。
"""
import asyncio
import contextlib
import json
import logging
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import and_, extract, func, select, text
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
    Case,
    CaseStockIn,
    CaseStockOut,
    DailyProductionRecord,
    MaterialRegistration,
    Order,
    OrderItem,
    Product,
    PurchaseOrder,
    PurchasePlan,
    PurchasePlanDetail,
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



class DashboardStats(BaseModel):
    order_today: int = 0          # 今日订单商品总件数
    order_yesterday: int = 0      # 昨日订单商品总件数
    stockin_today: int = 0        # 今日备货商品总件数
    stockin_yesterday: int = 0    # 昨日备货商品总件数
    stockout_today: int = 0       # 今日出货商品总件数
    stockout_yesterday: int = 0   # 昨日出货商品总件数
    pending_approvals: int = 0
    low_stock_count: int = 0
    pending_purchases: int = 0
    pending_materials: int = 0
    production_completion_rate: float = 0.0
    pending_shipments: int = 0
    total_shipments_today: int = 0
    total_orders_today: int = 0


class DashboardResponse(BaseModel):
    success: bool = True
    data: DashboardStats | None = None


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


class Activity(BaseModel):
    type: str
    time: str
    status: str
    title: str
    desc: str


_CACHE_KEY_ACTIVITIES = "dashboard:activities"


async def _get_cached_activities():
    from fastapi_app.core.redis_wrapper import safe_get
    cached = await safe_get(_CACHE_KEY_ACTIVITIES, context="仪表盘活动缓存")
    if cached:
        if isinstance(cached, str):
            return json.loads(cached)
        return cached
    return None


async def _set_cached_activities(data):
    from fastapi_app.core.redis_wrapper import safe_set
    await safe_set(_CACHE_KEY_ACTIVITIES, json.dumps(data, default=str), timeout=60, context="仪表盘活动缓存")


async def fetch_dashboard_activities(db: AsyncSession) -> list[Activity]:
    """查询仪表盘最近活动数据，优先命中 Redis 缓存。"""
    cached_activities = await _get_cached_activities()
    if cached_activities is not None:
        return [Activity(**a) for a in cached_activities]
    try:
        activities = []

        result = await db.execute(select(Order).order_by(Order.order_date.desc()).limit(4))
        for o in result.scalars().all():
            activities.append({"type": "order", "time": str(o.order_date) if o.order_date else "",
                               "status": o.status or "", "title": f"订单 {o.order_no}", "desc": f"订单 {o.order_no}"})

        result = await db.execute(select(StockIn).order_by(StockIn.stockin_date.desc()).limit(3))
        for s in result.scalars().all():
            activities.append({"type": "stockin", "time": str(s.stockin_date) if s.stockin_date else "",
                               "status": "已备货", "title": f"入库 {s.stockin_no}", "desc": f"入库 {s.stockin_no}"})

        result = await db.execute(select(StockOut).order_by(StockOut.stockout_date.desc()).limit(3))
        for s in result.scalars().all():
            activities.append({"type": "stockout", "time": str(s.stockout_date) if s.stockout_date else "",
                               "status": "已出货", "title": f"出库 {s.stockout_no}", "desc": f"出库 {s.stockout_no}"})

        result = await db.execute(select(ApprovalRequest).order_by(ApprovalRequest.request_time.desc()).limit(3))
        for a in result.scalars().all():
            activities.append({"type": "approval", "time": str(a.request_time) if a.request_time else "",
                               "status": a.status or "待审批", "title": "审批请求", "desc": "审批请求"})

        activities.sort(key=lambda x: x["time"], reverse=True)
        activities = activities[:8]
        await _set_cached_activities(activities)
        return [Activity(**a) for a in activities]
    except (OperationalError, DisconnectionError) as e:
        logger.warning("仪表盘异步活动加载失败: %s [%s]", e, type(e).__name__)
        return []


class TodoItem(BaseModel):
    id: int = 0
    type: str = ""
    description: str = ""
    urgency: str = "normal"
    created_at: str = ""
    related_module: str = ""
    related_business_id: int = 0


class TodoListResponse(BaseModel):
    success: bool = True
    data: list[TodoItem] = []


@cache_result(key_prefix="dashboard:todos", ttl=30, local_ttl=15,
              key_builder=lambda *args, **kwargs: "global")
async def fetch_dashboard_todos(db: AsyncSession) -> dict:
    """查询仪表盘待办事项列表。

    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    endpoint 的 response_model=TodoListResponse 会自动构造 Pydantic 模型。
    """
    from fastapi_app.shared_models.production_plan import ProductionPlan

    try:
        todos = []
        pending_orders = (await db.execute(
            select(Order).where(Order.status == "pending").order_by(Order.order_date.desc()).limit(5)
        )).scalars().all()
        for o in pending_orders:
            todos.append(TodoItem(
                id=o.id, type="order",
                description=f"订单 {o.order_no} 待处理",
                urgency="normal", created_at=str(o.order_date) if o.order_date else "",
                related_module="order_query", related_business_id=o.id
            ))
        try:
            pending_plans = (await db.execute(
                select(ProductionPlan).where(ProductionPlan.status.in_(["pending", "confirmed"])).order_by(ProductionPlan.plan_date.desc()).limit(5)
            )).scalars().all()
            for p in pending_plans:
                todos.append(TodoItem(
                    id=p.id, type="shipment",
                    description=f"出货计划 {p.customer_name} 待确认",
                    urgency="urgent" if p.status == "pending" else "normal",
                    created_at=str(p.plan_date) if p.plan_date else "",
                    related_module="shipment_plan", related_business_id=p.id
                ))
        except Exception as e:  # defensive: 单个待办来源失败时返回其他来源
            logger.warning("获取出货计划待办失败: %s", e)
        todos.sort(key=lambda x: 0 if x.urgency == "urgent" else 1)
        return TodoListResponse(success=True, data=todos[:10]).model_dump()
    except Exception as e:  # defensive: 待办整体失败时返回空列表
        logger.warning("仪表盘待办加载失败: %s", e, exc_info=True)
        return TodoListResponse(success=True, data=[]).model_dump()


class SystemStatus(BaseModel):
    is_running: bool = True
    last_sync_time: str = ""
    data_status: str = "up_to_date"


class SystemStatusResponse(BaseModel):
    success: bool = True
    data: SystemStatus | None = None


def fetch_system_status() -> SystemStatusResponse:
    """查询系统运行状态（当前为静态健康状态）。"""
    return SystemStatusResponse(
        success=True,
        data=SystemStatus(
            is_running=True,
            last_sync_time=str(datetime.now(UTC).date()),
            data_status="up_to_date",
        ),
    )


class NavItem(BaseModel):
    id: int
    name: str
    code: str
    icon: str | None = None
    url: str
    permission_codes: list[str] = []


class NavSection(BaseModel):
    name: str
    items: list[NavItem] = []


async def fetch_nav_sections():
    """查询导航菜单数据。"""
    from fastapi_app.core.nav_context import get_nav_sections_async
    return await get_nav_sections_async()


class CustomerOutDetail(BaseModel):
    customer_name: str = ""
    total_quantity: int = 0
    total_amount: float = 0.0


class CustomerOutDetailResponse(BaseModel):
    success: bool = True
    data: list[CustomerOutDetail] = []


def _parse_dashboard_date(date_str: str | None) -> date:
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return date.today()
    return date.today()


@cache_result(key_prefix="dashboard:customer_out", ttl=60, local_ttl=30,
              key_builder=lambda **kwargs: f"p:{kwargs.get('period', '')}:d:{kwargs.get('query_date', '') or ''}")  # sql-safe: escape_like/绑定参数/常量片段
async def fetch_customer_out_details(
    period: str, query_date: str | None, db: AsyncSession
) -> dict:
    """按客户汇总出库详情。

    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    """
    selected_date = _parse_dashboard_date(query_date)
    today = selected_date
    today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    tomorrow = today + timedelta(days=1)
    today_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
    month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)

    if period == "month":
        start_time = month_start
        end_time = datetime(selected_date.year, selected_date.month + 1, 1, 0, 0, 0) if selected_date.month < 12 else datetime(selected_date.year + 1, 1, 1, 0, 0, 0)
    else:
        start_time = today_start
        end_time = today_end

    try:
        result = await db.execute(
            select(
                StockOut.customer,
                func.coalesce(func.sum(StockOut.quantity), 0),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0)
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
            .where(StockOut.stockout_date >= start_time)
            .where(StockOut.stockout_date < end_time)
            .where(StockOut.customer.isnot(None))
            .where(StockOut.customer != "")
            .group_by(StockOut.customer)
        )

        details = []
        for row in result.all():
            details.append(CustomerOutDetail(
                customer_name=row[0] or "未知客户",
                total_quantity=int(row[1] or 0),
                total_amount=round(float(row[2] or 0), 2)
            ))
        return CustomerOutDetailResponse(success=True, data=details).model_dump()
    except (OperationalError, DataError, DatabaseError, ValueError, TypeError) as e:
        logger.warning("客户出库详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[]).model_dump()


@cache_result(key_prefix="dashboard:customer_order", ttl=60, local_ttl=30,
              key_builder=lambda **kwargs: f"p:{kwargs.get('period', '')}:d:{kwargs.get('date_param', '') or ''}")
async def fetch_customer_order_details(
    period: str, date_param: str | None, db: AsyncSession
) -> dict:
    """按客户汇总订单详情。

    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    """
    selected_date = _parse_dashboard_date(date_param)
    today = selected_date
    today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    tomorrow = today + timedelta(days=1)
    today_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)
    month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)

    if period == "month":
        start_time = month_start
        end_time = datetime(selected_date.year, selected_date.month + 1, 1, 0, 0, 0) if selected_date.month < 12 else datetime(selected_date.year + 1, 1, 1, 0, 0, 0)
    else:
        start_time = today_start
        end_time = today_end

    try:
        result = await db.execute(
            select(
                Order.customer,
                func.coalesce(func.sum(OrderItem.quantity), 0),
                func.coalesce(func.sum(OrderItem.quantity * Product.price), 0)
            )
            .join(OrderItem, OrderItem.order_id == Order.id, isouter=True)
            .join(Product, OrderItem.product_id == Product.id, isouter=True)
            .where(Order.order_date >= start_time)
            .where(Order.order_date < end_time)
            .where(Order.is_deleted.isnot(True))
            .where(Order.customer.isnot(None))
            .where(Order.customer != "")
            .group_by(Order.customer)
        )

        details = []
        for row in result.all():
            details.append(CustomerOutDetail(
                customer_name=row[0] or "未知客户",
                total_quantity=int(row[1] or 0),
                total_amount=round(float(row[2] or 0), 2)
            ))
        return CustomerOutDetailResponse(success=True, data=details).model_dump()
    except (OperationalError, DataError, DatabaseError, ValueError, TypeError) as e:
        logger.warning("客户订单详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[]).model_dump()


class MobileStockData(BaseModel):
    today_quantity: int = 0
    today_amount: float = 0.0
    month_quantity: int = 0
    month_amount: float = 0.0
    total_quantity: int = 0
    total_amount: float = 0.0


class MobileDeptData(BaseModel):
    name: str = ""
    daily_output: int = 0
    output_value: float = 0.0


class MobileProductionData(BaseModel):
    total_value: float = 0.0
    departments: list[MobileDeptData] = []


class MobileShippingData(BaseModel):
    daily_qty: int = 0
    total_amount: float = 0.0


class MobileOrderData(BaseModel):
    daily_qty: int = 0
    daily_amount: float = 0.0
    total_amount: float = 0.0
    total_qty: int = 0
    total_inventory: int = 0
    total_inventory_amount: float = 0.0


class MobileWarehouseData(BaseModel):
    in_qty: int = 0
    in_amount: float = 0.0
    out_qty: int = 0
    out_amount: float = 0.0


class MobileDashboardData(BaseModel):
    stock: MobileStockData
    production: MobileProductionData
    shipping: MobileShippingData
    orders: MobileOrderData
    warehouse: MobileWarehouseData
    production_plans: dict = {}


class MobileDashboardResponse(BaseModel):
    success: bool = True
    data: MobileDashboardData | None = None


@cache_result(key_prefix="dashboard:mobile", ttl=30, local_ttl=30,
              key_builder=lambda **kwargs: f"d{kwargs.get('query_date', '')}")  # sql-safe: escape_like/绑定参数/常量片段
async def fetch_mobile_dashboard(query_date: str | None, db: AsyncSession) -> dict:
    """移动端数据看板（一次聚合所有板块数据）

    优化：合并 StockOut 当日/当月/总出库为 SUM FILTER（3→1）、shipping 复用 stock 当日值（1→0）、
    合并 Order 当日+总金额为 SUM FILTER（3→1）、合并库存数量+金额（2→1）、
    合并 CaseStockIn/Out 数量+金额（4→2）。总往返从 15~16 次降至 8~9 次。

    注：SQLAlchemy AsyncSession 不支持 asyncio.gather 并发（单连接非线程安全），
    使用 SQL 层 SUM FILTER 合并优于多 session 并发，避免连接池压力。

    返回 dict（model_dump）以兼容 cache_result 的 JSON 序列化。
    endpoint 层负责重新构造 MobileDashboardResponse。
    """
    if query_date:
        try:
            selected_date = datetime.strptime(query_date, "%Y-%m-%d").date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()

    today = selected_date
    today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
    tomorrow = today + timedelta(days=1)
    today_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0)

    stock_data = MobileStockData()
    production_data = MobileProductionData()
    shipping_data = MobileShippingData()
    order_data = MobileOrderData()
    warehouse_data = MobileWarehouseData()

    try:
        # 1. 出库数据：合并当日/当月/总出库为单条 SUM FILTER 查询（3→1）
        # shipping_data 与 stock_data.today_* 查询完全相同，复用避免重复查询（1→0）
        month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)

        stock_row = (await db.execute(
            select(
                func.coalesce(func.sum(StockOut.quantity).filter(
                    StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
                ), 0).label('today_qty'),
                func.coalesce(func.sum(StockOut.quantity * Product.price).filter(
                    StockOut.stockout_date >= today_start, StockOut.stockout_date < today_end
                ), 0).label('today_amt'),
                func.coalesce(func.sum(StockOut.quantity).filter(
                    StockOut.stockout_date >= month_start
                ), 0).label('month_qty'),
                func.coalesce(func.sum(StockOut.quantity * Product.price).filter(
                    StockOut.stockout_date >= month_start
                ), 0).label('month_amt'),
                func.coalesce(func.sum(StockOut.quantity), 0).label('total_qty'),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0).label('total_amt'),
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
        )).one()
        stock_data.today_quantity = int(stock_row.today_qty)
        stock_data.today_amount = round(float(stock_row.today_amt), 2)
        stock_data.month_quantity = int(stock_row.month_qty)
        stock_data.month_amount = round(float(stock_row.month_amt), 2)
        stock_data.total_quantity = int(stock_row.total_qty)
        stock_data.total_amount = round(float(stock_row.total_amt), 2)
        # shipping_data 复用 stock 当日值
        # 业务等价性说明：移动看板中"出货"(shipping) 与"出库"(stock) 在当日维度指同一批
        # StockOut 记录（SUM(quantity) + SUM(quantity*price) WHERE stockout_date=today）。
        # 两者查询完全相同，复用避免重复查询（1→0）。
        # 注意：若未来 stock 模块增加额外过滤条件（如排除某类出库），
        # 需将 shipping 拆分为独立查询，否则 shipping 不会自动跟随变更。
        shipping_data.daily_qty = stock_data.today_quantity
        shipping_data.total_amount = stock_data.today_amount
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板出库数据加载失败: %s", e)

    try:
        # 2. 生产数据：指定日期各部门生产汇总（从DailyProductionRecord读取实际部门数据）
        dpr_result = await db.execute(
            select(
                DailyProductionRecord.department,
                func.coalesce(func.sum(DailyProductionRecord.quantity), 0),
                func.coalesce(func.sum(DailyProductionRecord.quantity * DailyProductionRecord.unit_price), 0),
            )
            .where(extract('year', DailyProductionRecord.production_date) == today.year)
            .where(extract('month', DailyProductionRecord.production_date) == today.month)
            .where(extract('day', DailyProductionRecord.production_date) == today.day)
            .group_by(DailyProductionRecord.department)
        )
        dept_map: dict[str, dict] = {}
        total_val = 0.0

        dept_name_map = {'filling': '充棉部', 'handcraft': '手工部', 'packaging': '包装部'}
        for row in dpr_result.all():
            dept_code = row[0] or 'other'
            dept = dept_name_map.get(dept_code, dept_code)
            qty = int(row[1] or 0)
            val = float(row[2] or 0)
            dept_map[dept] = {"name": dept, "daily_output": qty, "output_value": round(val, 2)}
            total_val += val

        production_data.total_value = round(total_val, 2)

        if not dept_map:
            any_result = await db.execute(
                select(
                    DailyProductionRecord.department,
                    func.coalesce(func.sum(DailyProductionRecord.quantity), 0),
                    func.coalesce(func.sum(DailyProductionRecord.quantity * DailyProductionRecord.unit_price), 0),
                )
                .where(extract('year', DailyProductionRecord.production_date) == today.year)
                .where(extract('month', DailyProductionRecord.production_date) == today.month)
                .group_by(DailyProductionRecord.department)
                .limit(3)
            )
            for row in any_result.all():
                dept_code = row[0] or 'other'
                dept = dept_name_map.get(dept_code, dept_code)
                if dept not in dept_map:
                    qty = int(row[1] or 0)
                    val = float(row[2] or 0)
                    dept_map[dept] = {"name": dept, "daily_output": qty, "output_value": round(val, 2)}
                    total_val += val
            production_data.total_value = round(total_val, 2)

        for d in dept_map.values():
            d["output_value"] = round(d["output_value"], 2)
            production_data.departments.append(MobileDeptData(**d))
        logger.info(f"生产数据加载完成: {len(production_data.departments)}个部门, 总值{production_data.total_value}")
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板生产数据加载失败: %s", e, exc_info=True)

    # 3. 出货数据：复用 stock_data.today_* 值（查询结构与 stock 当日完全相同，已在步骤 1 设置）

    try:
        # 4. 订单数据：合并当日+总订单件数+总金额为 SUM FILTER（3→1），合并库存数量+金额（2→1）
        # 全部基于 OrderItem 展开聚合，与 total_amount 的"件数×单价"语义保持一致：
        #   - total_qty = SUM(oi.quantity)   总订单商品件数（= 用户期望的"总订单数量"）
        #   - total_amt = SUM(oi.quantity * price)  总订单商品金额
        # 历史上 total_qty 误用 count(Order.id)（订单个数，21），与总额 8 千万量级明显不匹配；
        # 改为件数后与 daily_qty/daily_amount 维度一致，并与 total_amount 形成"件数×单价≈总额"。
        # COUNT(Order.id) 单独查询已废弃（行数膨胀 + 多一次 DB 往返）。
        order_row = (await db.execute(
            select(
                func.coalesce(func.sum(OrderItem.quantity).filter(
                    Order.order_date >= today_start, Order.order_date < today_end
                ), 0).label('daily_qty'),
                func.coalesce(func.sum(OrderItem.quantity * Product.price).filter(
                    Order.order_date >= today_start, Order.order_date < today_end
                ), 0).label('daily_amt'),
                func.coalesce(func.sum(OrderItem.quantity), 0).label('total_qty'),
                func.coalesce(func.sum(OrderItem.quantity * Product.price), 0).label('total_amt'),
            )
            .join(OrderItem, OrderItem.order_id == Order.id, isouter=True)
            .join(Product, OrderItem.product_id == Product.id, isouter=True)
            .where(Order.is_deleted.isnot(True))
        )).one()
        order_data.daily_qty = int(order_row.daily_qty)
        order_data.daily_amount = round(float(order_row.daily_amt), 2)
        order_data.total_qty = int(order_row.total_qty)
        order_data.total_amount = round(float(order_row.total_amt), 2)

        # 产品总库存数量 + 金额合并（2→1）
        inv_row = (await db.execute(
            select(
                func.coalesce(func.sum(Product.current_stock), 0).label('inv_qty'),
                func.coalesce(func.sum(Product.current_stock * Product.price), 0).label('inv_amt'),
            )
        )).one()
        order_data.total_inventory = int(inv_row.inv_qty)
        order_data.total_inventory_amount = round(float(inv_row.inv_amt), 2)
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板订单数据加载失败: %s", e)

    try:
        # 5. 皮套仓储：合并 CaseStockIn 数量+金额（2→1）、CaseStockOut 数量+金额（2→1）
        csi_row = (await db.execute(
            select(
                func.coalesce(func.sum(CaseStockIn.quantity), 0).label('qty'),
                func.coalesce(func.sum(CaseStockIn.quantity * Product.price), 0).label('amt'),
            )
            .join(Case, CaseStockIn.case_id == Case.id)
            .join(Product, Case.product_id == Product.id, isouter=True)
            .where(CaseStockIn.stockin_date >= today_start)
            .where(CaseStockIn.stockin_date < today_end)
        )).one()
        warehouse_data.in_qty = int(csi_row.qty)
        warehouse_data.in_amount = round(float(csi_row.amt), 2)

        cso_row = (await db.execute(
            select(
                func.coalesce(func.sum(CaseStockOut.quantity), 0).label('qty'),
                func.coalesce(func.sum(CaseStockOut.quantity * Product.price), 0).label('amt'),
            )
            .join(Case, CaseStockOut.case_id == Case.id)
            .join(Product, Case.product_id == Product.id, isouter=True)
            .where(CaseStockOut.stockout_date >= today_start)
            .where(CaseStockOut.stockout_date < today_end)
        )).one()
        warehouse_data.out_qty = int(cso_row.qty)
        warehouse_data.out_amount = round(float(cso_row.amt), 2)
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板仓储数据加载失败: %s", e)

    # 6. 生产计划数据
    plans_data = {"plans": [], "monthly_summary": None}
    try:
        now = datetime.now()
        year = now.year
        month = now.month

        # 直接从 purchase_plan_details 表获取生产计划数据
        logger.info(f"从 purchase_plan_details 读取生产计划: year={year}, month={month}")
        ppd_result = await db.execute(
            select(
                PurchasePlanDetail.id,
                PurchasePlan.customer_name,
                PurchasePlanDetail.product_name,
                PurchasePlanDetail.barcode,
                PurchasePlanDetail.quantity,
                PurchasePlanDetail.shipped_qty,
                PurchasePlanDetail.plan_date,
                PurchasePlanDetail.remark,
            )
            .join(PurchasePlan, PurchasePlanDetail.plan_id == PurchasePlan.id)
            .where(
                extract('year', PurchasePlanDetail.plan_date) == year,
                extract('month', PurchasePlanDetail.plan_date) == month,
            )
            .order_by(PurchasePlanDetail.plan_date, PurchasePlan.customer_name)
        )
        rows = ppd_result.all()
        logger.info(f"purchase_plan_details 查询返回 {len(rows)} 条")
        item_list = []
        total_plan_qty = 0
        total_shipped_qty = 0
        for row in rows:
            qty = int(row.quantity or 0)
            shipped = int(row.shipped_qty or 0)
            total_plan_qty += qty
            total_shipped_qty += shipped
            plan_date_str = row.plan_date.isoformat() if row.plan_date else ""
            logger.info(f"  详情: customer={row.customer_name}, product={row.product_name}, qty={qty}, date={plan_date_str}")
            item_list.append({
                "id": row.id,
                "customer_name": row.customer_name or "",
                "product_name": row.product_name or "",
                "barcode": row.barcode or "",
                "quantity": qty,
                "inventory_qty": 0,
                "shipped_qty": shipped,
                "remaining_qty": qty - shipped,
                "diff": qty,
                "stock_status": "warning",
                "shipment_status": "pending" if shipped == 0 else ("completed" if shipped >= qty else "partial"),
                "plan_date": plan_date_str,
                "status": "pending",
                "remark": row.remark or "",
            })
        plans_data["plans"] = item_list
        plans_data["monthly_summary"] = {
            "total_plan_qty": total_plan_qty,
            "total_inventory_qty": 0,
            "total_shipped_qty": total_shipped_qty,
            "total_remaining_qty": total_plan_qty - total_shipped_qty,
            "total_diff": total_plan_qty,
            "warning_count": len(item_list),
            "customer_summary": {},
        }
        logger.info(f"生产计划数据准备完成: {len(item_list)} 条")
    except Exception as e:  # defensive: 移动看板单个数据卡片失败时继续加载其他卡片
        logger.warning("移动看板生产计划数据加载失败", exc_info=True)
        if hasattr(e, '__cause__') and e.__cause__:
            logger.warning(f"  原因: {e.__cause__}")

    return MobileDashboardResponse(
        success=True,
        data=MobileDashboardData(
            stock=stock_data,
            production=production_data,
            shipping=shipping_data,
            orders=order_data,
            warehouse=warehouse_data,
            production_plans=plans_data,
        )
    ).model_dump()
