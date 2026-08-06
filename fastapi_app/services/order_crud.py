"""
订单 CRUD 操作

职责：订单的创建、更新、删除、查询、审批等核心业务逻辑。
从 order_service.py 拆分而来，保持函数签名不变。

TODO(multi-sku-order): 本模块多处直接读写 order.product_id/order.quantity/order.order_type/
order.country（update/delete/deduct 等函数）。多 SKU 模型下这些为首 item 兼容值，
完整改造涉及业务语义变更（如多 item 下修改/扣减/删除影响哪个 item），风险高，
待后续 spec 改造为遍历 order.items。当前依赖 Task 3 设置的兼容值。
"""
import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, desc, func, literal, select, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import CacheDomain, cache_result
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.event_bus import safe_publish_event as _safe_publish_event
from fastapi_app.core.exception_handler import INFRA_EXCEPTIONS
from fastapi_app.core.state_machine import can_transition
from fastapi_app.core.validators import validate_not_empty, validate_quantity_range
from fastapi_app.services import escape_like
from fastapi_app.services.enhanced_pagination import (
    OFFSET_THRESHOLD,
    optimized_count,
)
from fastapi_app.services.notification_service import StockEvent, dispatch_factory_notifications
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
    Order,
    OrderItem,
    OrderSyncRecord,
    Product,
    StockIn,
    StockOut,
    User,
)

logger = logging.getLogger(__name__)

# 持有后台任务引用，防止被 GC 回收（Python asyncio 官方推荐模式）
_pending_tasks: set[asyncio.Task] = set()


async def _safe_invalidate_purchase_cache():
    """安全清除采购中心缓存，失败仅记录警告"""
    await cache_mgr.invalidate(InvalidationStrategy.PURCHASE)


class PermissionDeniedError(Exception):
    """用户无权限执行此操作"""
    pass


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
    """解析日期字符串为 SQL 条件，失败返回 None。"""
    if not date_str:
        return None
    try:
        if is_end:
            end_dt = datetime.strptime(date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=UTC)
            return Order.order_date <= end_dt
        start_dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=UTC)
        return Order.order_date >= start_dt
    except ValueError:
        return None


def _build_order_filters(customer: str | None, product_id: int | None,
                         status: str | None, order_type: str | None,
                         start_date: str | None, end_date: str | None) -> list:
    """构建订单筛选条件列表（共用，避免 DRY 违反）。"""
    conditions = []
    if customer:
        conditions.append(Order.customer.like(f'%{escape_like(customer)}%'))
    if product_id:
        conditions.append(Order.product_id == product_id)
    if status:
        conditions.append(Order.status == status)
    if order_type:
        conditions.append(Order.order_type == order_type)
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
        return result.scalars().unique().all()

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
    orders = result.scalars().unique().all()
    # fallback: 并发删除可能导致游标偏移，回退到 OFFSET
    if orders:
        return orders
    logger.debug("keyset分页返回空，fallback到OFFSET分页")
    result = await db.execute(
        query.order_by(Order.order_date.desc())
        .offset(offset)
        .limit(per_page)
    )
    return result.scalars().unique().all()


def _serialize_orders(orders: list, deduct_map: dict) -> list:
    """序列化订单列表。"""
    return [
        OrderSerializer.serialize(
            order, OrderSerializer.LIST_CONFIG, deduct_quantity=deduct_map.get(order.id, 0)
        )
        for order in orders
    ]


