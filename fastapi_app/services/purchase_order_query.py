"""
采购订单查询操作

职责：采购订单的列表查询、详情查询、汇总统计、导出等读操作。
从 purchase_order_service.py 拆分而来，保持函数签名不变。
"""
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.purchase_utils import parse_source_order_ids
from fastapi_app.utils import calc_total_pages
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
)
from fastapi_app.shared_models.order import Order

logger = logging.getLogger(__name__)


def _parse_source_order_ids(po) -> list[int]:
    """解析采购订单关联的客户订单ID列表

    合并单值字段 source_order_id 与多值字段 source_order_ids（JSON/list）。
    多值字段的解析委托给 purchase_utils.parse_source_order_ids。
    """
    ids: list[int] = []
    if po.source_order_id:
        ids.append(po.source_order_id)
    ids.extend(parse_source_order_ids(po.source_order_ids))
    return ids


async def _fetch_bom_data(db: AsyncSession, product_ids: list[int], prod_name_map: dict[int, str] | None = None) -> dict[int, list[dict]]:
    """获取产品的 BOM 物料数据（填充物、面料、辅料）"""
    bom_data: dict[int, list[dict]] = {}
    if not product_ids:
        return bom_data

    fill_result = await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id.in_(product_ids))
    )
    for row in fill_result.scalars().all():
        name_prefix = prod_name_map.get(row.product_id, '') if prod_name_map else ''
        bom_data.setdefault(row.product_id, []).append({
            'material_name': f'{name_prefix}-填充物' if name_prefix else '填充物',
            'specification': row.specification or '',
            'unit': row.unit or '克',
            'quantity': float(row.cotton_usage or 0),
            'supplier_name': row.supplier_name or '',
            'category': 'filling',
        })

    fab_result = await db.execute(
        select(ProductFabric).where(ProductFabric.product_id.in_(product_ids))
    )
    for row in fab_result.scalars().all():
        bom_data.setdefault(row.product_id, []).append({
            'material_name': row.fabric_name or '面料',
            'specification': row.specification or '',
            'unit': row.unit or '米',
            'quantity': float(row.quantity or 0),
            'supplier_name': row.supplier_name or '',
            'category': 'fabric',
        })

    acc_result = await db.execute(
        select(ProductAccessory).where(ProductAccessory.product_id.in_(product_ids))
    )
    for row in acc_result.scalars().all():
        bom_data.setdefault(row.product_id, []).append({
            'material_name': row.accessory_name or '配件',
            'specification': row.specification or '',
            'unit': row.unit or '个',
            'quantity': float(row.quantity or 0),
            'supplier_name': row.supplier_name or '',
            'category': 'accessory',
        })

    return bom_data


_PO_SORT_MAP = {
    'create_time': PurchaseOrder.create_time,
    'order_no': PurchaseOrder.order_no,
    'total_amount': PurchaseOrder.total_amount,
}


def _apply_po_list_filters(query, count_query, *, status, supplier_id,
                           keyword, date_from, date_to):
    if status:
        if ',' in status:
            statuses = [s.strip() for s in status.split(',') if s.strip()]
            query = query.where(PurchaseOrder.status.in_(statuses))
            count_query = count_query.where(PurchaseOrder.status.in_(statuses))
        else:
            query = query.where(PurchaseOrder.status == status)
            count_query = count_query.where(PurchaseOrder.status == status)
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
        query = query.where(PurchaseOrder.create_time >= date_from)
        count_query = count_query.where(PurchaseOrder.create_time >= date_from)
    if date_to:
        end_date = f'{date_to} 23:59:59'
        query = query.where(PurchaseOrder.create_time <= end_date)
        count_query = count_query.where(PurchaseOrder.create_time <= end_date)
    return query, count_query


def _apply_po_sort(query, sort_by, sort_order, default_col, sort_map):
    sort_col = sort_map.get(sort_by, default_col)
    if sort_order == 'desc':
        sort_col = sort_col.desc()
    return query.order_by(sort_col)


