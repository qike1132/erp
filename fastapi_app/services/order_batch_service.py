"""订单批次号管理服务层"""
import contextlib
import json
import logging
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from fastapi_app.services import escape_like
from fastapi_app.services.serializers.order_serializer import OrderSerializer
from fastapi_app.shared_models import Order, OrderBatchAuditLog, OrderSyncConfig, Product, StockOut, User

logger = logging.getLogger(__name__)

_WHITELIST_CACHE_KEY = "order_batch:whitelist"
_WHITELIST_TTL = 300


async def _safe_publish_event(event_type: str, data: dict):
    try:
        from fastapi_app.services.notification_service import publish_stock_event
        await publish_stock_event(event_type, data)
    except (RuntimeError, OSError, ValueError):
        logger.warning("事件发布失败: %s", event_type, exc_info=True)


async def _get_redis_client():
    try:
        from fastapi_app.services.notification_service import _get_async_redis_client
        return await _get_async_redis_client()
    except (ImportError, OSError, ValueError):
        return None


def _write_audit_log(db: AsyncSession, *, batch_no: str, action: str, order_ids: list[int], user: User, old_value: str | None = None, new_value: str | None = None, detail: str | None = None):
    log = OrderBatchAuditLog(
        batch_no=batch_no,
        action=action,
        order_ids=json.dumps(order_ids),
        operator_id=user.id,
        operator_name=user.username,
        old_value=old_value,
        new_value=new_value,
        detail=detail,
    )
    db.add(log)


async def get_whitelist(db: AsyncSession) -> list[str]:
    redis = await _get_redis_client()
    if redis:
        try:
            cached = await redis.get(_WHITELIST_CACHE_KEY)
            if cached:
                return json.loads(cached)
        except (OSError, ValueError):
            logger.warning("白名单缓存读取失败", exc_info=True)

    result = await db.execute(
        select(OrderSyncConfig.config_value).where(OrderSyncConfig.config_key == "order_batch_whitelist")
    )
    row = result.scalar_one_or_none()
    customers = json.loads(row) if row else []

    if redis and customers:
        with contextlib.suppress(OSError, ValueError):
            await redis.setex(_WHITELIST_CACHE_KEY, _WHITELIST_TTL, json.dumps(customers, ensure_ascii=False))

    return customers


async def set_whitelist(db: AsyncSession, customers: list[str], user_id: int):
    value = json.dumps(customers, ensure_ascii=False)
    result = await db.execute(
        select(OrderSyncConfig).where(OrderSyncConfig.config_key == "order_batch_whitelist")
    )
    config = result.scalar_one_or_none()
    if config:
        config.config_value = value
        config.updated_by_id = user_id
        config.updated_at = datetime.now()
    else:
        db.add(OrderSyncConfig(config_key="order_batch_whitelist", config_value=value, description="订单批次号白名单客户"))

    redis = await _get_redis_client()
    if redis:
        with contextlib.suppress(OSError):
            await redis.delete(_WHITELIST_CACHE_KEY)


async def is_whitelisted(db: AsyncSession, customer: str) -> bool:
    whitelist = await get_whitelist(db)
    return customer in whitelist





