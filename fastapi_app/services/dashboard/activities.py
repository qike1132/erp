"""仪表盘动态(activities)聚合

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.schemas.dashboard import Activity
from fastapi_app.services.dashboard.scope import DashboardReadScope, dashboard_cache_key
from fastapi_app.shared_models import ApprovalRequest, Order, OrderItem, Product, StockIn, StockOut

logger = logging.getLogger(__name__)

_CACHE_KEY_ACTIVITIES = "dashboard:activities"


async def _get_cached_activities(key: str):
    from fastapi_app.core.redis_wrapper import safe_get
    cached = await safe_get(key, context="仪表盘活动缓存")
    if cached is not None:
        if isinstance(cached, str):
            return json.loads(cached)
        return cached
    return None

async def _set_cached_activities(key: str, data):
    from fastapi_app.core.redis_wrapper import safe_set
    await safe_set(key, json.dumps(data, default=str), timeout=60, context="仪表盘活动缓存")

async def fetch_dashboard_activities(db: AsyncSession, scope: DashboardReadScope) -> list[Activity]:
    """仅查询有读取权限的活动来源，按授权范围缓存。"""
    if not (scope.orders or scope.stockin or scope.stockout or scope.approvals):
        return []
    key = f'{_CACHE_KEY_ACTIVITIES}:{dashboard_cache_key(scope=scope)}'
    cached_activities = await _get_cached_activities(key)
    if cached_activities is not None:
        return [Activity(**a) for a in cached_activities]
    try:
        activities = []

        if scope.orders:
            order_stmt = select(Order).where(Order.is_deleted.isnot(True))
            if scope.factory:
                order_stmt = order_stmt.where(Order.items.any(OrderItem.product.has(Product.factory == scope.factory)))
            order_rows = await db.execute(order_stmt.order_by(Order.order_date.desc()).limit(4))
            for o in order_rows.scalars().all():
                activities.append({"type": "order", "time": str(o.order_date) if o.order_date else "",
                                   "status": o.status or "", "title": f"订单 {o.order_no}", "desc": f"订单 {o.order_no}"})

        if scope.stockin:
            stockin_stmt = select(StockIn)
            if scope.factory:
                stockin_stmt = stockin_stmt.where(StockIn.product.has(Product.factory == scope.factory))
            stockin_rows = await db.execute(stockin_stmt.order_by(StockIn.stockin_date.desc()).limit(3))
            for si in stockin_rows.scalars().all():
                activities.append({"type": "stockin", "time": str(si.stockin_date) if si.stockin_date else "",
                                   "status": "已备货", "title": f"入库 {si.stockin_no}", "desc": f"入库 {si.stockin_no}"})

        if scope.stockout:
            stockout_stmt = select(StockOut)
            if scope.factory:
                stockout_stmt = stockout_stmt.where(StockOut.product.has(Product.factory == scope.factory))
            stockout_rows = await db.execute(stockout_stmt.order_by(StockOut.stockout_date.desc()).limit(3))
            for so in stockout_rows.scalars().all():
                activities.append({"type": "stockout", "time": str(so.stockout_date) if so.stockout_date else "",
                                   "status": "已出货", "title": f"出库 {so.stockout_no}", "desc": f"出库 {so.stockout_no}"})

        if scope.approvals:
            approval_rows = await db.execute(select(ApprovalRequest).order_by(ApprovalRequest.request_time.desc()).limit(3))
            for a in approval_rows.scalars().all():
                activities.append({"type": "approval", "time": str(a.request_time) if a.request_time else "",
                                   "status": a.status or "待审批", "title": "审批请求", "desc": "审批请求"})

        activities.sort(key=lambda x: x["time"], reverse=True)
        activities = activities[:8]
        await _set_cached_activities(key, activities)
        return [Activity(**a) for a in activities]
    except (OperationalError, DisconnectionError):
        # M-16 族（2026-11-21 审计）：连接类异常交全局 503 处理器，不得吞成空活动列表。
        logger.warning("仪表盘活动加载失败（连接类，转 503）", exc_info=True)
        raise