@cache_result(
    key_prefix="orders:list",
    ttl=60,
    local_ttl=15,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:c{kwargs.get('customer', '')}:pid{kwargs.get('product_id', '')}:s{kwargs.get('status', '')}:ot{kwargs.get('order_type', '')}:sd{kwargs.get('start_date', '')}:ed{kwargs.get('end_date', '')}:f{kwargs.get('factory', '')}",
)
async def get_orders(db: AsyncSession, page: int = 1, per_page: int = 50,
                     customer: str | None = None, product_id: int | None = None,
                     status: str | None = None, order_type: str | None = None,
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
    conditions = _build_order_filters(customer, product_id, status, order_type, start_date, end_date)
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

    orders_data = _serialize_orders(orders, deduct_map)
    return {'items': orders_data, 'total': total, 'page': page, 'per_page': per_page}


@cache_result(
    key_prefix="orders:beile:list",
    ttl=60,
    local_ttl=15,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:c{kwargs.get('customer', '')}:f{kwargs.get('factory', '')}",
)
async def get_beile_orders_with_stockins(
    db: AsyncSession, *, page: int = 1, per_page: int = 50,
    customer: str | None = None, factory: str = '湖北',
) -> dict:
    """获取湖北工厂订单+备货合并列表。

    通过 UNION ALL 合并查询 Order（订单）和 StockIn（备货），
    按产品工厂筛选，确保订单和备货记录都能在同一列表中展示。

    参考 purchase_order_query.get_unprocessed_orders 的实现方案。
    """
    # ---- 构建 UNION ALL 子查询 ----
    # Order 部分：未删除订单，通过 order_item.product.factory 筛选
    order_part = select(
        literal('order').label('record_type'),
        Order.id.label('source_id'),
        Order.order_no.label('order_no'),
        Order.customer.label('customer'),
        Order.order_date.label('sort_date'),
    ).where(
        Order.is_deleted.isnot(True),
        Order.items.any(OrderItem.product.has(Product.factory == factory)),
    )
    if customer:
        order_part = order_part.where(Order.customer.like(f'%{escape_like(customer)}%'))

    # StockIn 部分：通过 product.factory 筛选
    stockin_part = select(
        literal('stockin').label('record_type'),
        StockIn.id.label('source_id'),
        StockIn.stockin_no.label('order_no'),
        StockIn.customer.label('customer'),
        StockIn.stockin_date.label('sort_date'),
    ).where(
        StockIn.product.has(Product.factory == factory),
    )
    if customer:
        stockin_part = stockin_part.where(StockIn.customer.like(f'%{escape_like(customer)}%'))

    unified = union_all(order_part, stockin_part).subquery()

    # ---- 1. COUNT 总数 ----
    count_result = await db.execute(select(func.count()).select_from(unified))
    total = count_result.scalar() or 0

    if total == 0:
        return {'items': [], 'total': 0, 'page': page, 'per_page': per_page}

    # ---- 2. 分页查询当前页 ----
    offset = (page - 1) * per_page
    page_result = await db.execute(
        select(
            unified.c.record_type,
            unified.c.source_id,
            unified.c.order_no,
            unified.c.customer,
            unified.c.sort_date,
        )
        .order_by(desc(unified.c.sort_date).nullslast())
        .limit(per_page)
        .offset(offset)
    )
    rows = page_result.all()

    if not rows:
        return {'items': [], 'total': total, 'page': page, 'per_page': per_page}

    # ---- 3. 按来源批量查询完整数据 ----
    order_ids = [r.source_id for r in rows if r.record_type == 'order']
    stockin_ids = [r.source_id for r in rows if r.record_type == 'stockin']

    orders_map: dict[int, Order] = {}
    if order_ids:
        order_result = await db.execute(
            select(Order)
            .options(
                joinedload(Order.product),
                selectinload(Order.items),
            )
            .where(Order.id.in_(order_ids))
        )
        for o in order_result.scalars().unique():
            orders_map[o.id] = o

    stockins_map: dict[int, StockIn] = {}
    if stockin_ids:
        stockin_result = await db.execute(
            select(StockIn)
            .options(joinedload(StockIn.product))
            .where(StockIn.id.in_(stockin_ids))
        )
        for s in stockin_result.scalars():
            stockins_map[s.id] = s

    # ---- 4. 构建 records（保持 SQL 排序顺序）----
    items: list[dict] = []
    for r in rows:
        if r.record_type == 'order':
            o = orders_map.get(r.source_id)
            if o:
                items.append(_build_beile_order_record(o, factory))
        else:
            s = stockins_map.get(r.source_id)
            if s:
                items.append(_build_beile_stockin_record(s, factory))

    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}


