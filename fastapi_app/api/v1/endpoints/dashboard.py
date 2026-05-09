"""
仪表盘 API

为 Vue/Vite 前端提供仪表盘统计数据和最近活动数据。
从 pages.py:index_page 的服务端渲染逻辑提取而来。
"""

import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_db, get_async_read_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.shared_models import ApprovalRequest, Order, Product, PurchaseOrder, StockIn, StockOut
from fastapi_app.shared_models.material_registration import MaterialRegistration

logger = logging.getLogger(__name__)

router = APIRouter()

_CACHE_KEY_STATS = "dashboard:stats"
_CACHE_KEY_ACTIVITIES = "dashboard:activities"
_CACHE_TTL = 300


class DashboardStats(BaseModel):
    order_today: int = 0
    order_yesterday: int = 0
    stockin_today: int = 0
    stockin_yesterday: int = 0
    stockout_today: int = 0
    stockout_yesterday: int = 0
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

        data = {}
        data["order_today"] = (await db.execute(select(func.count(Order.id)).where(Order.order_date >= today))).scalar() or 0
        data["stockin_today"] = (await db.execute(select(func.count(StockIn.id)).where(StockIn.stockin_date >= today))).scalar() or 0
        data["stockout_today"] = (await db.execute(select(func.count(StockOut.id)).where(StockOut.stockout_date >= today))).scalar() or 0
        data["pending_approvals"] = (await db.execute(select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status == "pending"))).scalar() or 0

        data["order_yesterday"] = (await db.execute(select(func.count(Order.id)).where(and_(Order.order_date >= yesterday, Order.order_date < today)))).scalar() or 0
        data["stockin_yesterday"] = (await db.execute(select(func.count(StockIn.id)).where(and_(StockIn.stockin_date >= yesterday, StockIn.stockin_date < today)))).scalar() or 0
        data["stockout_yesterday"] = (await db.execute(select(func.count(StockOut.id)).where(and_(StockOut.stockout_date >= yesterday, StockOut.stockout_date < today)))).scalar() or 0

        data["low_stock_count"] = (await db.execute(select(func.count(Product.id)).where(Product.current_stock <= 10))).scalar() or 0
        data["pending_purchases"] = (await db.execute(select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status.in_(["pending", "partial"])))).scalar() or 0
        data["pending_materials"] = (await db.execute(select(func.count(MaterialRegistration.id)).where(MaterialRegistration.status.in_(["pending", "partial"])))).scalar() or 0

        data["total_orders_today"] = data["order_today"]
        data["total_shipments_today"] = data["stockout_today"]
        try:
            from fastapi_app.shared_models.production_plan import ProductionPlan
            total_plans = (await db.execute(select(func.count(ProductionPlan.id)).where(ProductionPlan.plan_date >= today))).scalar() or 0
            completed_plans = (await db.execute(select(func.count(ProductionPlan.id)).where(and_(ProductionPlan.plan_date >= today, ProductionPlan.status == "completed")))).scalar() or 0
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


@router.get("/nav-sections")
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