async def _fetch_po_items_by_order(db: AsyncSession, order_ids: list[int]) -> dict[int, list]:
    if not order_ids:
        return {}
    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
    )
    all_items = items_result.scalars().all()
    items_by_order: dict[int, list] = defaultdict(list)
    for item in all_items:
        items_by_order[item.order_id].append(item)
    return items_by_order


async def _build_po_source_fill_map(db: AsyncSession, orders) -> dict[int, tuple[str, int]]:
    source_order_map: dict[int, tuple[str, int]] = {}
    orders_needing_fill = [o for o in orders if not o.product_name and (o.source_order_ids or o.source_order_id)]
    if not orders_needing_fill:
        return source_order_map
    all_source_ids: set[int] = set()
    for order in orders_needing_fill:
        if order.source_order_id:
            all_source_ids.add(order.source_order_id)
        all_source_ids.update(parse_source_order_ids(order.source_order_ids))
    if not all_source_ids:
        return source_order_map
    cust_result = await db.execute(
        select(Order.id, Order.product_id, Order.quantity)
        .where(Order.id.in_(all_source_ids))
    )
    cust_rows = cust_result.all()
    cust_pids = list({row.product_id for row in cust_rows if row.product_id})
    pid_name_map: dict[int, str] = {}
    if cust_pids:
        prod_result = await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(cust_pids))
        )
        pid_name_map = dict(prod_result.all())
    for row in cust_rows:
        source_order_map[row.id] = (pid_name_map.get(row.product_id, ''), row.quantity or 0)
    return source_order_map


async def _build_po_source_no_map(db: AsyncSession, orders) -> dict[int, str]:
    po_source_ids_map: dict[int, list[int]] = {}
    all_source_ids: set[int] = set()
    for order in orders:
        ids = _parse_source_order_ids(order)
        po_source_ids_map[order.id] = ids
        all_source_ids.update(ids)
    if not all_source_ids:
        return {}
    no_result = await db.execute(
        select(Order.id, Order.order_no).where(Order.id.in_(all_source_ids))
    )
    source_order_no_map = dict(no_result.all())
    po_source_no_str: dict[int, str] = {}
    for order in orders:
        nos = [source_order_no_map.get(sid, '') for sid in po_source_ids_map.get(order.id, [])]
        nos = [n for n in nos if n]
        po_source_no_str[order.id] = '、'.join(nos) if nos else ''
    return po_source_no_str


def _resolve_po_product_name_qty(order, source_order_map: dict[int, tuple[str, int]]) -> tuple[str, float]:
    product_name = order.product_name or ''
    quantity = float(order.product_quantity or 0) if order.product_quantity else 0
    if product_name and quantity:
        return product_name, quantity
    resolved_ids = _parse_source_order_ids(order)
    names: set[str] = set()
    qty_sum = 0
    for sid in resolved_ids:
        info = source_order_map.get(sid)
        if info:
            if info[0]:
                names.add(info[0])
            qty_sum += info[1]
    if not product_name and names:
        product_name = '、'.join(sorted(names)) if len(names) > 1 else next(iter(names))
    if not quantity and qty_sum:
        quantity = float(qty_sum)
    return product_name, quantity


def _serialize_po_item(item) -> dict:
    return {
        'id': item.id,
        'material_name': item.material_name,
        'material_code': item.material_code or '',
        'specification': item.specification or '',
        'unit': item.unit or '',
        'unit_price': float(item.unit_price or 0),
        'quantity': float(item.quantity or 0),
        'amount': float(item.total_price or 0),
        'category': item.material_category or '',
        'remark': item.remark or '',
    }


def _serialize_po_list_item(order, items, product_name, quantity, source_order_no) -> dict:
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
        'product_name': product_name,
        'quantity': quantity,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'has_bom': bool(items),
        'note': order.remark or '',
        'create_time': order.create_time.strftime('%Y-%m-%d %H:%M') if order.create_time else '',
        'items': [_serialize_po_item(item) for item in items],
    }