async def get_batch_query_list(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 50,
    batch_no: str | None = None,
    status: str | None = None,
    customer: str | None = None,
    keyword: str | None = None,
) -> dict:
    whitelist = await get_whitelist(db)

    stmt = select(Order).options(joinedload(Order.product)).where(
        Order.is_deleted.isnot(True),
    )

    # 白名单非空时仅显示白名单客户；为空时显示所有客户
    if whitelist:
        stmt = stmt.where(Order.customer.in_(whitelist))

    if batch_no:
        stmt = stmt.where(Order.batch_no == batch_no)
    if status:
        stmt = stmt.where(Order.status == status)
    if customer:
        stmt = stmt.where(Order.customer == customer)
    if keyword:
        kw = f"%{escape_like(keyword)}%"
        stmt = stmt.join(Product, Order.product_id == Product.id).where(
            or_(Order.order_no.ilike(kw), Product.name.ilike(kw), Product.barcode.ilike(kw))
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Order.order_date.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(stmt)
    orders = result.unique().scalars().all()

    order_ids = [o.id for o in orders]

    stockout_data = {}
    if order_ids:
        stockout_result = await db.execute(
            select(
                StockOut.order_id,
                StockOut.stockin_id,
                func.sum(StockOut.quantity - StockOut.returned_quantity),
            )
            .where(StockOut.order_id.in_(order_ids))
            .group_by(StockOut.order_id, StockOut.stockin_id)
        )
        for order_id, stockin_id, qty in stockout_result:
            if qty is None:
                continue
            if order_id not in stockout_data:
                stockout_data[order_id] = {'deducted_qty': 0, 'shipped_qty': 0}
            if stockin_id is not None:
                stockout_data[order_id]['deducted_qty'] += int(qty)
            else:
                stockout_data[order_id]['shipped_qty'] += int(qty)

    from fastapi_app.shared_models.order import compute_status_from_stockouts

    items = []
    for o in orders:
        sd = stockout_data.get(o.id, {'deducted_qty': 0, 'shipped_qty': 0})
        computed_status = compute_status_from_stockouts(o, sd['deducted_qty'], sd['shipped_qty'])
        base_data = OrderSerializer.serialize(o, OrderSerializer.BATCH_CONFIG)
        base_data.update({
            'product_barcode': o.product.barcode if o.product else None,
            'deducted_qty': sd['deducted_qty'],
            'shipped_qty': sd['shipped_qty'],
            'computed_status': computed_status,
        })
        items.append(base_data)

    return {'items': items, 'total': total}


async def get_batch_orders(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 50,
    batch_no: str | None = None,
    status: str | None = None,
    customer: str | None = None,
    keyword: str | None = None,
) -> dict:
    whitelist = await get_whitelist(db)
    if not whitelist:
        return {'items': [], 'total': 0}

    stmt = select(Order).options(joinedload(Order.product)).where(
        Order.customer.in_(whitelist),
        Order.status != '批次已完成',
        Order.is_deleted.isnot(True),
    )

    if batch_no:
        stmt = stmt.where(Order.batch_no == batch_no)
    if status:
        stmt = stmt.where(Order.status == status)
    if customer:
        stmt = stmt.where(Order.customer == customer)
    if keyword:
        kw = f"%{escape_like(keyword)}%"
        stmt = stmt.join(Product, Order.product_id == Product.id).where(
            or_(Order.order_no.ilike(kw), Product.name.ilike(kw), Product.barcode.ilike(kw))
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Order.order_date.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(stmt)
    orders = result.unique().scalars().all()

    return {'items': [OrderSerializer.serialize(o, OrderSerializer.BATCH_CONFIG) for o in orders], 'total': total}


async def get_batch_history(
    db: AsyncSession,
    *,
    page: int = 1,
    per_page: int = 50,
    batch_no: str | None = None,
    customer: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    whitelist = await get_whitelist(db)
    if not whitelist:
        return {'items': [], 'total': 0}

    stmt = select(Order).options(joinedload(Order.product), joinedload(Order.batch_completed_by)).where(
        Order.customer.in_(whitelist),
        Order.status == '批次已完成',
        Order.is_deleted.isnot(True),
    )

    if batch_no:
        stmt = stmt.where(Order.batch_no == batch_no)
    if customer:
        stmt = stmt.where(Order.customer == customer)
    if date_from:
        stmt = stmt.where(Order.batch_completed_at >= date_from)
    if date_to:
        stmt = stmt.where(Order.batch_completed_at <= date_to)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Order.batch_completed_at.desc()).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(stmt)
    orders = result.unique().scalars().all()

    items = []
    for o in orders:
        d = OrderSerializer.serialize(o, OrderSerializer.BATCH_CONFIG)
        d['batch_completed_by'] = o.batch_completed_by.username if o.batch_completed_by else None
        items.append(d)

    return {'items': items, 'total': total}


async def update_batch_no(
    db: AsyncSession,
    *,
    order_id: int,
    batch_no: str | None,
    sync_same_batch: bool,
    user: User,
) -> dict:
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise ValueError(f"订单不存在: {order_id}")

    old_batch_no = order.batch_no
    updated_ids = [order_id]
    order.batch_no = batch_no

    if sync_same_batch and old_batch_no and old_batch_no != batch_no:
        sync_stmt = update(Order).where(
            Order.batch_no == old_batch_no,
            Order.id != order_id,
            Order.status != '批次已完成',
            Order.is_deleted.isnot(True),
        ).values(batch_no=batch_no)
        sync_result = await db.execute(sync_stmt)
        if sync_result.rowcount > 0:
            sync_ids_result = await db.execute(
                select(Order.id).where(
                    Order.batch_no == batch_no,
                    Order.id != order_id,
                    Order.is_deleted.isnot(True),
                )
            )
            updated_ids = [order_id] + list(sync_ids_result.scalars().all())

    effective_batch = batch_no or old_batch_no or ''
    _write_audit_log(
        db, batch_no=effective_batch, action='batch_number_change',
        order_ids=updated_ids, user=user,
        old_value=old_batch_no, new_value=batch_no,
    )
    await db.flush()

    await _safe_publish_event("batch_no_updated", {"batch_no": effective_batch, "order_ids": updated_ids})
    return {'updated_count': len(updated_ids)}


async def batch_assign(
    db: AsyncSession,
    *,
    order_ids: list[int],
    batch_no: str,
    user: User,
) -> dict:
    whitelist = await get_whitelist(db)
    stmt = select(Order).where(Order.id.in_(order_ids), Order.is_deleted.isnot(True))
    result = await db.execute(stmt)
    orders = result.scalars().all()

    if len(orders) != len(order_ids):
        raise ValueError("部分订单不存在")

    non_whitelisted = [o.customer for o in orders if o.customer not in whitelist]
    if non_whitelisted:
        raise ValueError(f"以下客户不在白名单中: {', '.join(set(non_whitelisted))}")

    for o in orders:
        o.batch_no = batch_no

    _write_audit_log(
        db, batch_no=batch_no, action='batch_assign',
        order_ids=order_ids, user=user,
        new_value=batch_no,
    )
    await db.flush()

    await _safe_publish_event("batch_no_updated", {"batch_no": batch_no, "order_ids": order_ids})
    return {'updated_count': len(orders)}


async def complete_batch(
    db: AsyncSession,
    *,
    batch_no: str,
    user: User,
) -> dict:
    stmt = select(Order).where(
        Order.batch_no == batch_no,
        Order.status != '批次已完成',
        Order.is_deleted.isnot(True),
    ).with_for_update()
    result = await db.execute(stmt)
    orders = result.scalars().all()

    if not orders:
        raise ValueError(f"批次 {batch_no} 没有可完成的订单")

    now = datetime.now()
    completed = []
    failed_orders = []

    from fastapi_app.services.order_service import compute_order_status_from_db

    for o in orders:
        # 批次完成仅适用于已出货的订单
        if o.status != '已出货':
            failed_orders.append({'id': o.id, 'order_no': o.order_no, 'status': o.status})
            continue
        o.batch_completed_at = now
        o.batch_completed_by_id = user.id
        o.status = await compute_order_status_from_db(db, o)
        completed.append(o)

    _write_audit_log(
        db, batch_no=batch_no, action='batch_complete',
        order_ids=[o.id for o in completed], user=user,
        detail=f"完成{len(completed)}单, 失败{len(failed_orders)}单",
    )
    await db.flush()

    await _safe_publish_event("batch_completed", {
        "batch_no": batch_no,
        "completed_count": len(completed),
        "failed_count": len(failed_orders),
    })

    return {
        'completed_count': len(completed),
        'failed_orders': failed_orders,
    }
