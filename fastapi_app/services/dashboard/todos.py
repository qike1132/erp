"""仪表盘待办(todos)聚合

从 dashboard_service.py 按主题拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.schemas.dashboard import TodoItem, TodoListResponse
from fastapi_app.shared_models import Order

logger = logging.getLogger(__name__)


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
