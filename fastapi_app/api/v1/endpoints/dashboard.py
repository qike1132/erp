"""
仪表盘 API

为 Vue/Vite 前端提供仪表盘统计数据和最近活动数据。
从 pages.py:index_page 的服务端渲染逻辑提取而来。
"""

import json
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, extract, func, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.shared_models import (
    ApprovalRequest, Case, CaseStockIn, CaseStockOut, DailyProductionRecord,
    Order, Product, PurchaseOrder, PurchasePlan, PurchasePlanDetail,
    StockIn, StockOut,
)
from fastapi_app.shared_models.material_registration import MaterialRegistration

logger = logging.getLogger(__name__)

router = APIRouter()

_CACHE_KEY_STATS = "dashboard:stats"
_CACHE_KEY_ACTIVITIES = "dashboard:activities"
_CACHE_TTL = 300


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


class SystemStatus(BaseModel):
    is_running: bool = True
    last_sync_time: str = ""
    data_status: str = "up_to_date"


class SystemStatusResponse(BaseModel):
    success: bool = True
    data: SystemStatus | None = None


class DashboardResponse(BaseModel):
    success: bool = True
    data: DashboardStats | None = None


class Activity(BaseModel):
    type: str
    time: str
    status: str
    title: str
    desc: str


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


async def _get_cached_stats():
    try:
        from utils.redis_cache import redis_cache
        cached = await redis_cache.get(_CACHE_KEY_STATS)
        if cached:
            if isinstance(cached, str):
                return json.loads(cached)
            return cached
    except (OSError, ValueError):
        logger.warning("仪表盘缓存读取失败", exc_info=True)
    return None


async def _set_cached_stats(data):
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.set(_CACHE_KEY_STATS, json.dumps(data, default=str), timeout=_CACHE_TTL)
    except (OSError, ValueError):
        logger.warning("仪表盘缓存写入失败", exc_info=True)


async def _get_cached_activities():
    try:
        from utils.redis_cache import redis_cache
        cached = await redis_cache.get(_CACHE_KEY_ACTIVITIES)
        if cached:
            if isinstance(cached, str):
                return json.loads(cached)
            return cached
    except (OSError, ValueError):
        logger.warning("仪表盘活动缓存读取失败", exc_info=True)
    return None


async def _set_cached_activities(data):
    try:
        from utils.redis_cache import redis_cache
        await redis_cache.set(_CACHE_KEY_ACTIVITIES, json.dumps(data, default=str), timeout=60)
    except (OSError, ValueError):
        logger.warning("仪表盘活动缓存写入失败", exc_info=True)


async def _fetch_stats_async(db: AsyncSession) -> dict:
    try:
        today = date.today()
        yesterday = today - timedelta(days=1)

        # 拆分为单表查询，避免 CROSS JOIN 导致计数膨胀或 date/datetime 比较异常
        order_today = int((await db.execute(
            select(func.coalesce(func.sum(Order.quantity), 0)).where(
                and_(Order.order_date >= today, Order.is_deleted.isnot(True)))
        )).scalar() or 0)

        order_yesterday = int((await db.execute(
            select(func.coalesce(func.sum(Order.quantity), 0)).where(
                and_(Order.order_date >= yesterday, Order.order_date < today, Order.is_deleted.isnot(True)))
        )).scalar() or 0)

        stockin_today = int((await db.execute(
            select(func.coalesce(func.sum(StockIn.quantity), 0)).where(StockIn.stockin_date >= today)
        )).scalar() or 0)

        stockin_yesterday = int((await db.execute(
            select(func.coalesce(func.sum(StockIn.quantity), 0)).where(
                and_(StockIn.stockin_date >= yesterday, StockIn.stockin_date < today))
        )).scalar() or 0)

        stockout_today = int((await db.execute(
            select(func.coalesce(func.sum(StockOut.quantity), 0)).where(StockOut.stockout_date >= today)
        )).scalar() or 0)

        stockout_yesterday = int((await db.execute(
            select(func.coalesce(func.sum(StockOut.quantity), 0)).where(
                and_(StockOut.stockout_date >= yesterday, StockOut.stockout_date < today))
        )).scalar() or 0)

        pending_approvals = (await db.execute(
            select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending")
        )).scalar() or 0

        data = {
            "order_today": order_today,
            "stockin_today": stockin_today,
            "stockout_today": stockout_today,
            "pending_approvals": pending_approvals,
            "order_yesterday": order_yesterday,
            "stockin_yesterday": stockin_yesterday,
            "stockout_yesterday": stockout_yesterday,
        }

        low_stock_count = (await db.execute(
            select(func.count(Product.id)).where(Product.current_stock <= 10)
        )).scalar() or 0

        pending_purchases = (await db.execute(
            select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status.in_(["pending", "partial"]))
        )).scalar() or 0

        pending_materials = (await db.execute(
            select(func.count(MaterialRegistration.id)).where(MaterialRegistration.status.in_(["pending", "partial"]))
        )).scalar() or 0

        data["low_stock_count"] = low_stock_count
        data["pending_purchases"] = pending_purchases
        data["pending_materials"] = pending_materials

        data["total_orders_today"] = data["order_today"]
        data["total_shipments_today"] = data["stockout_today"]
        try:
            from fastapi_app.shared_models.production_plan import ProductionPlan
            prod_stats = (await db.execute(
                select(
                    func.count(ProductionPlan.id).filter(ProductionPlan.plan_date >= today),
                    func.count(ProductionPlan.id).filter(and_(ProductionPlan.plan_date >= today, ProductionPlan.status == "completed")),
                )
            )).one()
            total_plans = prod_stats[0] or 0
            completed_plans = prod_stats[1] or 0
            data["production_completion_rate"] = round(completed_plans / total_plans, 2) if total_plans > 0 else 0.0
            data["pending_shipments"] = total_plans - completed_plans
        except Exception:
            data["production_completion_rate"] = 0.0
            data["pending_shipments"] = 0
        return data
    except (OperationalError, DisconnectionError) as e:
        logger.warning("仪表盘异步统计加载失败: %s [%s]", e, type(e).__name__)
        return {"order_today": 0, "stockin_today": 0, "stockout_today": 0, "pending_approvals": 0,
                    "order_yesterday": 0, "stockin_yesterday": 0, "stockout_yesterday": 0,
                    "low_stock_count": 0, "pending_purchases": 0, "pending_materials": 0,
                    "production_completion_rate": 0.0, "pending_shipments": 0,
                    "total_shipments_today": 0, "total_orders_today": 0}


