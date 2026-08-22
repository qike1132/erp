"""
湖北订单+备货合并查询与确认（beile-order 页面）

从 order_crud.py 按职责拆出，行为与原实现完全一致。
"""
import logging
from datetime import UTC, datetime

from sqlalchemy import desc, func, literal, select, union_all, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.cache import CacheDomain, cache_result
from fastapi_app.core.cache_invalidation import InvalidationStrategy, cache_mgr
from fastapi_app.core.exceptions import NotFoundError
from fastapi_app.services import escape_like
from fastapi_app.services.notification_service import BEILE_UNCONFIRMED_TYPE
from fastapi_app.services.order._common import _safe_invalidate_purchase_cache
from fastapi_app.shared_models import Notification, Order, OrderItem, Product, StockIn, User

logger = logging.getLogger(__name__)
def _build_beile_unified_query(confirm_condition, unconfirmed_only, customer, factory):
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
    if confirm_condition is not None:
        order_part = order_part.where(confirm_condition)
    if customer:
        order_part = order_part.where(Order.customer.like(f'%{escape_like(customer)}%'))

    # StockIn 部分：通过 product.factory 筛选（备货同样参与确认状态筛选）
    stockin_part = select(
        literal('stockin').label('record_type'),
        StockIn.id.label('source_id'),
        StockIn.stockin_no.label('order_no'),
        StockIn.customer.label('customer'),
        StockIn.stockin_date.label('sort_date'),
    ).where(
        StockIn.product.has(Product.factory == factory),
    )
    if confirm_condition is not None:
        stockin_part = stockin_part.where(
            StockIn.confirmed_at.is_(None) if unconfirmed_only else StockIn.confirmed_at.isnot(None)
        )
    if customer:
        stockin_part = stockin_part.where(StockIn.customer.like(f'%{escape_like(customer)}%'))

    parts = [order_part, stockin_part]
    return union_all(*parts).subquery()


async def _fetch_beile_records_by_ids(db: AsyncSession, order_ids: list[int], stockin_ids: list[int]) -> tuple:
    orders_map: dict[int, Order] = {}
    if order_ids:
        order_result = await db.execute(
            select(Order)
            .options(
                joinedload(Order.product),
                joinedload(Order.confirmed_by),
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
            .options(
                joinedload(StockIn.product),
                joinedload(StockIn.confirmed_by),
            )
            .where(StockIn.id.in_(stockin_ids))
        )
        for s in stockin_result.scalars():
            stockins_map[s.id] = s

    return orders_map, stockins_map


@cache_result(
    key_prefix="orders:beile:list",
    ttl=60,
    local_ttl=15,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 50)}:c{kwargs.get('customer', '')}:f{kwargs.get('factory', '')}:cs{kwargs.get('confirm_status', '')}",
)
async def get_beile_orders_with_stockins(
    db: AsyncSession, *, page: int = 1, per_page: int = 50,
    customer: str | None = None, factory: str = '湖北',
    confirm_status: str | None = None,
) -> dict:
    """获取湖北工厂订单+备货合并列表。

    通过 UNION ALL 合并查询 Order（订单）和 StockIn（备货），
    按产品工厂筛选，确保订单和备货记录都能在同一列表中展示。

    湖北确认流程筛选（订单与备货对齐，均按各自表的 confirmed_at 过滤）：
    - confirm_status='unconfirmed'：仅返回 confirmed_at IS NULL 的订单+备货
    - confirm_status='confirmed'：仅返回已确认（confirmed_at 非空）的订单+备货
    - 其他取值（含 None）不生效，返回完整订单+备货列表

    参考 purchase_order_query.get_unprocessed_orders 的实现方案。
    """
    # 确认状态条件：订单与备货均参与确认流程
    confirm_condition = None
    unconfirmed_only = None
    if confirm_status == 'unconfirmed':
        confirm_condition = Order.confirmed_at.is_(None)
        unconfirmed_only = True
    elif confirm_status == 'confirmed':
        confirm_condition = Order.confirmed_at.isnot(None)
        unconfirmed_only = False

    unified = _build_beile_unified_query(confirm_condition, unconfirmed_only, customer, factory)

    # ---- 0. 未确认湖北记录总数（订单+备货，列表顶部横幅使用） ----
    # 全局统计（不受分页/客户筛选影响），统计 confirmed_at IS NULL 的订单与备货
    unconfirmed_orders_result = await db.execute(
        select(func.count(Order.id)).where(
            Order.is_deleted.isnot(True),
            Order.confirmed_at.is_(None),
            Order.items.any(OrderItem.product.has(Product.factory == factory)),
        )
    )
    unconfirmed_stockins_result = await db.execute(
        select(func.count(StockIn.id)).where(
            StockIn.confirmed_at.is_(None),
            StockIn.product.has(Product.factory == factory),
        )
    )
    unconfirmed_count = (unconfirmed_orders_result.scalar() or 0) + (unconfirmed_stockins_result.scalar() or 0)

    # ---- 1. COUNT 总数 ----
    count_result = await db.execute(select(func.count()).select_from(unified))
    total = count_result.scalar() or 0

    if total == 0:
        return {'items': [], 'total': 0, 'page': page, 'per_page': per_page,
                'unconfirmed_count': unconfirmed_count}

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
        return {'items': [], 'total': total, 'page': page, 'per_page': per_page,
                'unconfirmed_count': unconfirmed_count}

    # ---- 3. 按来源批量查询完整数据 ----
    order_ids = [r.source_id for r in rows if r.record_type == 'order']
    stockin_ids = [r.source_id for r in rows if r.record_type == 'stockin']

    orders_map, stockins_map = await _fetch_beile_records_by_ids(db, order_ids, stockin_ids)

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

    return {'items': items, 'total': total, 'page': page, 'per_page': per_page,
            'unconfirmed_count': unconfirmed_count}


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
        'product_image': first_item.product.image if first_item and first_item.product else None,
        'quantity': first_item.quantity if first_item else 0,
        'order_date': order.order_date.strftime('%Y-%m-%d %H:%M') if order.order_date else '',
        'record_type': 'order',
        'items': items_data,
        'factories': [factory],
        # 湖北订单确认状态：confirmed_at IS NULL 视为「未确认订单」
        'confirmed': order.confirmed_at is not None,
        'confirmed_at': order.confirmed_at.strftime('%Y-%m-%d %H:%M') if order.confirmed_at else '',
        'confirmed_by': order.confirmed_by.username if order.confirmed_by else None,
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
        'product_image': stockin.product.image if stockin.product else None,
        'quantity': stockin.quantity,
        'order_date': stockin.stockin_date.strftime('%Y-%m-%d %H:%M') if stockin.stockin_date else '',
        'record_type': 'stockin',
        'items': items_data,
        'factories': [factory],
        # 湖北备货确认状态（与订单确认流程对齐）：confirmed_at IS NULL 视为「未确认备货」
        'confirmed': stockin.confirmed_at is not None,
        'confirmed_at': stockin.confirmed_at.strftime('%Y-%m-%d %H:%M') if stockin.confirmed_at else '',
        'confirmed_by': stockin.confirmed_by.username if stockin.confirmed_by else None,
    }