@cache_result(
    key_prefix='orders',
    ttl=120,
    local_ttl=60,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 20)}:s{kwargs.get('status', '')}:k{kwargs.get('keyword', '')}:df{kwargs.get('date_from', '')}:dt{kwargs.get('date_to', '')}:si{kwargs.get('supplier_id', '')}:sb{kwargs.get('sort_by', 'create_time')}:so{kwargs.get('sort_order', 'desc')}",
)
async def get_purchase_orders(db: AsyncSession, *, page: int = 1, per_page: int = 20,
                              status: str = '', supplier_id: int | None = None,
                              keyword: str = '', date_from: str = '', date_to: str = '',
                              sort_by: str = 'create_time', sort_order: str = 'desc') -> dict:
    query = select(PurchaseOrder)
    count_query = select(func.count(PurchaseOrder.id))
    query, count_query = _apply_po_list_filters(
        query, count_query, status=status, supplier_id=supplier_id,
        keyword=keyword, date_from=date_from, date_to=date_to,
    )
    query = _apply_po_sort(query, sort_by, sort_order, PurchaseOrder.create_time, _PO_SORT_MAP)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    orders = result.scalars().unique().all()

    order_ids = [o.id for o in orders]
    items_by_order = await _fetch_po_items_by_order(db, order_ids)
    source_order_map = await _build_po_source_fill_map(db, orders)
    po_source_no_str = await _build_po_source_no_map(db, orders)

    order_list = []
    for order in orders:
        items = items_by_order.get(order.id, [])
        product_name, quantity = _resolve_po_product_name_qty(order, source_order_map)
        order_list.append(_serialize_po_list_item(
            order, items, product_name, quantity, po_source_no_str.get(order.id, ''),
        ))

    return {
        'orders': order_list,
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


async def _resolve_po_detail_product_name_qty(
    db: AsyncSession, order, product_name: str, quantity: float,
) -> tuple[str, float, list[str]]:
    """Resolve product_name, quantity, and source_order_nos for a single purchase order detail."""
    source_order_nos: list[str] = []
    resolved_ids = _parse_source_order_ids(order)
    if not resolved_ids:
        return product_name, quantity, source_order_nos
    if not product_name or not quantity:
        cust_result = await db.execute(
            select(Order.id, Order.product_id, Order.quantity, Order.order_no)
            .where(Order.id.in_(resolved_ids))
        )
        cust_rows = cust_result.all()
        cust_pids = list({row.product_id for row in cust_rows if row.product_id})
        pid_name_map: dict[int, str] = {}
        if cust_pids:
            prod_result = await db.execute(
                select(Product.id, Product.name).where(Product.id.in_(cust_pids))
            )
            pid_name_map = dict(prod_result.all())
        names: set[str] = set()
        qty_sum = 0
        for row in cust_rows:
            pname = pid_name_map.get(row.product_id, '')
            if pname:
                names.add(pname)
            qty_sum += row.quantity or 0
            if row.order_no:
                source_order_nos.append(row.order_no)
        if not product_name and names:
            product_name = '、'.join(sorted(names)) if len(names) > 1 else next(iter(names))
        if not quantity and qty_sum:
            quantity = float(qty_sum)
    else:
        no_result = await db.execute(
            select(Order.id, Order.order_no).where(Order.id.in_(resolved_ids))
        )
        source_order_nos = [row.order_no for row in no_result.all() if row.order_no]
    return product_name, quantity, source_order_nos


async def get_purchase_order(db: AsyncSession, order_id: int) -> dict:
    order = await db.get(PurchaseOrder, order_id)
    if not order:
        return None

    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order_id)
    )
    items = items_result.scalars().all()

    product_name = order.product_name or ''
    quantity = float(order.product_quantity or 0) if order.product_quantity else 0
    product_name, quantity, source_order_nos = await _resolve_po_detail_product_name_qty(
        db, order, product_name, quantity,
    )

    return {
        'id': order.id,
        'order_no': order.order_no,
        'source_order_no': '、'.join(source_order_nos) if source_order_nos else '',
        'supplier_name': order.supplier_name,
        'supplier_id': order.supplier_id,
        'customer_name': order.customer_name,
        'customer': order.customer_name,
        'status': order.status,
        'total_amount': float(order.total_amount or 0),
        'product_name': product_name,
        'quantity': quantity,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'note': order.remark or '',
        'create_time': order.create_time.strftime('%Y-%m-%d %H:%M') if order.create_time else '',
        'items': [_serialize_po_item(item) for item in items],
    }


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