def _build_beile_order_record(order: Order, factory: str) -> dict:
    """构建湖北订单列表中的订单记录（含多 SKU）。"""
    items_data = [
        {
            'id': item.id,
            'product_id': item.product_id,
            'product_name': item.product_name,
            'product_barcode': item.product_barcode,
            'quantity': item.quantity,
            'order_type': item.order_type,
            'country': item.country or '',
            'deduct_quantity': item.deduct_quantity or 0,
            'note': item.note or '',
        }
        for item in (order.items or [])
    ]
    first_item = order.items[0] if order.items else None
    return {
        'id': order.id,
        'order_no': order.order_no,
        'customer': order.customer,
        'product_id': first_item.product_id if first_item else None,
        'product_name': first_item.product_name if first_item else None,
        'quantity': first_item.quantity if first_item else 0,
        'order_date': order.order_date.strftime('%Y-%m-%d %H:%M') if order.order_date else '',
        'record_type': 'order',
        'items': items_data,
        'factories': [factory],
    }


def _build_beile_stockin_record(stockin: StockIn, factory: str) -> dict:
    """构建湖北订单列表中的备货记录。"""
    product_name = stockin.product.name if stockin.product else None
    product_barcode = stockin.product.barcode if stockin.product else None
    items_data = [{
        'id': stockin.id,
        'product_id': stockin.product_id,
        'product_name': product_name,
        'product_barcode': product_barcode,
        'quantity': stockin.quantity,
        'order_type': stockin.order_type,
        'country': stockin.country or '',
        'deduct_quantity': 0,
        'note': stockin.note or '',
    }]
    return {
        'id': stockin.id,
        'order_no': stockin.stockin_no,
        'customer': stockin.customer,
        'product_id': stockin.product_id,
        'product_name': product_name,
        'quantity': stockin.quantity,
        'order_date': stockin.stockin_date.strftime('%Y-%m-%d %H:%M') if stockin.stockin_date else '',
        'record_type': 'stockin',
        'items': items_data,
        'factories': [factory],
    }


async def create_order(db: AsyncSession, product_id: int, quantity: int,
                       customer: str, note: str, current_user: User,
                       order_type: str = 'regular', country: str | None = None) -> dict:
    """
    创建订单

    业务规则：
    - 产品必须存在
    - 数量 > 0 且 <= 9999999
    - 客户名称不能为空
    - 创建订单记录及库存日志（不影响物理库存）
    - 定制订单必须填写国家名称
    """
    if order_type == 'custom' and not country:
        raise ValueError('定制订单必须填写国家名称')

    validate_quantity_range(quantity, "订单数量")

    product = await get_product_for_update(db, product_id)

    order_no = await _generate_order_number(db)

    async with db.begin_nested():
        order = Order(
            order_no=order_no,
            customer=customer,
            order_date=datetime.now(UTC).replace(tzinfo=None),  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
            product_id=product_id,
            quantity=quantity,
            note=note,
            status='待备货',
            order_type=order_type,
            country=country if order_type == 'custom' else None,
        )
        db.add(order)
        await db.flush()

        log = InventoryLog(
            product_id=product_id,
            change_type='订单',
            change_quantity=quantity,
            related_id=order_no,
            customer=customer,
            note=f'订单：{order_no}'
        )
        db.add(log)

        await db.flush()
    await db.refresh(order)
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
    # dashboard 缓存失效已移至 endpoint 层（事务提交后），此处不再重复
    logger.info(f'订单添加成功：{order_no}，客户：{customer}，产品：{product.name}，数量：{quantity}')

    await _safe_invalidate_purchase_cache()

    # 发布订单创建事件，通知前端实时刷新
    await _safe_publish_event(StockEvent.ORDER_CREATED, {
            'order_id': order.id,
            'order_no': order_no,
            'customer': customer,
            'product_name': product.name,
            'quantity': quantity,
        }, fcm_title="新订单已创建", fcm_body=f"订单 {order_no}，客户：{customer}，数量：{quantity}")

    return order.to_dict()


async def update_order(db: AsyncSession, order_id: int, quantity: int,
                       customer: str, note: str, current_user: User,
                       order_type: str | None = None, country: str | None = None) -> dict:
    result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = result.scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '编辑')

    if current_user.is_super:
        return await _update_order_directly(
            db, order, order_id, quantity, customer, note,
            current_user, order_type, country
        )
    else:
        return await _submit_edit_approval(
            db, order, order_id, quantity, customer, note, current_user
        )


