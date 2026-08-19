"""
采购订单查询 - 公共辅助函数

从 purchase_order_query.py 拆分而来，集中存放被多个查询函数复用的
辅助函数与模块级常量，保持函数体与行为完全不变。
"""
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import cast, exists, func, literal, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.purchase_utils import parse_source_order_ids
from fastapi_app.shared_models import (
    MaterialRegistration,
    MaterialRegistrationItem,
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
    PurchaseOrderItem,
    StockIn,
)
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_item import OrderItem

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


def _is_filling_category(category: str | None) -> bool:
    """判断物料类别是否为填充物（汇总下单只展示面料和辅料，排除填充物）。"""
    if not category:
        return False
    cat = category.strip().lower()
    return cat == 'filling' or '填充' in category


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


async def _build_po_source_fill_and_no_maps(
    db: AsyncSession, orders
) -> tuple[dict[int, tuple[str, int]], dict[int, str]]:
    """合并 fill_map 与 no_map 的 2 次 Order 查询为 1 次。

    Returns:
        (source_order_map, po_source_no_str)
        - source_order_map: {source_order_id: (product_name, quantity)}，仅包含需要回填的订单
        - po_source_no_str: {purchase_order_id: '订单号1、订单号2'}
    """
    po_source_ids_map: dict[int, list[int]] = {}
    all_source_ids: set[int] = set()
    for order in orders:
        ids = _parse_source_order_ids(order)
        po_source_ids_map[order.id] = ids
        all_source_ids.update(ids)
    if not all_source_ids:
        return {}, {}
    # 单次查询：同时取 order_no（给 no_map）和 product_id/quantity（给 fill_map）
    # TODO(multi-sku-order): Order.product_id/quantity 在多 SKU 模型下为首 item 兼容值，
    # source_order_map 当前按 order_id 映射单个 (product_name, quantity)，需在后续 spec
    # 中改造为遍历 Order.items。当前依赖兼容值。
    src_result = await db.execute(
        select(Order.id, Order.order_no, Order.product_id, Order.quantity)
        .where(Order.id.in_(all_source_ids))
    )
    src_rows = src_result.all()
    # no_map: {source_order_id: order_no}
    source_order_no_map = {row.id: row.order_no for row in src_rows if row.order_no}
    # fill_map 的 product_id 需要关联 Product 表查名称
    # 条件与旧 _build_po_source_fill_map 保持一致：仅 product_name 缺失时才回填
    # （quantity 缺失但 product_name 已填的场景在旧实现中同样不回填，保持行为等价）
    orders_needing_fill = {
        o for o in orders
        if not o.product_name and (o.source_order_ids or o.source_order_id)
    }
    fill_source_ids = set()
    for o in orders_needing_fill:
        fill_source_ids.update(po_source_ids_map.get(o.id, []))
    cust_pids = list({row.product_id for row in src_rows if row.product_id and row.id in fill_source_ids})
    pid_name_map: dict[int, str] = {}
    if cust_pids:
        prod_result = await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(cust_pids))
        )
        pid_name_map = dict(prod_result.all())
    source_order_map: dict[int, tuple[str, int]] = {}
    for row in src_rows:
        if row.id in fill_source_ids:
            source_order_map[row.id] = (pid_name_map.get(row.product_id, ''), row.quantity or 0)
    # po_source_no_str 按 purchase_order_id 聚合
    po_source_no_str: dict[int, str] = {}
    for po_id, sids in po_source_ids_map.items():
        nos = [source_order_no_map.get(sid, '') for sid in sids]
        nos = [n for n in nos if n]
        po_source_no_str[po_id] = '、'.join(nos) if nos else ''
    return source_order_map, po_source_no_str


async def _build_po_source_no_map(db: AsyncSession, orders) -> dict[int, str]:
    """单独查询 no_map（仅源订单号聚合）。

    若同时需要 fill_map，请用 _build_po_source_fill_and_no_maps 合并查询以节省 1 次 roundtrip。
    """
    po_source_ids_map: dict[int, list[int]] = {}
    all_source_ids: set[int] = set()
    for order in orders:
        po_source_ids_map[order.id] = _parse_source_order_ids(order)
        all_source_ids.update(po_source_ids_map[order.id])
    if not all_source_ids:
        return {}
    no_result = await db.execute(
        select(Order.id, Order.order_no).where(Order.id.in_(all_source_ids))
    )
    source_order_no_map = dict(no_result.all())
    po_source_no_str: dict[int, str] = {}
    for po_id, sids in po_source_ids_map.items():
        nos = [source_order_no_map.get(sid, '') for sid in sids]
        nos = [n for n in nos if n]
        po_source_no_str[po_id] = '、'.join(nos) if nos else ''
    return po_source_no_str