def _apply_completed_filters(query, count_query, *, supplier_id, keyword, date_from, date_to):
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


def _serialize_completed_order(order, items, arrived_map: dict, source_order_no: str) -> dict:
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
    }


async def get_completed_purchase_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 20,
    supplier_id: int | None = None, keyword: str = '',
    date_from: str = '', date_to: str = '',
    quick_filter: str = '', is_arrived: str = '',
    sort_by: str = 'completed_at', sort_order: str = 'desc',
) -> dict:
    query = select(PurchaseOrder).where(PurchaseOrder.status == 'completed')
    count_query = select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == 'completed')
    query, count_query = _apply_completed_filters(
        query, count_query, supplier_id=supplier_id, keyword=keyword,
        date_from=date_from, date_to=date_to,
    )
    query, count_query = _apply_completed_quick_filter(query, count_query, quick_filter)
    query = _apply_po_sort(query, sort_by, sort_order, PurchaseOrder.completed_at, _COMPLETED_SORT_MAP)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    orders = result.scalars().unique().all()

    order_ids = [o.id for o in orders]
    items_by_order, arrived_map = await _fetch_completed_items_and_arrived(db, order_ids)
    po_source_no_str = await _build_po_source_no_map(db, orders)

    order_list = []
    for order in orders:
        items = items_by_order.get(order.id, [])
        order_list.append(_serialize_completed_order(
            order, items, arrived_map, po_source_no_str.get(order.id, ''),
        ))

    return {
        'orders': order_list,
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


def _build_po_items_map(all_items) -> dict[tuple, list]:
    items_map: dict[tuple, list] = {}
    for item in all_items:
        ikey = (item.order_id, item.material_name, item.specification or '', item.unit or '')
        items_map.setdefault(ikey, []).append(item)
    return items_map


async def _fetch_po_items_map(db: AsyncSession, po_ids: list[int]) -> dict[tuple, list]:
    if not po_ids:
        return {}
    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(po_ids))
    )
    return _build_po_items_map(items_result.scalars().all())


async def _fetch_supplier_cust_order_map(db: AsyncSession, orders) -> dict[int, tuple[int, float]]:
    source_order_ids: set[int] = set()
    for po in orders:
        source_order_ids.update(_parse_source_order_ids(po))
    cust_order_map: dict[int, tuple[int, float]] = {}
    if source_order_ids:
        cust_result = await db.execute(
            select(Order.id, Order.product_id, Order.quantity).where(Order.id.in_(source_order_ids))
        )
        for row in cust_result.all():
            cust_order_map[row.id] = (row.product_id, row.quantity or 0)
    return cust_order_map


def _resolve_po_qty_and_pid(po, cust_order_map: dict[int, tuple[int, float]]) -> tuple[float, int | None]:
    order_qty = float(po.product_quantity or 0)
    sids = _parse_source_order_ids(po)
    if not order_qty:
        for sid in sids:
            if sid in cust_order_map:
                order_qty += cust_order_map[sid][1]
    pid = None
    for sid in sids:
        if sid in cust_order_map:
            pid = cust_order_map[sid][0]
            break
    return order_qty, pid


def _build_supplier_mat_map(orders, bom_data, items_map, cust_order_map) -> dict[tuple, dict]:
    mat_map: dict[tuple, dict] = {}
    for po in orders:
        order_qty, pid = _resolve_po_qty_and_pid(po, cust_order_map)
        for bom in bom_data.get(pid, []):
            sup = bom['supplier_name'] or po.supplier_name or '未指定供应商'
            key = (sup, bom['material_name'], bom['specification'], bom['unit'])
            ikey = (po.id, bom['material_name'], bom['specification'], bom['unit'])
            matching_items = items_map.get(ikey, [])
            total_qty = sum(float(it.quantity or 0) for it in matching_items) if matching_items else bom['quantity'] * order_qty
            if key in mat_map:
                mat_map[key]['total_quantity'] += total_qty
            else:
                mat_map[key] = {
                    'material_name': bom['material_name'],
                    'specification': bom['specification'],
                    'total_quantity': total_qty,
                    'unit': bom['unit'],
                    'supplier_name': sup,
                }
    return mat_map