async def _update_order_directly(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str,
    current_user: User, order_type: str | None,
    country: str | None,
) -> dict:
    validate_quantity_range(quantity, "订单数量")
    validate_not_empty(customer, "客户名称")
    # TODO(multi-sku-order): 读取/修改 order.quantity 在多 SKU 下语义变更（多 item 改哪个？），待后续 spec 改造为遍历 order.items；当前依赖兼容值。
    old_quantity = order.quantity
    _ = order.customer
    order.customer = customer
    order.quantity = quantity
    order.note = note
    if order_type is not None:
        order.order_type = order_type
    if country is not None:
        order.country = country if order_type != 'regular' else None

    if quantity != old_quantity:
        # TODO(multi-sku-order): order.product_id 在多 SKU 下为首 item 兼容值，库存调整需按 OrderItem 维度；待后续 spec 改造。
        product = await get_product_for_update(db, order.product_id)
        log = InventoryLog(
            product_id=order.product_id,
            change_type='订单修改',
            change_quantity=quantity - old_quantity,
            related_id=order.order_no,
            note=f'订单修改：{order.order_no}'
        )
        db.add(log)

    await db.flush()

    # Task 3.2: 派发工厂通知（order_updated）
    # 仅 flush 不 commit，与 _update_order_directly 事务模型一致；
    # 简单实现：传 changed_items=None，让 dispatch 遍历 order.items（内部 await 查询）。
    # 通知失败不应影响订单修改，捕获异常仅记录日志。
    try:
        await dispatch_factory_notifications(db, order, 'order_updated', None)
    except Exception as notify_err:
        logger.warning(
            "工厂通知派发失败 order_no=%s: %s", order.order_no, notify_err,
            exc_info=True,
        )

    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
    # dashboard 缓存失效已移至 endpoint 层（事务提交后）

    await _safe_invalidate_purchase_cache()

    logger.info(f'订单编辑成功：{order.order_no}，操作人：{current_user.username}')

    await _safe_publish_event(StockEvent.ORDER_UPDATED, {
        'order_id': order_id,
        'order_no': order.order_no,
        'customer': customer,
        'quantity': quantity,
    }, fcm_title="订单已更新", fcm_body=f"订单 {order.order_no} 信息已更新")

    return {'success': True, 'message': '订单编辑成功！', 'requires_approval': False}


async def _increase_deduction(
    db: AsyncSession, order: Order, diff: int,
) -> None:
    """增加抵扣：从可用备货中按 FIFO 扣除。

    Args:
        db: 异步会话
        order: 目标订单（已加行锁）
        diff: 需增加的抵扣量（正数）

    Raises:
        ValueError: 可用备货不足
    """
    from fastapi_app.shared_models import StockIn
    from fastapi_app.services.numbering import generate_stockout_number

    stockins_result = await db.execute(
        select(StockIn)
        .where(StockIn.product_id == order.product_id, StockIn.customer == order.customer)
        .order_by(StockIn.stockin_date.asc(), StockIn.id.asc())
        .with_for_update()
    )
    stockins = stockins_result.scalars().all()

    # 批量查询所有备货的已抵扣量（消除 N+1 查询）
    stockin_ids = [s.id for s in stockins]
    deducted_map: dict[int, int] = {}
    if stockin_ids:
        deducted_rows = await db.execute(
            select(StockOut.stockin_id, func.coalesce(func.sum(StockOut.quantity - StockOut.returned_quantity), 0))
            .where(StockOut.stockin_id.in_(stockin_ids))
            .group_by(StockOut.stockin_id)
        )
        deducted_map = dict(deducted_rows.all())

    # 循环外一次性锁定产品（消除重复行锁）
    product = await get_product_for_update(db, order.product_id)

    remaining = diff
    logs: list[InventoryLog] = []
    for stockin in stockins:
        if remaining <= 0:
            break
        already_deducted = int(deducted_map.get(stockin.id, 0))
        available = stockin.quantity - already_deducted
        if available <= 0:
            continue

        deduct_amount = min(remaining, available)
        stockout_no = await generate_stockout_number(db)
        stockout = StockOut(
            stockout_no=stockout_no,
            stockout_date=datetime.now(UTC).replace(tzinfo=None),
            product_id=stockin.product_id,
            quantity=deduct_amount,
            customer=order.customer,
            order_id=order.id,
            stockin_id=stockin.id,
            note=f'[订单抵扣]{order.order_no}'
        )
        db.add(stockout)

        # 更新产品库存（循环外已锁定，循环内直接修改）
        if product and deduct_amount > 0:
            product.current_stock -= deduct_amount

        logs.append(InventoryLog(
            product_id=order.product_id,
            change_type='订单抵扣',
            change_quantity=-deduct_amount,
            related_id=stockout_no,
            note=f'修改抵扣增加：订单{order.order_no}，备货{stockin.stockin_no}，数量{deduct_amount}'
        ))
        remaining -= deduct_amount

    if logs:
        db.add_all(logs)

    if remaining > 0:
        raise ValueError(f'可用备货不足，还需{remaining}件无法抵扣')