async def confirm_beile_order(db: AsyncSession, order_id: int, current_user: User) -> dict:
    """确认湖北订单（beile-order 页面）。

    业务规则：
    - 仅允许确认 factory=湖北 的订单，与其他地区（东莞等）订单独立隔离：
      非湖北工厂订单通过本接口一律返回 404，防止跨区域串改。
    - 幂等：订单已确认时直接返回成功，不重复记录确认人。
    - 只写入 confirmed_at / confirmed_by_id，不影响 order.status
      （派生状态机不受确认流程干扰）。
    """
    result = await db.execute(
        select(Order)
        .where(
            Order.id == order_id,
            Order.is_deleted.isnot(True),
            Order.items.any(OrderItem.product.has(Product.factory == '湖北')),
        )
        .with_for_update()
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError('订单不存在或非湖北工厂订单')

    if order.confirmed_at is not None:
        logger.info('湖北订单重复确认（幂等）：order_id=%s，操作人：%s', order_id, current_user.username)
        return {'success': True, 'message': '订单已确认', 'already_confirmed': True}

    order.confirmed_at = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    order.confirmed_by_id = current_user.id
    await db.flush()

    # 该订单的「未确认提醒」通知标记为已读，确认后不再残留未读待办
    await db.execute(
        update(Notification)
        .where(
            Notification.related_order_id == order.id,
            Notification.type == BEILE_UNCONFIRMED_TYPE,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )

    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
    await _safe_invalidate_purchase_cache()

    logger.info('湖北订单确认成功：order_no=%s，操作人：%s', order.order_no, current_user.username)
    return {'success': True, 'message': '订单已确认', 'already_confirmed': False}


async def confirm_beile_stockin(db: AsyncSession, stockin_id: int, current_user: User) -> dict:
    """确认湖北备货（beile-order 页面，与订单确认流程对齐）。

    业务规则：
    - 仅允许确认 factory=湖北 的备货记录，与其他地区独立隔离：
      非湖北工厂备货通过本接口一律返回 404，防止跨区域串改。
    - 幂等：备货已确认时直接返回成功，不重复记录确认人。
    - 只写入 confirmed_at / confirmed_by_id，不影响库存业务数据。
    """
    result = await db.execute(
        select(StockIn)
        .where(
            StockIn.id == stockin_id,
            StockIn.product.has(Product.factory == '湖北'),
        )
        .with_for_update()
    )
    stockin = result.scalar_one_or_none()
    if not stockin:
        raise NotFoundError('备货记录不存在或非湖北工厂备货')

    if stockin.confirmed_at is not None:
        logger.info('湖北备货重复确认（幂等）：stockin_id=%s，操作人：%s', stockin_id, current_user.username)
        return {'success': True, 'message': '备货已确认', 'already_confirmed': True}

    stockin.confirmed_at = datetime.now(UTC).replace(tzinfo=None)  # naive UTC: DB列类型为 TIMESTAMP WITHOUT TIME ZONE
    stockin.confirmed_by_id = current_user.id
    await db.flush()

    await cache_mgr.invalidate(InvalidationStrategy.DOMAIN, CacheDomain.ORDER)
    await _safe_invalidate_purchase_cache()

    logger.info('湖北备货确认成功：stockin_no=%s，操作人：%s', stockin.stockin_no, current_user.username)
    return {'success': True, 'message': '备货已确认', 'already_confirmed': False}