async def get_supplier_order_summary(db: AsyncSession, order_ids: list | None = None) -> dict:
    if not order_ids:
        return {'materials': [], 'order_count': 0}

    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids))
    )
    orders = result.scalars().all()

    cust_order_map = await _fetch_supplier_cust_order_map(db, orders)

    product_ids = list({pid for pid, _ in cust_order_map.values() if pid})
    bom_data = await _fetch_bom_data(db, product_ids)

    po_ids = [o.id for o in orders]
    items_map = await _fetch_po_items_map(db, po_ids)

    mat_map = _build_supplier_mat_map(orders, bom_data, items_map, cust_order_map)
    materials = sorted(mat_map.values(), key=lambda x: (x['supplier_name'], x['material_name']))
    return {'materials': materials, 'order_count': len(orders)}


async def _fetch_factory_cust_order_map(db: AsyncSession, orders) -> dict[int, tuple[int, float, str]]:
    source_order_ids: set[int] = set()
    for po in orders:
        source_order_ids.update(_parse_source_order_ids(po))
    cust_order_map: dict[int, tuple[int, float, str]] = {}
    if source_order_ids:
        cust_result = await db.execute(
            select(Order.id, Order.product_id, Order.quantity, Order.customer).where(Order.id.in_(source_order_ids))
        )
        for row in cust_result.all():
            cust_order_map[row.id] = (row.product_id, row.quantity or 0, row.customer or '')
    return cust_order_map