async def _decrease_deduction(
    db: AsyncSession, order: Order, order_id: int, reduce_amount: int,
) -> None:
    """减少抵扣：按时间倒序删除/减少已有的抵扣出库记录。

    Args:
        db: 异步会话
        order: 目标订单（已加行锁）
        order_id: 订单 ID
        reduce_amount: 需减少的抵扣量（正数）
    """
    stockouts_result = await db.execute(
        select(StockOut)
        .where(StockOut.order_id == order_id, StockOut.stockin_id.isnot(None))
        .order_by(StockOut.id.desc())
        .with_for_update()
    )
    deduction_stockouts = stockouts_result.scalars().all()

    # 循环外一次性锁定产品（消除重复行锁）
    product = await get_product_for_update(db, order.product_id)

    remaining = reduce_amount
    logs: list[InventoryLog] = []
    for stockout in deduction_stockouts:
        if remaining <= 0:
            break
        effective_qty = stockout.quantity - stockout.returned_quantity
        if effective_qty <= 0:
            continue

        if remaining >= effective_qty:
            # 整条删除
            remaining -= effective_qty
            if product:
                product.current_stock += effective_qty
            logs.append(InventoryLog(
                product_id=order.product_id,
                change_type='取消抵扣',
                change_quantity=effective_qty,
                related_id=stockout.stockout_no,
                note=f'修改抵扣减少：订单{order.order_no}，取消出库{stockout.stockout_no}，数量{effective_qty}'
            ))
            await db.delete(stockout)
        else:
            # 部分减少
            stockout.quantity -= remaining
            if product:
                product.current_stock += remaining
            logs.append(InventoryLog(
                product_id=order.product_id,
                change_type='取消抵扣',
                change_quantity=remaining,
                related_id=stockout.stockout_no,
                note=f'修改抵扣减少：订单{order.order_no}，减少出库{stockout.stockout_no}，数量{remaining}'
            ))
            remaining = 0

    if logs:
        db.add_all(logs)


async def update_deduct_quantity(
    db: AsyncSession, order_id: int, new_deduct_quantity: int, current_user: User,
) -> dict:
    """更新订单的抵扣备货数量。

    逻辑：
    - 查询当前抵扣量（StockOut where order_id=X and stockin_id IS NOT NULL）
    - 如果 new > current：增加抵扣（从可用备货中扣除）
    - 如果 new < current：减少抵扣（删除/减少已有的抵扣出库记录）
    - 如果 new == current：无变化
    """
    result = await db.execute(select(Order).where(Order.id == order_id).with_for_update())
    order = result.scalar_one_or_none()
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '修改抵扣')

    if new_deduct_quantity < 0:
        raise ValueError('抵扣数量不能为负数')

    # 查询当前抵扣量
    deduct_map = await _batch_deduct_quantities(db, [order_id])
    current_deduct = deduct_map.get(order_id, 0)

    if new_deduct_quantity == current_deduct:
        return {'success': True, 'message': '抵扣数量未变化', 'deduct_quantity': current_deduct}

    diff = new_deduct_quantity - current_deduct

    if diff > 0:
        await _increase_deduction(db, order, diff)
    else:  # diff < 0，减少抵扣
        await _decrease_deduction(db, order, order_id, abs(diff))

    # 更新订单状态
    order.status = await compute_order_status_from_db(db, order)

    await db.flush()
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER_AND_INVENTORY)
    await _safe_invalidate_purchase_cache()

    logger.info(f'订单抵扣修改：{order.order_no}，{current_deduct}->{new_deduct_quantity}，操作人：{current_user.username}')

    return {'success': True, 'message': '抵扣数量修改成功', 'deduct_quantity': new_deduct_quantity}


