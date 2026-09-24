"""采购订单列表查询辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.sanitizer import escape_like
from fastapi_app.services.purchase._common import _parse_source_order_ids
from fastapi_app.shared_models import (
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

_PO_SORT_MAP = {
    'create_time': PurchaseOrder.create_time,
    'order_no': PurchaseOrder.order_no,
    'total_amount': PurchaseOrder.total_amount,
}


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