async def _fetch_prod_name_map(db: AsyncSession, product_ids: list[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    prod_result = await db.execute(
        select(Product.id, Product.name).where(Product.id.in_(product_ids))
    )
    return dict(prod_result.all())


def _resolve_factory_source_info(po, cust_order_map, cust, order_qty):
    sids = _parse_source_order_ids(po)
    pid = None
    for sid in sids:
        if sid in cust_order_map:
            pid = cust_order_map[sid][0]
            if not cust or cust == '未知客户':
                cust = cust_order_map[sid][2] or cust
            if not order_qty:
                order_qty = cust_order_map[sid][1]
            break
    return pid, cust, order_qty


def _resolve_factory_po_info(po, cust_order_map, prod_name_map):
    cust = po.customer_name or '未知客户'
    prod = po.product_name or '未知产品'
    order_qty = float(po.product_quantity or 0)
    pid, cust, order_qty = _resolve_factory_source_info(po, cust_order_map, cust, order_qty)
    if pid and pid in prod_name_map:
        prod = prod_name_map[pid]
    return cust, prod, order_qty, pid


def _accumulate_factory_bom(group, po, bom, items_map, order_qty):
    sup = bom['supplier_name'] or po.supplier_name or '未指定供应商'
    if sup not in group['_supplier_map']:
        group['_supplier_map'][sup] = {
            'supplier_name': sup,
            '_fabric_map': {},
        }
    fabric_map = group['_supplier_map'][sup]['_fabric_map']
    fkey = (bom['material_name'], bom['specification'], bom['unit'])

    ikey = (po.id, bom['material_name'], bom['specification'], bom['unit'])
    matching_items = items_map.get(ikey, [])
    if matching_items:
        per_order_qty = sum(float(it.quantity or 0) for it in matching_items)
        cur_item_ids = [it.id for it in matching_items]
    else:
        per_order_qty = bom['quantity'] * order_qty
        cur_item_ids = []

    if fkey in fabric_map:
        fabric_map[fkey]['quantity'] += per_order_qty
        fabric_map[fkey]['item_ids'].extend(cur_item_ids)
    else:
        fabric_map[fkey] = {
            'fabric_name': bom['material_name'],
            'specification': bom['specification'],
            'quantity': per_order_qty,
            'unit': bom['unit'],
            'item_ids': cur_item_ids,
        }


def _build_factory_group_map(orders, bom_data, items_map, cust_order_map, prod_name_map) -> dict[tuple, dict]:
    group_map: dict[tuple, dict] = {}
    for po in orders:
        cust, prod, order_qty, pid = _resolve_factory_po_info(po, cust_order_map, prod_name_map)
        key = (cust, prod)
        if key not in group_map:
            group_map[key] = {
                'customer_name': cust,
                'product_name': prod,
                'product_quantity': order_qty,
                'order_quantity': order_qty,
                '_supplier_map': {},
            }
        group = group_map[key]
        for bom in bom_data.get(pid, []):
            _accumulate_factory_bom(group, po, bom, items_map, order_qty)
    return group_map


def _serialize_factory_groups(group_map: dict[tuple, dict]) -> list:
    groups = []
    for key in sorted(group_map.keys()):
        group = group_map[key]
        suppliers = []
        for skey in sorted(group['_supplier_map'].keys()):
            supplier = group['_supplier_map'][skey]
            fabrics = [f for f in sorted(supplier['_fabric_map'].values(), key=lambda x: x['fabric_name'])]
            suppliers.append({'supplier_name': supplier['supplier_name'], 'fabrics': fabrics})
        groups.append({
            'customer_name': group['customer_name'],
            'product_name': group['product_name'],
            'product_quantity': group['product_quantity'],
            'order_quantity': group['order_quantity'],
            'suppliers': suppliers,
        })
    return groups


async def get_factory_order_summary(
    db: AsyncSession, order_ids: list | None = None,
) -> dict:
    if not order_ids:
        return {'groups': [], 'order_count': 0}

    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids))
    )
    orders = result.scalars().unique().all()

    cust_order_map = await _fetch_factory_cust_order_map(db, orders)

    product_ids = list({pid for pid, _, _ in cust_order_map.values() if pid})
    prod_name_map = await _fetch_prod_name_map(db, product_ids)

    bom_data = await _fetch_bom_data(db, product_ids, prod_name_map)

    po_ids = [o.id for o in orders]
    items_map = await _fetch_po_items_map(db, po_ids)

    group_map = _build_factory_group_map(orders, bom_data, items_map, cust_order_map, prod_name_map)
    groups = _serialize_factory_groups(group_map)

    return {'groups': groups, 'order_count': len(orders)}


async def export_completed_orders(
    db: AsyncSession, *, supplier_id: int | None = None,
    date_from: str = '', date_to: str = '',
) -> list:
    query = select(PurchaseOrder).where(PurchaseOrder.status == 'completed')
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if date_from:
        query = query.where(PurchaseOrder.completed_at >= date_from)
    if date_to:
        query = query.where(PurchaseOrder.completed_at <= f'{date_to} 23:59:59')
    query = query.order_by(PurchaseOrder.completed_at.desc())

    result = await db.execute(query)
    orders = result.scalars().unique().all()

    rows = []
    order_ids = [o.id for o in orders]

    if order_ids:
        items_result = await db.execute(
            select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids))
        )
        all_items = items_result.scalars().all()
        items_by_order: dict[int, list] = {}
        for item in all_items:
            items_by_order.setdefault(item.order_id, []).append(item)
    else:
        items_by_order = {}

    for order in orders:
        items = items_by_order.get(order.id, [])
        for item in items:
            rows.append({
                'order_no': order.order_no,
                'supplier_name': order.supplier_name,
                'customer_name': order.customer_name,
                'material_name': item.material_name,
                'material_code': item.material_code or '',
                'specification': item.specification or '',
                'unit': item.unit or '',
                'quantity': float(item.quantity or 0),
                'unit_price': float(item.unit_price or 0),
                'amount': float(item.total_price or 0),
                'completed_at': order.completed_at.strftime('%Y-%m-%d') if order.completed_at else '',
            })
    return rows