async def _submit_edit_approval(
    db: AsyncSession, order: Order, order_id: int,
    quantity: int, customer: str, note: str, current_user: User,
) -> dict:
    validate_not_empty(customer, "客户名称")
    if quantity is not None:
        validate_quantity_range(quantity, "订单数量")

    await _ensure_no_pending_request(db, order_id, current_user, '编辑')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE

    operation_data = {
        'customer': customer,
        'quantity': quantity,
        'note': note,
        'original_customer': order.customer,
        'original_quantity': order.quantity,
        'original_note': order.note or ''
    }

    approval_request = ApprovalRequest(
        order_id=order_id,
        requester_id=current_user.id,
        operation_type=ApprovalRequest.OPERATION_EDIT,
        operation_data=json.dumps(operation_data, ensure_ascii=False),
        status=ApprovalRequest.STATUS_PENDING,
        lock_time=datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.flush()
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
    await cache_mgr.invalidate_dashboard()
    logger.info(f'订单编辑审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交编辑审批请求，请等待管理员审批！', 'requires_approval': True}


async def delete_order(db: AsyncSession, order_id: int, current_user: User) -> dict:
    order = await db.get(Order, order_id, options=[joinedload(Order.product)])
    if not order or order.is_deleted:
        raise ValueError('订单不存在')

    await _check_order_lock(db, order_id, order, current_user, '删除')

    if current_user.is_super:
        return await _delete_order_directly(db, order, order_id, current_user)
    else:
        return await _submit_delete_approval(db, order, order_id, current_user)


async def _delete_order_directly(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    product = await get_product_for_update(db, order.product_id)

    result = await db.execute(
        select(StockOut).where(StockOut.order_id == order.id)
    )
    order_stockouts = result.scalars().all()
    total_deducted = sum(so.quantity - so.returned_quantity for so in order_stockouts)

    # 批量构建抵扣回滚日志，消除循环内逐条 add 的 N+1 开销
    rollback_logs = []
    for stockout in order_stockouts:
        net_qty = stockout.quantity - stockout.returned_quantity
        if net_qty <= 0:
            continue
        rollback_logs.append(InventoryLog(
            product_id=order.product_id,
            change_type='抵扣回滚',
            change_quantity=net_qty,
            related_id=order.order_no,
            note=f'订单删除回滚抵扣：{order.order_no}，恢复备货ID {stockout.stockin_id if stockout.stockin_id else "未知"} 的 {net_qty} 件'
        ))
    if rollback_logs:
        db.add_all(rollback_logs)

    net_change = total_deducted
    if product.current_stock + net_change < 0:
        raise ValueError(f'删除订单将导致库存为负数（产品：{product.name}，当前库存：{product.current_stock}，净变化：{net_change:+d}）')
    product.current_stock += net_change

    log = InventoryLog(
        product_id=order.product_id,
        change_type='订单删除',
        change_quantity=total_deducted,
        related_id=order.order_no,
        note=f'订单删除：{order.order_no}，订单数量：{order.quantity}，抵扣回滚数量：{total_deducted}'
    )
    db.add(log)

    await db.execute(delete(StockOut).where(StockOut.order_id == order.id))
    await db.execute(delete(OrderSyncRecord).where(OrderSyncRecord.source_order_id == order_id))

    result = await db.execute(
        select(ApprovalRequest.id).where(ApprovalRequest.order_id == order_id)
    )
    approval_ids = [row[0] for row in result.all()]
    if approval_ids:
        await db.execute(delete(ApprovalLog).where(ApprovalLog.approval_request_id.in_(approval_ids)))
    await db.execute(delete(ApprovalRequest).where(ApprovalRequest.order_id == order_id))

    deleted_order_no = order.order_no
    order.is_deleted = True
    order.deleted_at = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    order.deleted_by_id = current_user.id

    await db.flush()
    try:
        await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
        # dashboard 缓存失效已移至 endpoint 层（事务提交后）
    except INFRA_EXCEPTIONS as e:
        logger.warning('缓存清除失败: %s', e)

    await _safe_invalidate_purchase_cache()

    # StockEvent.ORDER_DELETED：仅 WebSocket/FCM 通知（不查询数据库，可在提交前调度）
    # 领域事件 ORDER_DELETED 由 endpoint 层在事务提交后直接发布（order.py）
    task = asyncio.create_task(_safe_publish_event(StockEvent.ORDER_DELETED, {
        'order_id': order_id,
        'order_no': deleted_order_no,
    }, fcm_title="订单已删除", fcm_body=f"订单 {deleted_order_no} 已被删除"))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)

    logger.info(f'订单删除成功：{deleted_order_no}，操作人：{current_user.username}，抵扣回滚：{total_deducted}')
    return {'success': True, 'message': f'订单删除成功！抵扣回滚数量：{total_deducted}', 'requires_approval': False}


async def _submit_delete_approval(
    db: AsyncSession, order: Order, order_id: int, current_user: User,
) -> dict:
    await _ensure_no_pending_request(db, order_id, current_user, '删除')

    order.is_locked = True
    order.locked_by_id = current_user.id
    order.lock_time = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE

    operation_data = {
        'order_no': order.order_no,
        'customer': order.customer,
        'quantity': order.quantity,
        'product_name': order.product.name if order.product else '',
        'note': order.note or ''
    }

    approval_request = ApprovalRequest(
        order_id=order_id,
        requester_id=current_user.id,
        operation_type=ApprovalRequest.OPERATION_DELETE,
        operation_data=json.dumps(operation_data, ensure_ascii=False),
        status=ApprovalRequest.STATUS_PENDING,
        lock_time=datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    )
    db.add(approval_request)
    await db.flush()

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CREATE, current_user, {'operation_data': operation_data})

    await db.flush()
    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
    await cache_mgr.invalidate_dashboard()
    logger.info(f'订单删除审批请求已提交：{order.order_no}，申请人：{current_user.username}')
    return {'success': True, 'message': '已提交删除审批请求，请等待管理员审批！', 'requires_approval': True}