async def _build_po_source_sku_map(db: AsyncSession, orders) -> dict[int, list[dict]]:
    """根据采购订单关联的源订单，构建每个采购订单的 SKU 明细列表。

    多 SKU 客户订单通过 Order.items 获取；备货记录(StockIn)无 items，回退到
    product_id/quantity 兼容字段。
    """
    po_source_ids_map: dict[int, list[int]] = {}
    all_source_ids: set[int] = set()
    for order in orders:
        ids = _parse_source_order_ids(order)
        po_source_ids_map[order.id] = ids
        all_source_ids.update(ids)
    if not all_source_ids:
        return {}

    # 1) 优先查询 OrderItem（多 SKU 模型）
    item_result = await db.execute(
        select(OrderItem, Product.barcode)
        .join(Product, OrderItem.product_id == Product.id)
        .where(OrderItem.order_id.in_(all_source_ids))
        .order_by(OrderItem.order_id, OrderItem.id)
    )
    items_by_source: dict[int, list[dict]] = defaultdict(list)
    covered_source_ids: set[int] = set()
    for item, barcode in item_result.all():
        items_by_source[item.order_id].append({
            'product_name': item.product_name or '',
            'barcode': barcode or item.product_barcode or '',
            'quantity': float(item.quantity or 0),
            'order_type': item.order_type or 'regular',
            'country': item.country or '',
        })
        covered_source_ids.add(item.order_id)

    # 2) 无 OrderItem 的 source_id 回退到 Order/StockIn 兼容字段
    fallback_ids = all_source_ids - covered_source_ids
    if fallback_ids:
        order_result = await db.execute(
            select(Order.id, Order.product_id, Order.quantity, Product.name, Product.barcode)
            .join(Product, Order.product_id == Product.id)
            .where(Order.id.in_(fallback_ids))
        )
        for row in order_result.all():
            items_by_source[row.id].append({
                'product_name': row.name or '',
                'barcode': row.barcode or '',
                'quantity': float(row.quantity or 0),
                'order_type': 'regular',
                'country': '',
            })
            covered_source_ids.add(row.id)

        stockin_fallback_ids = fallback_ids - covered_source_ids
        if stockin_fallback_ids:
            stockin_result = await db.execute(
                select(StockIn.id, StockIn.product_id, StockIn.quantity, Product.name, Product.barcode)
                .join(Product, StockIn.product_id == Product.id)
                .where(StockIn.id.in_(stockin_fallback_ids))
            )
            for row in stockin_result.all():
                items_by_source[row.id].append({
                    'product_name': row.name or '',
                    'barcode': row.barcode or '',
                    'quantity': float(row.quantity or 0),
                    'order_type': 'stockin',
                    'country': '',
                })

    # 3) 按采购订单分组，保持 source_order_ids 顺序，并合并重复 SKU
    po_sku_map: dict[int, list[dict]] = {}
    for po_id, source_ids in po_source_ids_map.items():
        skus: list[dict] = []
        for sid in source_ids:
            skus.extend(items_by_source.get(sid, []))
        merged_skus = _merge_duplicate_skus(skus)
        po_sku_map[po_id] = merged_skus
        logger.info(
            "[po-sku] po_id=%d source_ids=%s raw_skus=%d merged_skus=%d",
            po_id, source_ids, len(skus), len(merged_skus),
        )
    return po_sku_map


def _merge_duplicate_skus(skus: list[dict]) -> list[dict]:
    """合并同一采购订单内产品名称和条码重复的 SKU 行，数量累加。"""
    key_map: dict[tuple[str, str], dict] = {}
    for sku in skus:
        key = (sku['product_name'], sku['barcode'])
        if key in key_map:
            key_map[key]['quantity'] += sku['quantity']
        else:
            key_map[key] = sku.copy()
    merged = list(key_map.values())
    if len(merged) != len(skus):
        logger.debug(
            "[merge-sku] before=%d after=%d merged=%s",
            len(skus), len(merged), merged,
        )
    return merged


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


def _serialize_po_list_item(order, items, product_name, quantity, source_order_no, sku_items=None) -> dict:
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
        'sku_items': sku_items or [],
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
            # TODO(multi-sku-order): Order.product_id/quantity 在多 SKU 下为首 item 兼容值，待后续 spec 改造为遍历 Order.items。
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


def _build_po_items_map(all_items) -> dict[tuple, list]:
    items_map: dict[tuple, list] = {}
    for item in all_items:
        ikey = (item.order_id, item.material_name, item.specification or '', item.unit or '')
        items_map.setdefault(ikey, []).append(item)
    return items_map


