"""仪表盘动态(activities)聚合

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import DisconnectionError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.schemas.dashboard import Activity
from fastapi_app.shared_models import ApprovalRequest, Order, StockIn, StockOut

logger = logging.getLogger(__name__)

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