async def cancel_approval(db: AsyncSession, approval_id: int, current_user: User) -> None:
    approval_request = await db.get(ApprovalRequest, approval_id)
    if not approval_request:
        raise ValueError('审批请求不存在')

    if approval_request.requester_id != current_user.id and not current_user.is_super:
        raise PermissionDeniedError('您没有权限取消此审批请求')

    if not can_transition(approval_request.status, 'cancel'):
        raise ValueError(f'该审批请求当前状态为"{approval_request.status}"，无法取消')

    order = await db.get(Order, approval_request.order_id)
    if order and not order.is_deleted:
        order.is_locked = False
        order.locked_by_id = None
        order.lock_time = None

    approval_request.status = ApprovalRequest.STATUS_CANCELLED

    await _create_approval_log_obj(approval_request, ApprovalLog.ACTION_CANCEL, current_user, {'reason': '用户主动取消'})

    await db.flush()


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


# ==================== 内部辅助函数 ====================

async def _check_order_lock(db: AsyncSession, order_id: int, order: Order,
                             current_user: User, action: str) -> None:
    if not (order.is_locked and order.locked_by_id != current_user.id):
        return
    result = await db.execute(
        select(ApprovalRequest).options(
            joinedload(ApprovalRequest.requester)
        ).where(
            ApprovalRequest.order_id == order_id,
            ApprovalRequest.status == ApprovalRequest.STATUS_PENDING,
        )
    )
    pending = result.unique().scalar_one_or_none()
    if pending:
        raise ValueError(f'该订单正在等待审批（申请人：{pending.requester.username}），暂时无法{action}！')
    raise ValueError(f'该订单已被其他用户锁定，暂时无法{action}！')


async def _ensure_no_pending_request(db: AsyncSession, order_id: int,
                                      current_user: User, action: str) -> None:
    result = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.order_id == order_id,
            ApprovalRequest.requester_id == current_user.id,
            ApprovalRequest.status == ApprovalRequest.STATUS_PENDING,
        )
    )
    if result.scalar_one_or_none():
        raise ValueError(f'您已提交过该订单的{action}审批请求，请等待管理员审批！')


async def _generate_order_number(db: AsyncSession) -> str:
    from fastapi_app.services.numbering import generate_order_number
    return await generate_order_number(db)


async def _create_approval_log_obj(approval_request: ApprovalRequest, action: str,
                                    actor: User, details: dict | None = None) -> None:
    from sqlalchemy.orm import object_session

    from fastapi_app.services.approval_log_service import create_approval_log
    session = object_session(approval_request)
    if session:
        await create_approval_log(session, approval_request, action, actor, details)