async def _fetch_activities_async(db: AsyncSession) -> list:
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
        return activities[:8]
    except (OperationalError, DisconnectionError) as e:
        logger.warning("仪表盘异步活动加载失败: %s [%s]", e, type(e).__name__)
        return []


@router.get("/stats", response_model=DashboardResponse)
async def get_dashboard_stats(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘统计数据（Redis缓存5分钟）"""
    dashboard_stats = await _get_cached_stats()

    if dashboard_stats is None:
        try:
            dashboard_stats = await _fetch_stats_async(db)
            await _set_cached_stats(dashboard_stats)
        except (OperationalError, DisconnectionError):
            logger.warning("仪表盘统计查询失败", exc_info=True)
            dashboard_stats = {}

    return DashboardResponse(
        success=True,
        data=DashboardStats(**dashboard_stats)
    )


@router.get("/activities", response_model=list[Activity])
async def get_dashboard_activities(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘最近活动数据（Redis缓存60秒）"""
    cached_activities = await _get_cached_activities()
    if cached_activities is not None:
        return [Activity(**a) for a in cached_activities]
    try:
        activities = await _fetch_activities_async(db)
        await _set_cached_activities(activities)
        return [Activity(**a) for a in activities]
    except (OperationalError, DisconnectionError) as e:
        logger.warning("仪表盘活动加载失败: %s [%s]", e, type(e).__name__)
        return []


@router.get("/nav-sections", response_model=dict[str, NavSection])
async def get_nav_sections(user_id: int = Depends(get_current_user_id)):
    """导航菜单数据（供前端使用）"""
    from fastapi_app.core.nav_context import get_nav_sections_async
    sections = await get_nav_sections_async()
    return sections


@router.get("/todos", response_model=TodoListResponse)
async def get_dashboard_todos(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """仪表盘待办事项"""
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
            from fastapi_app.shared_models.production_plan import ProductionPlan
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
        except Exception as e:
            logger.warning("获取出货计划待办失败: %s", e)
        todos.sort(key=lambda x: 0 if x.urgency == "urgent" else 1)
        return TodoListResponse(success=True, data=todos[:10])
    except Exception as e:
        logger.warning("仪表盘待办加载失败: %s", e, exc_info=True)
        return TodoListResponse(success=True, data=[])


@router.get("/system-status", response_model=SystemStatusResponse)
async def get_system_status(
    user_id: int = Depends(get_current_user_id),
):
    """系统运行状态"""
    return SystemStatusResponse(
        success=True,
        data=SystemStatus(
            is_running=True,
            last_sync_time=str(date.today()),
            data_status="up_to_date"
        )
    )


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


class CustomerOutDetail(BaseModel):
    customer_name: str = ""
    total_quantity: int = 0
    total_amount: float = 0.0


class CustomerOutDetailResponse(BaseModel):
    success: bool = True
    data: list[CustomerOutDetail] = []


class MobileDashboardResponse(BaseModel):
    success: bool = True
    data: MobileDashboardData | None = None


@router.get("/mobile", response_model=MobileDashboardResponse)
async def get_mobile_dashboard(
    query_date: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """移动端数据看板（一次聚合所有板块数据）"""
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
        # 1. 出库数据：当日和当月的出货数量+金额 + 总出货
        month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)
        
        # 当日出库
        today_result = await db.execute(
            select(
                func.coalesce(func.sum(StockOut.quantity), 0),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0)
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
            .where(StockOut.stockout_date >= today_start)
            .where(StockOut.stockout_date < today_end)
        )
        today_row = today_result.one_or_none()
        if today_row:
            stock_data.today_quantity = int(today_row[0] or 0)
            stock_data.today_amount = round(float(today_row[1] or 0), 2)
        
        # 当月出库
        month_result = await db.execute(
            select(
                func.coalesce(func.sum(StockOut.quantity), 0),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0)
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
            .where(StockOut.stockout_date >= month_start)
        )
        month_row = month_result.one_or_none()
        if month_row:
            stock_data.month_quantity = int(month_row[0] or 0)
            stock_data.month_amount = round(float(month_row[1] or 0), 2)
        
        # 总出库（所有时间）
        total_result = await db.execute(
            select(
                func.coalesce(func.sum(StockOut.quantity), 0),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0)
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
        )
        total_row = total_result.one_or_none()
        if total_row:
            stock_data.total_quantity = int(total_row[0] or 0)
            stock_data.total_amount = round(float(total_row[1] or 0), 2)
    except Exception as e:
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
    except Exception as e:
        logger.warning("移动看板生产数据加载失败: %s", e, exc_info=True)

    try:
        # 3. 出货数据：指定日期出货数量 + 金额
        so_result = await db.execute(
            select(
                func.coalesce(func.sum(StockOut.quantity), 0),
                func.coalesce(func.sum(StockOut.quantity * Product.price), 0)
            )
            .join(Product, StockOut.product_id == Product.id, isouter=True)
            .where(StockOut.stockout_date >= today_start)
            .where(StockOut.stockout_date < today_end)
        )
        row = so_result.one_or_none()
        if row:
            shipping_data.daily_qty = int(row[0] or 0)
            shipping_data.total_amount = round(float(row[1] or 0), 2)
    except Exception as e:
        logger.warning("移动看板出货数据加载失败: %s", e)

    try:
        # 4. 订单数据：指定日期订单数量 + 金额
        o_result = await db.execute(
            select(
                func.coalesce(func.sum(Order.quantity), 0),
                func.coalesce(func.sum(Order.quantity * Product.price), 0)
            )
            .join(Product, Order.product_id == Product.id, isouter=True)
            .where(Order.order_date >= today_start)
            .where(Order.order_date < today_end)
            .where(Order.is_deleted.isnot(True))
        )
        row = o_result.one_or_none()
        if row:
            order_data.daily_qty = int(row[0] or 0)
            order_data.daily_amount = round(float(row[1] or 0), 2)
        
        # 总订单（所有时间）- 订单条目数
        count_o = await db.execute(
            select(func.count(Order.id))
            .where(Order.is_deleted.isnot(True))
        )
        order_data.total_qty = int(count_o.scalar() or 0)
        
        # 总订单金额
        total_o = await db.execute(
            select(func.coalesce(func.sum(Order.quantity * Product.price), 0))
            .join(Product, Order.product_id == Product.id, isouter=True)
            .where(Order.is_deleted.isnot(True))
        )
        order_data.total_amount = round(float(total_o.scalar() or 0), 2)
        
        # 产品总库存数量
        total_inv = await db.execute(
            select(func.coalesce(func.sum(Product.current_stock), 0))
        )
        order_data.total_inventory = int(total_inv.scalar() or 0)
        
        # 产品总库存金额（库存数量 × 产品价格）
        total_inv_amt = await db.execute(
            select(func.coalesce(func.sum(Product.current_stock * Product.price), 0))
        )
        order_data.total_inventory_amount = round(float(total_inv_amt.scalar() or 0), 2)
    except Exception as e:
        logger.warning("移动看板订单数据加载失败: %s", e)

    try:
        # 5. 皮套仓储：指定日期进/出仓数量 + 金额
        csi_qty = await db.execute(
            select(func.coalesce(func.sum(CaseStockIn.quantity), 0))
            .where(CaseStockIn.stockin_date >= today_start)
            .where(CaseStockIn.stockin_date < today_end)
        )
        warehouse_data.in_qty = int(csi_qty.scalar() or 0)

        cso_qty = await db.execute(
            select(func.coalesce(func.sum(CaseStockOut.quantity), 0))
            .where(CaseStockOut.stockout_date >= today_start)
            .where(CaseStockOut.stockout_date < today_end)
        )
        warehouse_data.out_qty = int(cso_qty.scalar() or 0)

        csi_amt = await db.execute(
            select(func.coalesce(func.sum(CaseStockIn.quantity * Product.price), 0))
            .join(Case, CaseStockIn.case_id == Case.id)
            .join(Product, Case.product_id == Product.id, isouter=True)
            .where(CaseStockIn.stockin_date >= today_start)
            .where(CaseStockIn.stockin_date < today_end)
        )
        warehouse_data.in_amount = round(float(csi_amt.scalar() or 0), 2)

        cso_amt = await db.execute(
            select(func.coalesce(func.sum(CaseStockOut.quantity * Product.price), 0))
            .join(Case, CaseStockOut.case_id == Case.id)
            .join(Product, Case.product_id == Product.id, isouter=True)
            .where(CaseStockOut.stockout_date >= today_start)
            .where(CaseStockOut.stockout_date < today_end)
        )
        warehouse_data.out_amount = round(float(cso_amt.scalar() or 0), 2)
    except Exception as e:
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
    except Exception as e:
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
    )


@router.get("/customer-out-details", response_model=CustomerOutDetailResponse)
async def get_customer_out_details(
    period: str = "today",
    query_date: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取客户出库详情
    
    Args:
        period: 时间段，可选 "today"（当日）或 "month"（当月）
        query_date: 指定日期，格式 YYYY-MM-DD，默认为今天
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
    month_start = datetime(selected_date.year, selected_date.month, 1, 0, 0, 0)
    
    # 根据period确定时间范围
    if period == "month":
        start_time = month_start
        end_time = datetime(selected_date.year, selected_date.month + 1, 1, 0, 0, 0) if selected_date.month < 12 else datetime(selected_date.year + 1, 1, 1, 0, 0, 0)
    else:
        start_time = today_start
        end_time = today_end
    
    try:
        # 按客户汇总出库数据
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
            customer_name = row[0] or "未知客户"
            total_quantity = int(row[1] or 0)
            total_amount = round(float(row[2] or 0), 2)
            details.append(CustomerOutDetail(
                customer_name=customer_name,
                total_quantity=total_quantity,
                total_amount=total_amount
            ))
        
        return CustomerOutDetailResponse(success=True, data=details)
    except Exception as e:
        logger.warning("客户出库详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[])


@router.get("/customer-order-details", response_model=CustomerOutDetailResponse)
async def get_customer_order_details(
    period: str = "today",
    date_param: str | None = None,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_read_db),
):
    """获取客户订单详情
    
    Args:
        period: 时间段，可选 "today"（当日）或 "month"（当月）
        date_param: 指定日期，格式 YYYY-MM-DD，默认为今天
    """
    if date_param:
        try:
            from datetime import datetime as dt
            selected_date = dt.strptime(date_param, "%Y-%m-%d").date()
        except ValueError:
            selected_date = date.today()
    else:
        selected_date = date.today()
    
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
        # 按客户汇总订单数据（按 period 过滤时间范围）
        result = await db.execute(
            select(
                Order.customer,
                func.coalesce(func.sum(Order.quantity), 0),
                func.coalesce(func.sum(Order.quantity * Product.price), 0)
            )
            .join(Product, Order.product_id == Product.id, isouter=True)
            .where(Order.order_date >= start_time)
            .where(Order.order_date < end_time)
            .where(Order.is_deleted.isnot(True))
            .where(Order.customer.isnot(None))
            .where(Order.customer != "")
            .group_by(Order.customer)
        )
        
        details = []
        for row in result.all():
            customer_name = row[0] or "未知客户"
            total_quantity = int(row[1] or 0)
            total_amount = round(float(row[2] or 0), 2)
            details.append(CustomerOutDetail(
                customer_name=customer_name,
                total_quantity=total_quantity,
                total_amount=total_amount
            ))
        
        return CustomerOutDetailResponse(success=True, data=details)
    except Exception as e:
        logger.warning("客户订单详情加载失败: %s", e)
        return CustomerOutDetailResponse(success=True, data=[])