async def _fetch_processed_order_ids(db: AsyncSession) -> set[int]:
    po_result = await db.execute(
        select(PurchaseOrder.source_order_ids).where(
            PurchaseOrder.source_order_ids.isnot(None),
        )
    )
    processed_order_ids: set[int] = set()
    for row in po_result.all():
        try:
            ids = json.loads(row.source_order_ids)
            if isinstance(ids, list):
                processed_order_ids.update(ids)
        except (ValueError, TypeError):
            pass
    return processed_order_ids


def _build_unprocessed_order_record(order) -> dict:
    return {
        'id': order.id,
        'composite_id': f"order:{order.id}",
        'source_order_id': order.id,
        'order_no': order.order_no,
        'customer': order.customer,
        'customer_name': order.customer,
        'product_id': order.product_id,
        'quantity': order.quantity,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'create_time': order.order_date.strftime('%Y-%m-%d %H:%M') if order.order_date else '',
        'record_type': 'order',
    }


def _build_unprocessed_stockin_record(stockin) -> dict:
    return {
        'id': stockin.id,
        'composite_id': f"stockin:{stockin.id}",
        'source_order_id': stockin.id,
        'order_no': stockin.stockin_no,
        'customer': stockin.customer,
        'customer_name': stockin.customer,
        'product_id': stockin.product_id,
        'quantity': stockin.quantity,
        'order_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '',
        'create_time': stockin.stockin_date.strftime('%Y-%m-%d %H:%M') if stockin.stockin_date else '',
        'record_type': 'stockin',
    }


async def _fetch_bom_product_ids(db: AsyncSession, product_ids: list) -> set[int]:
    bom_product_ids: set[int] = set()
    if not product_ids:
        return bom_product_ids
    filling_result = await db.execute(
        select(ProductMaterial.product_id).where(ProductMaterial.product_id.in_(product_ids))
    )
    bom_product_ids |= {row[0] for row in filling_result}
    fabric_result = await db.execute(
        select(ProductFabric.product_id).where(ProductFabric.product_id.in_(product_ids))
    )
    bom_product_ids |= {row[0] for row in fabric_result}
    accessory_result = await db.execute(
        select(ProductAccessory.product_id).where(ProductAccessory.product_id.in_(product_ids))
    )
    bom_product_ids |= {row[0] for row in accessory_result}
    return bom_product_ids


