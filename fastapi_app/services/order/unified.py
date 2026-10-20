"""
订单+备货合并查询（订单管理页通用列表）。

泛化自 fastapi_app/services/order/beile.py 的 UNION ALL + ilike + 窗口分页思路，
去掉湖北硬编码、confirm_status、采购单/确认注入等 beile 专属逻辑，得到适用于
「订单管理」页的订单(Order)与备货(StockIn)统一只读列表。

设计要点：
- 两侧统一投影为 (record_type, source_id, order_no, customer, sort_date) 后 UNION ALL；
- 按 sort_date DESC NULLS LAST, record_type, source_id 稳定排序；
- 分页用 func.count().over() 窗口计数（单次扫描拿到 total）；
- 备货侧不设软删状态位（StockIn 只有硬删，无 is_deleted 过滤）；
- 日期参数非法抛 BusinessError（HTTP 400），不静默忽略。
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import desc, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from fastapi_app.core.exceptions import BusinessError
from fastapi_app.services import escape_like
from fastapi_app.services.order.queries import _batch_item_factories, _parse_date_condition
from fastapi_app.services.order_utils import _batch_deduct_quantities
from fastapi_app.shared_models import Order, OrderItem, Product, StockIn

logger = logging.getLogger(__name__)

_PER_PAGE_MAX = 500


def _parse_stockin_date_condition(date_str: str | None, is_end: bool = False):
    """备货侧日期条件（镜像 _parse_date_condition，因后者硬编码 Order.order_date）。

    空值返回 None（不筛选）；非法格式抛 BusinessError（HTTP 400），不静默忽略。
    """
    if not date_str:
        return None
    try:
        if is_end:
            end_dt = datetime.strptime(date_str, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
            return StockIn.stockin_date <= end_dt
        start_dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=UTC)
        return StockIn.stockin_date >= start_dt
    except ValueError:
        raise BusinessError(f"{'结束' if is_end else '开始'}日期格式错误，应为 YYYY-MM-DD") from None


def _build_order_part(
    product_kw: str | None,
    order_no_kw: str | None,
    customer: str | None,
    status: str | None,
    factory: str | None,
    start_date: str | None,
    end_date: str | None,
    keyword: str | None = None,
):
    """订单侧子查询：投影统一列并施加订单侧筛选。"""
    part = select(
        literal('order').label('record_type'),
        Order.id.label('source_id'),
        Order.order_no.label('order_no'),
        Order.customer.label('customer'),
        Order.order_date.label('sort_date'),
    ).where(Order.is_deleted.isnot(True))

    if factory:
        part = part.where(Order.items.any(OrderItem.product.has(Product.factory == factory)))
    if status:
        part = part.where(Order.status == status)
    if customer:
        part = part.where(Order.customer.like(f'%{escape_like(customer)}%'))
    if order_no_kw:
        kw = f'%{escape_like(order_no_kw)}%'
        part = part.where(Order.order_no.ilike(kw))
    if product_kw:
        kw = f'%{escape_like(product_kw)}%'
        part = part.where(Order.items.any(or_(
            OrderItem.product_name.ilike(kw),
            OrderItem.product_barcode.ilike(kw),
        )))
    # keyword OR 搜索：单号 / 客户 / SKU 产品名 / 条码 任意命中即返回（搜索框）
    if keyword:
        kw = f'%{escape_like(keyword)}%'
        part = part.where(or_(
            Order.order_no.ilike(kw),
            Order.customer.ilike(kw),
            Order.items.any(or_(
                OrderItem.product_name.ilike(kw),
                OrderItem.product_barcode.ilike(kw),
            )),
        ))

    start_cond = _parse_date_condition(start_date)
    if start_cond is not None:
        part = part.where(start_cond)
    end_cond = _parse_date_condition(end_date, is_end=True)
    if end_cond is not None:
        part = part.where(end_cond)
    return part


def _build_stockin_part(
    product_kw: str | None,
    order_no_kw: str | None,
    customer: str | None,
    factory: str | None,
    start_date: str | None,
    end_date: str | None,
    keyword: str | None = None,
):
    """备货侧子查询：投影统一列并施加备货侧筛选（status 不适用，恒不过滤）。"""
    part = select(
        literal('stockin').label('record_type'),
        StockIn.id.label('source_id'),
        StockIn.stockin_no.label('order_no'),
        StockIn.customer.label('customer'),
        StockIn.stockin_date.label('sort_date'),
    )

    if factory:
        part = part.where(StockIn.product.has(Product.factory == factory))
    if customer:
        part = part.where(StockIn.customer.like(f'%{escape_like(customer)}%'))
    if order_no_kw:
        kw = f'%{escape_like(order_no_kw)}%'
        part = part.where(StockIn.stockin_no.ilike(kw))
    if product_kw:
        kw = f'%{escape_like(product_kw)}%'
        part = part.where(StockIn.product.has(or_(
            Product.name.ilike(kw),
            Product.barcode.ilike(kw),
        )))
    # keyword OR 搜索：备货号 / 客户 / 产品名 / 条码 任意命中即返回（与订单侧同构）
    if keyword:
        kw = f'%{escape_like(keyword)}%'
        part = part.where(or_(
            StockIn.stockin_no.ilike(kw),
            StockIn.customer.ilike(kw),
            StockIn.product.has(or_(
                Product.name.ilike(kw),
                Product.barcode.ilike(kw),
            )),
        ))

    start_cond = _parse_stockin_date_condition(start_date)
    if start_cond is not None:
        part = part.where(start_cond)
    end_cond = _parse_stockin_date_condition(end_date, is_end=True)
    if end_cond is not None:
        part = part.where(end_cond)
    return part


def _build_unified_query(
    record_type: str | None = None,
    product_kw: str | None = None,
    order_no_kw: str | None = None,
    customer: str | None = None,
    status: str | None = None,
    factory: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    keyword: str | None = None,
):
    """构建订单+备货的 UNION ALL 子查询。"""
    order_part = _build_order_part(
        product_kw, order_no_kw, customer, status, factory, start_date, end_date,
        keyword=keyword,
    )
    stockin_part = _build_stockin_part(
        product_kw, order_no_kw, customer, factory, start_date, end_date,
        keyword=keyword,
    )

    if record_type == 'order':
        parts = [order_part]
    elif record_type == 'stockin':
        parts = [stockin_part]
    else:  # 'all' / None / 未知值 → 全量（端点用 Literal 已拦截未知值）
        parts = [order_part, stockin_part]

    return union_all(*parts).subquery()


async def _fetch_orders(db: AsyncSession, order_ids: list[int]) -> dict[int, Order]:
    """按 id 批量回填订单（含 items → product 与 product 关系，防 MissingGreenlet）。"""
    if not order_ids:
        return {}
    result = await db.execute(
        select(Order)
        .options(
            joinedload(Order.product),
            selectinload(Order.items).joinedload(OrderItem.product),
        )
        .where(Order.id.in_(order_ids))
    )
    return {o.id: o for o in result.scalars().unique()}


async def _fetch_stockins(db: AsyncSession, stockin_ids: list[int]) -> dict[int, StockIn]:
    """按 id 批量回填备货（含 product 关系）。"""
    if not stockin_ids:
        return {}
    result = await db.execute(
        select(StockIn)
        .options(selectinload(StockIn.product))
        .where(StockIn.id.in_(stockin_ids))
    )
    return {s.id: s for s in result.scalars()}


def _fmt_datetime(dt: datetime | None) -> str:
    """格式化时间戳（对齐 OrderSerializer：'%Y-%m-%d %H:%M'，空值返回空串）。"""
    return dt.strftime('%Y-%m-%d %H:%M') if dt else ''


def _product_dict(product: Product | None) -> dict | None:
    """手工构造产品摘要，禁止整体序列化 Product / to_dict()（防 price 泄露）。"""
    if product is None:
        return None
    return {
        'id': product.id,
        'name': product.name,
        'barcode': product.barcode or '',
        'image': product.image or '',
    }


def _build_order_record(order: Order, deduct_quantity: int, factories: list[str]) -> dict:
    """构造订单行（product 取首 SKU，无 SKU 时回退 order.product）。"""
    first_item = order.items[0] if order.items else None
    product_src = first_item.product if first_item else order.product
    items_data = [
        {
            'id': item.id,
            'product_id': item.product_id,
            'product_name': item.product_name,
            'product_barcode': item.product_barcode,
            'product_image': (item.product.image or '') if item.product else '',
            'quantity': item.quantity,
            'deduct_quantity': item.deduct_quantity or 0,
            'note': item.note or '',
        }
        for item in order.items
    ]
    return {
        'id': order.id,
        'record_type': 'order',
        'order_no': order.order_no,
        'customer': order.customer,
        'order_date': _fmt_datetime(order.order_date),
        'status': order.status,
        'product': _product_dict(product_src),
        'quantity': order.quantity,
        'deduct_quantity': deduct_quantity,
        'factories': factories,
        'items': items_data,
    }


def _build_stockin_record(stockin: StockIn) -> dict:
    """构造备货行（status 恒为 null，factories 取备货产品工厂）。"""
    product = stockin.product
    items_data = [
        {
            'id': stockin.id,
            'product_id': stockin.product_id,
            'product_name': product.name if product else None,
            'product_barcode': product.barcode if product else None,
            'product_image': (product.image or '') if product else '',
            'quantity': stockin.quantity,
            'deduct_quantity': 0,
            'note': stockin.note or '',
        }
    ]
    return {
        'id': stockin.id,
        'record_type': 'stockin',
        'order_no': stockin.stockin_no,
        'customer': stockin.customer,
        'order_date': _fmt_datetime(stockin.stockin_date),
        'status': None,
        'product': _product_dict(product),
        'quantity': stockin.quantity,
        'deduct_quantity': 0,
        'factories': [product.factory] if product and product.factory else [],
        'items': items_data,
    }


async def _fetch_page_rows(db: AsyncSession, unified, page: int, per_page: int):
    """分页拉取统一子查询行（sort_date DESC NULLS LAST 稳定排序，窗口计数随行下发）。

    Returns:
        (rows, total)：rows 为当前页行；total 为命中总数（空页时对 offset>0 补探针计数）。
    """
    offset = (page - 1) * per_page
    page_result = await db.execute(
        select(
            unified.c.record_type,
            unified.c.source_id,
            unified.c.order_no,
            unified.c.customer,
            unified.c.sort_date,
            func.count().over().label('total_count'),
        )
        .order_by(
            desc(unified.c.sort_date).nullslast(),
            unified.c.record_type,
            unified.c.source_id,
        )
        .limit(per_page)
        .offset(offset)
    )
    rows = page_result.all()

    if not rows:
        total = 0
        if offset != 0:
            probe = await db.execute(
                select(func.count().over().label('total_count')).select_from(unified).limit(1)
            )
            total = probe.scalar() or 0
        return [], total

    return rows, rows[0].total_count or 0


async def _assemble_records(db: AsyncSession, rows) -> list[dict]:
    """按行类型批量回填订单/备货并组装统一记录 dict（行序保持分页排序）。"""
    order_ids = [r.source_id for r in rows if r.record_type == 'order']
    stockin_ids = [r.source_id for r in rows if r.record_type == 'stockin']

    orders_map = await _fetch_orders(db, order_ids)
    stockins_map = await _fetch_stockins(db, stockin_ids)
    deduct_map = await _batch_deduct_quantities(db, order_ids)
    factory_map = await _batch_item_factories(db, order_ids)

    items: list[dict] = []
    for r in rows:
        if r.record_type == 'order':
            order = orders_map.get(r.source_id)
            if order is not None:
                items.append(_build_order_record(
                    order,
                    deduct_map.get(order.id, 0),
                    factory_map.get(order.id, []),
                ))
        else:
            stockin = stockins_map.get(r.source_id)
            if stockin is not None:
                items.append(_build_stockin_record(stockin))
    return items


async def get_unified_records(
    db: AsyncSession,
    *,
    page: int,
    per_page: int,
    record_type: str | None,
    product_kw: str | None,
    order_no_kw: str | None,
    customer: str | None,
    status: str | None,
    factory: str | None,
    start_date: str | None,
    end_date: str | None,
    keyword: str | None = None,
) -> dict:
    """订单+备货合并分页查询（只读）。

    Args:
        db: 异步数据库会话（只读副本）。
        page: 页码，从 1 开始。
        per_page: 每页数量（上限 500）。
        record_type: 记录类型（all/order/stockin）。
        product_kw: 产品关键字（订单侧匹配 SKU 名称/条码，备货侧匹配产品名称/条码）。
        order_no_kw: 单号关键字（订单侧订单号，备货侧备货号）。
        customer: 客户名关键字。
        status: 订单状态筛选（仅订单侧生效）。
        factory: 工厂筛选（订单侧按 SKU 工厂，备货侧按产品工厂；非空时两侧均过滤）。
        start_date: 开始日期（YYYY-MM-DD，含当日）。
        end_date: 结束日期（YYYY-MM-DD，含当日）。
        keyword: 搜索框 OR 关键字（单号/客户/产品名/条码，两侧同构，任意命中即返回）。

    Returns:
        dict: {'items': [...], 'total': int, 'page': int, 'per_page': int}。
    """
    page = max(page, 1)
    per_page = min(max(per_page, 1), _PER_PAGE_MAX)

    unified = _build_unified_query(
        record_type=record_type,
        product_kw=product_kw,
        order_no_kw=order_no_kw,
        customer=customer,
        status=status,
        factory=factory,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword,
    )

    rows, total = await _fetch_page_rows(db, unified, page, per_page)
    items = await _assemble_records(db, rows) if rows else []
    return {'items': items, 'total': total, 'page': page, 'per_page': per_page}
