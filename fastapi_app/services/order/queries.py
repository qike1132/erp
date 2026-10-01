"""订单查询（详情/列表分页/筛选/序列化/我的审批请求）

自 order_crud.py 拆分（批次1-3），函数原文零改动。"""
# ruff: noqa: F401 - 拆分过渡期沿用完整导入块，待按模块收敛未用导入
import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import CacheDomain, cache_result
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
from fastapi_app.core.exceptions import BusinessError, NotFoundError
from fastapi_app.core.state_machine import can_transition
from fastapi_app.core.validators import validate_not_empty, validate_quantity_range
from fastapi_app.services import escape_like
from fastapi_app.services.enhanced_pagination import (
    OFFSET_THRESHOLD,
    optimized_count,
)
from fastapi_app.services.notification_service import (
    StockEvent,
    dispatch_factory_notifications,
)
from fastapi_app.services.order._common import (
    PermissionDeniedError,
    _log_background_task_exception,
    _pending_tasks,
    _safe_invalidate_purchase_cache,
    _safe_publish_event,
)
from fastapi_app.services.order_utils import (
    _batch_deduct_quantities,
    compute_order_status_from_db,
)
from fastapi_app.services.serializers.order_serializer import (
    OrderSerializer,
)
from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import (
    ApprovalLog,
    ApprovalRequest,
    InventoryLog,
    Notification,
    Order,
    OrderItem,
    OrderSyncRecord,
    Product,
    StockIn,
    StockOut,
    User,
)
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

logger = logging.getLogger(__name__)





async def get_order_by_id(db: AsyncSession, order_id: int) -> dict | None:
    """根据ID获取单个订单详情（含关联数据）"""

    query = select(Order).options(
        joinedload(Order.product),
        joinedload(Order.locked_by),
        selectinload(Order.items),
    ).where(Order.id == order_id, Order.is_deleted.isnot(True))

    result = await db.execute(query)
    order = result.scalars().unique().first()
    if not order:
        return None

    deduct_map = await _batch_deduct_quantities(db, [order.id])
    return OrderSerializer.serialize(
        order, OrderSerializer.DETAIL_CONFIG, deduct_quantity=deduct_map.get(order.id, 0)
    )

def _parse_date_condition(date_str: str | None, is_end: bool = False):
    """解析日期字符串为 SQL 条件。

    空值返回 None（不筛选）；非法格式抛 BusinessError（HTTP 400），
    不再静默忽略，避免用户误以为筛选已生效。
    """
    if not date_str:
        return None
    try:
        if is_end:
            end_dt = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=UTC)
            return Order.order_date <= end_dt
        start_dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=UTC)
        return Order.order_date >= start_dt
    except ValueError:
        raise BusinessError(f"{'结束' if is_end else '开始'}日期格式错误，应为 YYYY-MM-DD") from None

def _build_order_filters(customer: str | None, product_id: int | None,
                         status: str | None,
                         start_date: str | None, end_date: str | None) -> list:
    """构建订单筛选条件列表（共用，避免 DRY 违反）。"""
    conditions: list[ColumnElement[bool]] = []
    if customer:
        conditions.append(Order.customer.like(f'%{escape_like(customer)}%'))
    if product_id:
        conditions.append(Order.product_id == product_id)
    if status:
        conditions.append(Order.status == status)
    start_cond = _parse_date_condition(start_date)
    if start_cond is not None:
        conditions.append(start_cond)
    end_cond = _parse_date_condition(end_date, is_end=True)
    if end_cond is not None:
        conditions.append(end_cond)
    return conditions

async def _fetch_orders_page(db: AsyncSession, query, conditions: list,
                             offset: int, per_page: int) -> list:
    """执行分页查询，深翻页自动切换 keyset 分页。"""
    # 常规翻页：OFFSET + LIMIT
    if offset <= OFFSET_THRESHOLD:
        result = await db.execute(
            query.order_by(Order.order_date.desc())
            .offset(offset)
            .limit(per_page)
        )
        return list(result.scalars().unique().all())

    # 深翻页：用子查询定位游标值，避免 OFFSET 扫描跳过大量行
    logger.debug("深翻页 offset=%d 超过阈值 %d，自动使用keyset分页", offset, OFFSET_THRESHOLD)
    # 构造不含 eager load 的纯定位子查询（更快），使用 (order_date, id) 组合游标确保唯一性
    cursor_base = select(Order.order_date, Order.id).where(Order.is_deleted.isnot(True))
    for condition in conditions:
        cursor_base = cursor_base.where(condition)
    cursor_subq = cursor_base.order_by(Order.order_date.desc(), Order.id.desc()).offset(offset).limit(1).subquery()
    # 使用组合游标 (order_date, id) 做行比较，确保相同时间戳的行也能正确定位
    result = await db.execute(
        query.where(tuple_(Order.order_date, Order.id) <= select(cursor_subq.c.order_date, cursor_subq.c.id))
        .order_by(Order.order_date.desc(), Order.id.desc())
        .limit(per_page)
    )
    orders = list(result.scalars().unique().all())
    # fallback: 并发删除可能导致游标偏移，回退到 OFFSET
    if orders:
        return orders
    logger.debug("keyset分页返回空，fallback到OFFSET分页")
    result = await db.execute(
        query.order_by(Order.order_date.desc())
        .offset(offset)
        .limit(per_page)
    )
    return list(result.scalars().unique().all())

