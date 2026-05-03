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

from fastapi_app.core.database import get_async_db
from fastapi_app.core.deps import get_current_user_id
from fastapi_app.shared_models import ApprovalRequest, Order, Product, PurchaseOrder, StockIn, StockOut
from fastapi_app.shared_models.material_registration import MaterialRegistration

logger = logging.getLogger(__name__)

router = APIRouter()

_CACHE_KEY = "dashboard:stats"
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


class Activity(BaseModel):
    type: str
    time: str
    status: str
    title: str
    desc: str


async def _get_cached_stats():
    try:
        from utils.redis_cache import redis_cache
        cached = await redis_cache.get(_CACHE_KEY)
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
        await redis_cache.set(_CACHE_KEY, json.dumps(data, default=str), timeout=_CACHE_TTL)
    except (OSError, ValueError):
        logger.warning("仪表盘缓存写入失败", exc_info=True)


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
        return data
    except (OperationalError, DisconnectionError) as e:
        logger.warning("仪表盘异步统计加载失败: %s [%s]", e, type(e).__name__)
        return {"order_today": 0, "stockin_today": 0, "stockout_today": 0, "pending_approvals": 0,
                    "order_yesterday": 0, "stockin_yesterday": 0, "stockout_yesterday": 0,
                    "low_stock_count": 0, "pending_purchases": 0, "pending_materials": 0}


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


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
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

    return DashboardStats(**dashboard_stats)


@router.get("/activities", response_model=list[Activity])
async def get_dashboard_activities(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db),
):
    """仪表盘最近活动数据（实时查询）"""
    try:
        activities = await _fetch_activities_async(db)
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
