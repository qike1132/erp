"""采购订单完成态查询辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.purchase._list import _serialize_po_item
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)

_COMPLETED_SORT_MAP = {
    'completed_at': PurchaseOrder.completed_at,
    'order_no': PurchaseOrder.order_no,
    'total_amount': PurchaseOrder.total_amount,
}

_QUICK_FILTER_DAYS = {
    'today': 0,
    'week': 7,
    'month': 30,
}


def _apply_completed_filters(
    query, count_query, *,
    supplier_id, keyword, date_from, date_to,
    order_no, customer_name, product_name, supplier_name,
    barcode, material_name, start_date, end_date,
):
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
        count_query = count_query.where(PurchaseOrder.supplier_id == supplier_id)
    if keyword:
        like_pattern = f'%{escape_like(keyword)}%'
        kw_filter = or_(
            PurchaseOrder.order_no.ilike(like_pattern),
            PurchaseOrder.customer_name.ilike(like_pattern),
            PurchaseOrder.supplier_name.ilike(like_pattern),
        )
        query = query.where(kw_filter)
        count_query = count_query.where(kw_filter)
    if date_from:
        query = query.where(PurchaseOrder.completed_at >= date_from)
        count_query = count_query.where(PurchaseOrder.completed_at >= date_from)
    if date_to:
        end_date = f'{date_to} 23:59:59'
        query = query.where(PurchaseOrder.completed_at <= end_date)
        count_query = count_query.where(PurchaseOrder.completed_at <= end_date)
    # 分字段过滤（与前端 useCompletedOrders filters 一一对应）
    for col, val in (
        (PurchaseOrder.order_no, order_no),
        (PurchaseOrder.customer_name, customer_name),
        (PurchaseOrder.product_name, product_name),
        (PurchaseOrder.supplier_name, supplier_name),
    ):
        if val:
            pattern = f'%{escape_like(val)}%'
            query = query.where(col.ilike(pattern))
            count_query = count_query.where(col.ilike(pattern))
    if start_date:
        query = query.where(PurchaseOrder.completed_at >= start_date)
        count_query = count_query.where(PurchaseOrder.completed_at >= start_date)
    if end_date:
        query = query.where(PurchaseOrder.completed_at <= f'{end_date} 23:59:59')  # sql-safe: escape_like/绑定参数/常量片段
        count_query = count_query.where(PurchaseOrder.completed_at <= f'{end_date} 23:59:59')  # sql-safe: escape_like/绑定参数/常量片段
    # barcode / material_name 需要 EXISTS 子查询 purchase_order_item
    if barcode:
        barcode_pattern = f'%{escape_like(barcode)}%'
        barcode_filter = exists().where(
            PurchaseOrderItem.order_id == PurchaseOrder.id,
            PurchaseOrderItem.barcode.ilike(barcode_pattern),
        )
        query = query.where(barcode_filter)
        count_query = count_query.where(barcode_filter)
    if material_name:
        material_pattern = f'%{escape_like(material_name)}%'
        material_filter = exists().where(
            PurchaseOrderItem.order_id == PurchaseOrder.id,
            PurchaseOrderItem.material_name.ilike(material_pattern),
        )
        query = query.where(material_filter)
        count_query = count_query.where(material_filter)
    return query, count_query

def _apply_completed_quick_filter(query, count_query, quick_filter):
    days = _QUICK_FILTER_DAYS.get(quick_filter)
    if days is None:
        return query, count_query
    threshold = datetime.now(UTC).replace(tzinfo=None).date() - timedelta(days=days)
    query = query.where(PurchaseOrder.completed_at >= threshold)
    count_query = count_query.where(PurchaseOrder.completed_at >= threshold)
    return query, count_query

async def _fetch_completed_items_and_arrived(db: AsyncSession, order_ids: list[int]):
    if not order_ids:
        return {}, {}
    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
    )
    all_items = items_result.scalars().all()
    items_by_order: dict[int, list] = defaultdict(list)
    for item in all_items:
        items_by_order[item.order_id].append(item)

    regs_result = await db.execute(
        select(
            MaterialRegistrationItem.material_name,
            MaterialRegistrationItem.material_code,
            func.sum(MaterialRegistrationItem.received_quantity).label('total'),
        ).join(
            MaterialRegistration, MaterialRegistrationItem.registration_id == MaterialRegistration.id
        ).where(
            MaterialRegistration.purchase_order_id.in_(order_ids),
            MaterialRegistration.status.in_(('pending', 'partial', 'completed')),
        ).group_by(
            MaterialRegistrationItem.material_name,
            MaterialRegistrationItem.material_code,
        )
    )
    arrived_map = {
        (r.material_name, r.material_code or ''): int(r.total or 0)
        for r in regs_result
    }
    return items_by_order, arrived_map

def _serialize_completed_item(item, arrived_map: dict) -> dict:
    required = int(item.quantity or 0)
    key = (item.material_name, item.material_code)
    arrived = arrived_map.get(key, 0)
    return {
        **_serialize_po_item(item),
        'is_arrived': required > 0 and arrived >= required,
        'deficit': max(0, required - arrived) if required > 0 else 0,
    }

def _serialize_completed_order(order, items, arrived_map: dict, source_order_no: str, sku_items: list[dict] | None = None) -> dict:
    return {
        'id': order.id,
        'order_no': order.order_no,
        'source_order_no': source_order_no,
        'supplier_name': order.supplier_name,
        'supplier_id': order.supplier_id,
        'customer_name': order.customer_name,
        'customer': order.customer_name,
        'status': order.status,
        'total_amount': float(order.total_amount or 0),
        'product_name': order.product_name or '',
        'quantity': float(order.product_quantity or 0) if order.product_quantity else 0,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'note': order.remark or '',
        'create_time': order.create_time.strftime('%Y-%m-%d %H:%M') if order.create_time else '',
        'completed_at': order.completed_at.strftime('%Y-%m-%d %H:%M') if order.completed_at else '',
        'items': [_serialize_completed_item(item, arrived_map) for item in items],
        'sku_items': sku_items or [],
    }