async def _batch_item_factories(db: AsyncSession, order_ids: list[int]) -> dict[int, list[str]]:
    """批量查询每个订单涉及的 SKU 工厂名（单次 JOIN 聚合）。

    `factories` 字段需要 item → product.factory 这一跳，而 `selectinload(Order.items)`
    **不会**连带加载 `OrderItem.product`；异步会话里访问未加载的关系会抛 MissingGreenlet，
    使整个订单列表接口 500。这里用一次 JOIN 把结果预取出来交给序列化器。
    """
    if not order_ids:
        return {}
    result = await db.execute(
        select(OrderItem.order_id, Product.factory)
        .join(Product, OrderItem.product_id == Product.id)
        .where(OrderItem.order_id.in_(order_ids), Product.factory.isnot(None))
        .distinct()
    )
    grouped: dict[int, set[str]] = {}
    for order_id, factory in result.all():
        if factory:
            grouped.setdefault(order_id, set()).add(factory)
    return {oid: sorted(names) for oid, names in grouped.items()}

def _serialize_orders(orders: list, deduct_map: dict, factory_map: dict | None = None) -> list:
    """序列化订单列表。"""
    factories = factory_map or {}
    return [
        OrderSerializer.serialize(
            order,
            OrderSerializer.LIST_CONFIG,
            deduct_quantity=deduct_map.get(order.id, 0),
            item_factories=factories.get(order.id, []),
        )
        for order in orders
    ]

# local_ttl=0：禁用 L1，仅走 L2。生产为多 worker 且 CACHE_L1_BROADCAST_ENABLED 关闭，
# L1 无法跨 worker 失效 —— 订单写入后 invalidate_cache("orders:*") 只删 L2，
# 其余 worker 的 L1 仍会在 TTL 内返回删除/改数量前的旧列表（客户订单页自身也受影响）。
# 与 orders:beile:list 同一处理；代价仅每次请求一次本地 Redis GET。
@cache_result(
    key_prefix="orders:list",
    ttl=60,
    local_ttl=0,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:c{kwargs.get('customer', '')}:pid{kwargs.get('product_id', '')}:s{kwargs.get('status', '')}:sd{kwargs.get('start_date', '')}:ed{kwargs.get('end_date', '')}:f{kwargs.get('factory', '')}",
)
async def get_orders(db: AsyncSession, page: int = 1, per_page: int = 50,
                     customer: str | None = None, product_id: int | None = None,
                     status: str | None = None,
                     start_date: str | None = None, end_date: str | None = None,
                     factory: str | None = None) -> dict:
    """获取订单列表（含关联数据，支持分页和筛选）

    Args:
        factory: 工厂筛选（东莞/湖北）。非空时仅返回包含该工厂 SKU 的订单。
            权限隔离由调用层（endpoint）负责：当 current_user.factory 非空且非超管时，
            调用方应强制传入 current_user.factory，忽略前端参数。
    """
    # 基础查询（移除 selectinload(order_stockouts)，改用 SQL 聚合）
    query = select(Order).options(
        joinedload(Order.product),
        joinedload(Order.locked_by),
        selectinload(Order.items),
    ).where(Order.is_deleted.isnot(True))
    count_query = select(func.count(Order.id)).where(Order.is_deleted.isnot(True))

    # 筛选条件（共用，避免 DRY 违反）
    conditions = _build_order_filters(customer, product_id, status, start_date, end_date)
    # 工厂筛选：订单包含至少一个属于该工厂的 SKU（加入 conditions 以便深翻页游标子查询同步过滤）
    if factory:
        conditions.append(Order.items.any(OrderItem.product.has(Product.factory == factory)))
    for condition in conditions:
        query = query.where(condition)
        count_query = count_query.where(condition)

    # 总数 (use approximate count for large tables to avoid full scan)
    total = await optimized_count(db, count_query, table_name='order')

    # 分页查询 — 深翻页自动切换 keyset 分页
    offset = (page - 1) * per_page
    orders = await _fetch_orders_page(db, query, conditions, offset, per_page)

    # 单次 SQL 聚合获取所有订单的抵扣数量，替代 selectinload + Python 遍历
    order_ids = [o.id for o in orders]
    deduct_map = await _batch_deduct_quantities(db, order_ids)
    factory_map = await _batch_item_factories(db, order_ids)

    orders_data = _serialize_orders(orders, deduct_map, factory_map)
    return {'items': orders_data, 'total': total, 'page': page, 'per_page': per_page}

async def get_my_approvals(db: AsyncSession, current_user: User) -> list[dict]:
    """获取我的审批请求"""
    result = await db.execute(
        select(ApprovalRequest)
        .options(joinedload(ApprovalRequest.order), joinedload(ApprovalRequest.requester))
        .where(ApprovalRequest.requester_id == current_user.id)
        .order_by(ApprovalRequest.request_time.desc())
    )
    approvals = result.scalars().unique().all()
    return [a.to_dict() for a in approvals]
