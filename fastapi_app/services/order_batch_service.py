"""订单批次号管理服务层

TODO(multi-sku-order): 本模块 keyword 搜索通过 JOIN Product, Order.product_id == Product.id
按首 item 产品名/barcode 过滤，多 SKU 下无法匹配非首 item 的产品。待后续 spec 改造为
JOIN OrderItem。当前依赖 Task 3 设置的兼容值。
"""
import contextlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, literal, nullslast, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

# event_bus 迁移说明（暂保留，不迁移至 domain_events）：
# event_bus.safe_publish_event 承担 WebSocket 广播 + FCM 推送（经 notification_service），
# 本文件发布的 "batch_no_updated" / "batch_completed" 为任意字符串事件名，
# 而 domain_events.publish_with_retry 需要 DomainEventType 枚举值（无对应 batch 事件），
# 且不具备 WS/FCM 实时通知能力——强行迁移会丢失前端实时推送，行为不等价。
from fastapi_app.core.event_bus import safe_publish_event as _safe_publish_event
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.serializers.order_serializer import OrderSerializer
from fastapi_app.shared_models import Order, OrderBatchAuditLog, OrderSyncConfig, Product, StockIn, StockOut, User

logger = logging.getLogger(__name__)

_WHITELIST_CACHE_KEY = "order_batch:whitelist"
_WHITELIST_TTL = 300


async def _get_redis_client():
    """获取模块级共享 Redis 客户端（连接池管理，无需手动关闭）"""
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
        config.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
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

    # ---- SQL 层 UNION ALL 分页 ----
    # 修复：此前订单/备货两支各 LIMIT 5000 后内存合并排序，任一支超 5000 条即被截断，
    # 导致分页窗口失真。现改为两支仅投影（排序日期 + 类型标记 + 主键），由数据库
    # UNION ALL 统一 ORDER BY + OFFSET/LIMIT 确定页内记录，再按主键回表序列化，
    # 过滤条件、字段映射与响应结构均与原实现保持一致。

    # 支 1：订单（过滤条件与原实现逐条一致）
    order_branch = select(
        Order.order_date.label('sort_date'),
        literal('order').label('record_type'),
        Order.id.label('record_id'),
    ).where(Order.is_deleted.isnot(True))

    if whitelist:
        order_branch = order_branch.where(Order.customer.in_(whitelist))
    if batch_no:
        order_branch = order_branch.where(Order.batch_no == batch_no)
    if status:
        order_branch = order_branch.where(Order.status == status)
    if customer:
        order_branch = order_branch.where(Order.customer == customer)
    if keyword:
        kw = f"%{escape_like(keyword)}%"
        order_branch = order_branch.join(Product, Order.product_id == Product.id).where(
            or_(Order.order_no.ilike(kw), Product.name.ilike(kw), Product.barcode.ilike(kw))
        )

    # 支 2：备货（无 is_deleted/batch_no/status 过滤，与原实现一致）
    stockin_branch = select(
        StockIn.stockin_date.label('sort_date'),
        literal('stockin').label('record_type'),
        StockIn.id.label('record_id'),
    )

    if whitelist:
        stockin_branch = stockin_branch.where(StockIn.customer.in_(whitelist))
    if customer:
        stockin_branch = stockin_branch.where(StockIn.customer == customer)
    if keyword:
        kw = f"%{escape_like(keyword)}%"
        stockin_branch = stockin_branch.join(Product, StockIn.product_id == Product.id).where(
            or_(StockIn.stockin_no.ilike(kw), Product.name.ilike(kw), Product.barcode.ilike(kw))
        )

    # total = 两支各自 COUNT 之和（复用同一分支查询，过滤条件绝对一致，不受分页影响）
    order_total = int((await db.execute(
        select(func.count()).select_from(order_branch.subquery())
    )).scalar() or 0)
    stockin_total = int((await db.execute(
        select(func.count()).select_from(stockin_branch.subquery())
    )).scalar() or 0)
    total = order_total + stockin_total

    # UNION ALL 外层统一排序分页：
    # - sort_date DESC NULLS LAST（与原内存排序"空日期排最后"一致）
    # - 并列时 record_type 升序使订单在前（与原稳定排序"orders 先于 stockins"一致）、
    #   record_id DESC 保证同键时结果稳定可复现
    union_sq = order_branch.union_all(stockin_branch).subquery()
    page_rows = (await db.execute(
        select(union_sq.c.record_type, union_sq.c.record_id)
        .order_by(
            union_sq.c.sort_date.desc().nullslast(),
            union_sq.c.record_type.asc(),
            union_sq.c.record_id.desc(),
        )
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).all()

    page_order_ids = [rid for rtype, rid in page_rows if rtype == 'order']
    page_stockin_ids = [rid for rtype, rid in page_rows if rtype == 'stockin']

    # ---- 订单回表序列化（仅取页内记录，字段映射与原实现一致）----
    serialized_orders: dict[int, dict] = {}
    if page_order_ids:
        orders = (await db.execute(
            select(Order).options(joinedload(Order.product)).where(Order.id.in_(page_order_ids))
        )).unique().scalars().all()

        stockout_data = {}
        stockout_result = await db.execute(
            select(
                StockOut.order_id,
                StockOut.stockin_id,
                func.sum(StockOut.quantity - StockOut.returned_quantity),
            )
            .where(StockOut.order_id.in_(page_order_ids))
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

        for o in orders:
            sd = stockout_data.get(o.id, {'deducted_qty': 0, 'shipped_qty': 0})
            computed_status = compute_status_from_stockouts(o, sd['deducted_qty'], sd['shipped_qty'])
            base_data = OrderSerializer.serialize(o, OrderSerializer.BATCH_CONFIG)
            base_data.update({
                'product_barcode': o.product.barcode if o.product else None,
                'deducted_qty': sd['deducted_qty'],
                'shipped_qty': sd['shipped_qty'],
                'computed_status': computed_status,
                'record_type': 'order',
            })
            serialized_orders[o.id] = base_data

    # ---- 备货回表序列化（字段映射与原实现一致）----
    serialized_stockins: dict[int, dict] = {}
    if page_stockin_ids:
        stockins = (await db.execute(
            select(StockIn).options(joinedload(StockIn.product)).where(StockIn.id.in_(page_stockin_ids))
        )).unique().scalars().all()
        for s in stockins:
            serialized_stockins[s.id] = {
                'id': s.id,
                'order_no': s.stockin_no,
                'customer': s.customer,
                'order_date': s.stockin_date.strftime('%Y-%m-%d %H:%M') if s.stockin_date else '',
                'product_id': s.product_id,
                'product_name': s.product.name if s.product else None,
                'product_barcode': s.product.barcode if s.product else None,
                'quantity': s.quantity,
                'deducted_qty': 0,
                'shipped_qty': 0,
                'status': None,
                'computed_status': None,
                'batch_no': None,
                'batch_completed_at': None,
                'is_locked': None,
                'record_type': 'stockin',
            }

    # ---- 按 UNION 页序组装，保持数据库排序结果 ----
    items = []
    for rtype, rid in page_rows:
        item = serialized_orders.get(rid) if rtype == 'order' else serialized_stockins.get(rid)
        if item is not None:
            items.append(item)

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
    result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
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
    stmt = select(Order).where(Order.id.in_(order_ids), Order.is_deleted.isnot(True)).with_for_update()
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

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    completed = []
    failed_orders = []

    from fastapi_app.services.order_utils import compute_order_status_from_db

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