@cache_result(
    key_prefix='orders:unprocessed',
    ttl=30,
    local_ttl=10,
    key_builder=lambda *args, **kwargs: f"p{kwargs.get('page', 1)}:pp{kwargs.get('per_page', 20)}",
)
async def get_unprocessed_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 20,
) -> dict:
    """获取未处理订单列表——包含客户订单（Order）和备货记录（StockIn）

    采购中心同时查询 status='待备货' 的客户订单和备货记录，
    合并后按日期降序排列，确保任何路径创建的订单/备货都能立即可见。
    """
    from fastapi_app.shared_models import Order as CustomerOrder
    from fastapi_app.shared_models import Product, StockIn

    processed_order_ids = await _fetch_processed_order_ids(db)

    # ---- 查询客户订单（无分页，后续合并后统一分页）----
    order_base_filter = and_(
        CustomerOrder.status == '待备货',
        CustomerOrder.is_deleted == False,  # noqa: E712
    )
    if processed_order_ids:
        order_base_filter = and_(order_base_filter, CustomerOrder.id.notin_(processed_order_ids))

    order_query = select(CustomerOrder).where(order_base_filter).order_by(CustomerOrder.order_date.desc())
    order_result = await db.execute(order_query)
    orders = order_result.scalars().unique().all()

    # ---- 查询备货记录（排除已关联采购单的）----
    # 获取已关联采购单的 StockIn ID（source_order_ids 中可能包含 StockIn ID）
    processed_stockin_ids: set[int] = set()
    if processed_order_ids:
        stockin_id_result = await db.execute(select(StockIn.id))
        all_stockin_ids = {row[0] for row in stockin_id_result}
        processed_stockin_ids = processed_order_ids & all_stockin_ids

    stockin_query = select(StockIn)
    if processed_stockin_ids:
        stockin_query = stockin_query.where(StockIn.id.notin_(processed_stockin_ids))
    stockin_query = stockin_query.order_by(StockIn.stockin_date.desc())
    stockin_result = await db.execute(stockin_query)
    stockins = stockin_result.scalars().unique().all()

    # ---- 合并结果 ----
    all_records = [_build_unprocessed_order_record(order) for order in orders]
    all_records.extend(_build_unprocessed_stockin_record(stockin) for stockin in stockins)

    # 按日期降序排列
    all_records.sort(key=lambda x: x.get('order_date') or '', reverse=True)

    total = len(all_records)

    # 分页
    start = (page - 1) * per_page
    page_records = all_records[start:start + per_page]

    # 批量查询产品名称
    product_ids = list({r['product_id'] for r in page_records})
    pid_name_map: dict[int, str] = {}
    if product_ids:
        prod_result = await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        )
        pid_name_map = dict(prod_result.all())

    # 批量查询 BOM 信息
    bom_product_ids = await _fetch_bom_product_ids(db, product_ids)

    return {
        'orders': [
            {
                'id': r['id'],
                'composite_id': r['composite_id'],
                'source_order_id': r['source_order_id'],
                'order_no': r['order_no'],
                'customer': r['customer'],
                'customer_name': r['customer_name'],
                'product_id': r['product_id'],
                'product_name': pid_name_map.get(r['product_id'], '未知产品'),
                'quantity': r['quantity'],
                'order_date': r['order_date'],
                'has_bom': r['product_id'] in bom_product_ids,
                'create_time': r['create_time'],
                'status': 'pending',
                'record_type': r['record_type'],
            }
            for r in page_records
        ],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


async def get_completed_order_suggestions(
    db: AsyncSession, keyword: str,
) -> list:
    if not keyword:
        return []
    like_pattern = f'%{escape_like(keyword)}%'
    result = await db.execute(
        select(PurchaseOrder.order_no, PurchaseOrder.id).where(
            PurchaseOrder.status == 'completed',
            or_(
                PurchaseOrder.order_no.ilike(like_pattern),
                PurchaseOrder.supplier_name.ilike(like_pattern),
            ),
        ).limit(10)
    )
    return [{'order_no': r.order_no, 'id': r.id} for r in result]


async def get_completed_order_quick_filters(db: AsyncSession) -> dict:
    today = datetime.now(UTC).replace(tzinfo=None).date()
    today_count_result = await db.execute(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.status == 'completed',
            PurchaseOrder.completed_at >= today,
        )
    )
    week_count_result = await db.execute(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.status == 'completed',
            PurchaseOrder.completed_at >= today - timedelta(days=7),
        )
    )
    month_count_result = await db.execute(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.status == 'completed',
            PurchaseOrder.completed_at >= today - timedelta(days=30),
        )
    )
    return {
        'today': today_count_result.scalar() or 0,
        'week': week_count_result.scalar() or 0,
        'month': month_count_result.scalar() or 0,
    }


async def query_supplier_groups(db: AsyncSession, keyword: str = '') -> list:
    """查询供应商分组列表"""
    query = select(
        PurchaseOrder.supplier_name,
        PurchaseOrder.supplier_id,
        func.count(PurchaseOrder.id).label('order_count'),
        func.sum(PurchaseOrder.total_amount).label('total_amount'),
    ).where(PurchaseOrder.status == 'completed')

    if keyword:
        like_pattern = f'%{escape_like(keyword)}%'
        query = query.where(PurchaseOrder.supplier_name.ilike(like_pattern))

    query = query.group_by(PurchaseOrder.supplier_name, PurchaseOrder.supplier_id)
    query = query.order_by(func.sum(PurchaseOrder.total_amount).desc())
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            'supplier_name': r.supplier_name,
            'supplier_id': r.supplier_id,
            'order_count': r.order_count,
            'total_amount': float(r.total_amount or 0),
        }
        for r in rows
    ]