def _build_po_items_by_order(all_items) -> dict[int, list]:
    """按 order_id 分组 PO 明细，用于 BOM 不可用时的回退。"""
    items_by_order: dict[int, list] = {}
    for item in all_items:
        items_by_order.setdefault(item.order_id, []).append(item)
    return items_by_order


async def _fetch_po_items_map(db: AsyncSession, po_ids: list[int]) -> tuple[dict[tuple, list], dict[int, list]]:
    """获取 PO 明细的两种索引：按 (order_id, material, spec, unit) 和按 order_id。"""
    if not po_ids:
        return {}, {}
    items_result = await db.execute(
        select(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(po_ids))
    )
    all_items = items_result.scalars().all()
    return _build_po_items_map(all_items), _build_po_items_by_order(all_items)


async def _fetch_supplier_cust_order_map(db: AsyncSession, orders) -> dict[int, tuple[int, float]]:
    source_order_ids: set[int] = set()
    for po in orders:
        source_order_ids.update(_parse_source_order_ids(po))
    cust_order_map: dict[int, tuple[int, float]] = {}
    if source_order_ids:
        cust_result = await db.execute(
            # TODO(multi-sku-order): Order.product_id/quantity 在多 SKU 下为首 item 兼容值，待后续 spec 改造为遍历 Order.items。
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


def _build_supplier_mat_map(orders, bom_data, items_map, items_by_order, cust_order_map) -> dict[tuple, dict]:
    mat_map: dict[tuple, dict] = {}
    for po in orders:
        order_qty, pid = _resolve_po_qty_and_pid(po, cust_order_map)
        bom_list = bom_data.get(pid, [])
        if bom_list:
            for bom in bom_list:
                if _is_filling_category(bom.get('category')):
                    continue
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
        else:
            # BOM 不可用时回退：直接使用 PO 明细作为物料数据
            for item in items_by_order.get(po.id, []):
                if _is_filling_category(item.material_category):
                    continue
                sup = item.supplier_name or po.supplier_name or '未指定供应商'
                key = (sup, item.material_name, item.specification or '', item.unit or '')
                total_qty = float(item.quantity or 0)
                if key in mat_map:
                    mat_map[key]['total_quantity'] += total_qty
                else:
                    mat_map[key] = {
                        'material_name': item.material_name,
                        'specification': item.specification or '',
                        'total_quantity': total_qty,
                        'unit': item.unit or '',
                        'supplier_name': sup,
                    }
    return mat_map


async def _fetch_factory_cust_order_map(db: AsyncSession, orders) -> dict[int, tuple[int, float, str]]:
    source_order_ids: set[int] = set()
    for po in orders:
        source_order_ids.update(_parse_source_order_ids(po))
    cust_order_map: dict[int, tuple[int, float, str]] = {}
    if source_order_ids:
        cust_result = await db.execute(
            # TODO(multi-sku-order): Order.product_id/quantity 在多 SKU 下为首 item 兼容值，待后续 spec 改造为遍历 Order.items。
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


def _accumulate_factory_po_items(group, po, items_by_order):
    """BOM 不可用时的回退：直接使用 PO 明细作为布料/物料数据。"""
    for item in items_by_order.get(po.id, []):
        if _is_filling_category(item.material_category):
            continue
        sup = item.supplier_name or po.supplier_name or '未指定供应商'
        if sup not in group['_supplier_map']:
            group['_supplier_map'][sup] = {
                'supplier_name': sup,
                '_fabric_map': {},
            }
        fabric_map = group['_supplier_map'][sup]['_fabric_map']
        fkey = (item.material_name, item.specification or '', item.unit or '')
        if fkey in fabric_map:
            fabric_map[fkey]['quantity'] += float(item.quantity or 0)
            if item.id not in fabric_map[fkey]['item_ids']:
                fabric_map[fkey]['item_ids'].append(item.id)
        else:
            fabric_map[fkey] = {
                'fabric_name': item.material_name,
                'specification': item.specification or '',
                'quantity': float(item.quantity or 0),
                'unit': item.unit or '',
                'item_ids': [item.id] if item.id else [],
            }


def _build_factory_group_map(orders, bom_data, items_map, items_by_order, cust_order_map, prod_name_map) -> dict[tuple, dict]:
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
        bom_list = bom_data.get(pid, [])
        if bom_list:
            for bom in bom_list:
                if _is_filling_category(bom.get('category')):
                    continue
                _accumulate_factory_bom(group, po, bom, items_map, order_qty)
        else:
            _accumulate_factory_po_items(group, po, items_by_order)
    return group_map


def _serialize_factory_groups(group_map: dict[tuple, dict]) -> list:
    groups = []
    for key in sorted(group_map.keys()):
        group = group_map[key]
        suppliers = []
        for skey in sorted(group['_supplier_map'].keys()):
            supplier = group['_supplier_map'][skey]
            fabrics = sorted(supplier['_fabric_map'].values(), key=lambda x: x['fabric_name'])
            suppliers.append({'supplier_name': supplier['supplier_name'], 'fabrics': fabrics})
        groups.append({
            'customer_name': group['customer_name'],
            'product_name': group['product_name'],
            'product_quantity': group['product_quantity'],
            'order_quantity': group['order_quantity'],
            'suppliers': suppliers,
        })
    return groups


def _build_not_processed_filter(id_column):
    """构建 NOT EXISTS 子查询：排除已被采购订单关联的记录。

    P-6 优化：用 JSONB @> 操作符在数据库层检查 ID 是否出现在
    purchase_order.source_order_ids 中，替代预查询 + .notin_() 方案。

    优势：
    - 无 SQL 参数上限风险（PostgreSQL IN 列表上限约 32767）
    - 无需预查询 + 30s 缓存，结果实时准确
    - GIN 表达式索引 (source_order_ids::jsonb) 保证性能

    正则预过滤防御无效 JSON，与 P-7 的 CASE 策略等价但表达式不变
    （WHERE 条件不影响 GIN 表达式索引匹配）。
    """
    return ~exists(
        select(literal('1'))
        .select_from(PurchaseOrder)
        .where(PurchaseOrder.source_order_ids.isnot(None))
        .where(PurchaseOrder.source_order_ids.op('~')(r'^\s*\['))
        .where(
            cast(PurchaseOrder.source_order_ids, JSONB).op('@>')(
                func.jsonb_build_array(id_column)
            )
        )
    )


def _build_unprocessed_order_record(order) -> dict:
    # 多 SKU 模型：返回所有 OrderItem，前端按 SKU 行展示。
    # 顶层 product_id/product_name/quantity 保留首个 SKU 值，用于兼容旧前端字段。
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
        'composite_id': f"order:{order.id}",
        'source_order_id': order.id,
        'order_no': order.order_no,
        'customer': order.customer,
        'customer_name': order.customer,
        'product_id': first_item.product_id if first_item else None,
        'product_name': first_item.product_name if first_item else None,
        'quantity': first_item.quantity if first_item else 0,
        'order_date': order.order_date.strftime('%Y-%m-%d') if order.order_date else '',
        'create_time': order.order_date.strftime('%Y-%m-%d %H:%M') if order.order_date else '',
        'record_type': 'order',
        'items': items_data,
        'sku_count': len(items_data),
    }


def _build_unprocessed_stockin_record(stockin) -> dict:
    # StockIn 为单 SKU，统一封装为 items 列表，便于前端复用多 SKU 渲染逻辑
    items_data = [{
        'id': stockin.id,
        'product_id': stockin.product_id,
        'product_name': None,  # 由调用方批量查询 Product 后填充
        'product_barcode': None,
        'quantity': stockin.quantity,
        'order_type': stockin.order_type,
        'country': stockin.country or '',
        'deduct_quantity': 0,
        'note': stockin.note or '',
    }]
    return {
        'id': stockin.id,
        'composite_id': f"stockin:{stockin.id}",
        'source_order_id': stockin.id,
        'order_no': stockin.stockin_no,
        'customer': stockin.customer,
        'customer_name': stockin.customer,
        'product_id': stockin.product_id,
        'product_name': None,
        'quantity': stockin.quantity,
        'order_date': stockin.stockin_date.strftime('%Y-%m-%d') if stockin.stockin_date else '',
        'create_time': stockin.stockin_date.strftime('%Y-%m-%d %H:%M') if stockin.stockin_date else '',
        'record_type': 'stockin',
        'items': items_data,
        'sku_count': 1,
    }


async def _fetch_bom_product_ids(db: AsyncSession, product_ids: list) -> set[int]:
    if not product_ids:
        return set()
    # UNION ALL 单次查询：合并填充物/面料/辅料三张 BOM 子表的 product_id
    stmt = union_all(
        select(ProductMaterial.product_id).where(ProductMaterial.product_id.in_(product_ids)),
        select(ProductFabric.product_id).where(ProductFabric.product_id.in_(product_ids)),
        select(ProductAccessory.product_id).where(ProductAccessory.product_id.in_(product_ids)),
    )
    result = await db.execute(stmt)
    return {row[0] for row in result}
