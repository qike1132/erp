"""
采购订单查询操作（对外查询函数 + 兼容 re-export）

职责：采购订单的列表查询、详情查询、汇总统计、导出等读操作。
从 purchase_order_service.py 拆分而来，保持函数签名不变。

本文件保留全部对外查询主函数；公共辅助函数已迁移至
purchase_order_query_helpers.py，并在文件末尾 re-export，
确保 `from fastapi_app.services.purchase_order_query import X`
（X 为任意原函数名/模块级常量）保持兼容。
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.cache import cache_result
from fastapi_app.core.sanitizer import escape_like
from fastapi_app.shared_models import PurchaseOrder, PurchaseOrderItem
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK
from fastapi_app.shared_models.purchase_order import PurchaseOrderStatus
from fastapi_app.utils import calc_total_pages


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
    # 合并 fill_map 与 no_map 的 2 次 Order 查询为 1 次
    source_order_map, po_source_no_str = await _build_po_source_fill_and_no_maps(db, orders)
    po_source_sku_map = await _build_po_source_sku_map(db, orders)

    order_list = []
    for order in orders:
        items = items_by_order.get(order.id, [])
        product_name, quantity = _resolve_po_product_name_qty(order, source_order_map)
        order_list.append(_serialize_po_list_item(
            order, items, product_name, quantity, po_source_no_str.get(order.id, ''),
            sku_items=po_source_sku_map.get(order.id, []),
        ))

    return {
        'orders': order_list,
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


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

    po_sku_map = await _build_po_source_sku_map(db, [order])

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
        'sku_items': po_sku_map.get(order.id, []),
    }


async def get_completed_purchase_orders(
    db: AsyncSession, *, page: int = 1, per_page: int = 20,
    supplier_id: int | None = None, keyword: str = '',
    date_from: str = '', date_to: str = '',
    order_no: str = '', customer_name: str = '',
    product_name: str = '', supplier_name: str = '',
    barcode: str = '', material_name: str = '',
    start_date: str = '', end_date: str = '',
    quick_filter: str = '', is_arrived: str = '',
    sort_by: str = 'completed_at', sort_order: str = 'desc',
) -> dict:
    query = select(PurchaseOrder).where(PurchaseOrder.status == PurchaseOrderStatus.COMPLETED)
    count_query = select(func.count(PurchaseOrder.id)).where(PurchaseOrder.status == PurchaseOrderStatus.COMPLETED)
    query, count_query = _apply_completed_filters(
        query, count_query, supplier_id=supplier_id, keyword=keyword,
        date_from=date_from, date_to=date_to,
        order_no=order_no, customer_name=customer_name,
        product_name=product_name, supplier_name=supplier_name,
        barcode=barcode, material_name=material_name,
        start_date=start_date, end_date=end_date,
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
    po_sku_map = await _build_po_source_sku_map(db, orders)

    order_list = []
    for order in orders:
        items = items_by_order.get(order.id, [])
        order_list.append(_serialize_completed_order(
            order, items, arrived_map, po_source_no_str.get(order.id, ''),
            po_sku_map.get(order.id, []),
        ))

    return {
        'orders': order_list,
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }


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
    items_map, items_by_order = await _fetch_po_items_map(db, po_ids)

    mat_map = _build_supplier_mat_map(orders, bom_data, items_map, items_by_order, cust_order_map)
    materials = sorted(mat_map.values(), key=lambda x: (x['supplier_name'], x['material_name']))
    return {'materials': materials, 'order_count': len(orders)}


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
    items_map, items_by_order = await _fetch_po_items_map(db, po_ids)

    group_map = _build_factory_group_map(orders, bom_data, items_map, items_by_order, cust_order_map, prod_name_map)
    groups = _serialize_factory_groups(group_map)

    return {'groups': groups, 'order_count': len(orders)}


async def export_completed_orders(
    db: AsyncSession, *, supplier_id: int | None = None,
    date_from: str = '', date_to: str = '',
) -> list:
    # 只查需要的列，避免大量 ORM 实例驻留内存（防 OOM）
    order_cols = (
        PurchaseOrder.id, PurchaseOrder.order_no, PurchaseOrder.supplier_name,
        PurchaseOrder.customer_name, PurchaseOrder.completed_at,
    )
    query = select(*order_cols).where(PurchaseOrder.status == PurchaseOrderStatus.COMPLETED)
    if supplier_id:
        query = query.where(PurchaseOrder.supplier_id == supplier_id)
    if date_from:
        query = query.where(PurchaseOrder.completed_at >= date_from)
    if date_to:
        query = query.where(PurchaseOrder.completed_at <= f'{date_to} 23:59:59')  # sql-safe: escape_like/绑定参数/常量片段
    query = query.order_by(PurchaseOrder.completed_at.desc())

    result = await db.execute(query)
    orders = result.all()

    rows = []
    order_ids = [o.id for o in orders]

    if order_ids:
        # 明细也只查导出所需列
        item_cols = (
            PurchaseOrderItem.order_id, PurchaseOrderItem.material_name,
            PurchaseOrderItem.material_code, PurchaseOrderItem.specification,
            PurchaseOrderItem.unit, PurchaseOrderItem.quantity,
            PurchaseOrderItem.unit_price, PurchaseOrderItem.total_price,
        )
        items_result = await db.execute(
            select(*item_cols).where(PurchaseOrderItem.order_id.in_(order_ids))
        )
        items_by_order: dict[int, list] = {}
        for item in items_result.all():
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

    P-1 优化：UNION ALL 将 Order + StockIn 合并为单次 SQL 查询，
    数据库层完成排序 + LIMIT/OFFSET 分页，避免全量加载到内存。
    仅对当前页的 Order 批量查询 items（selectinload），内存 O(页大小)。

    P-6 优化：用 NOT EXISTS + JSONB @> 子查询替代预查询 + .notin_()，
    消除 SQL 参数上限风险，结果实时准确，无需 30s 缓存。
    """
    from fastapi_app.shared_models import Order as CustomerOrder
    from fastapi_app.shared_models import Product, StockIn

    # ---- 构建 UNION ALL 子查询（轻量列，数据库层排序+分页）----
    # Order 部分：status='待备货' 且未删除，NOT EXISTS 排除已被采购单关联的 ID
    order_part = select(
        literal('order').label('record_type'),
        CustomerOrder.id.label('source_id'),
        CustomerOrder.order_no.label('order_no'),
        CustomerOrder.customer.label('customer'),
        CustomerOrder.order_date.label('sort_date'),
    ).where(
        CustomerOrder.status == ORDER_STATUS_PENDING_STOCK,
        CustomerOrder.is_deleted == False,  # noqa: E712
        _build_not_processed_filter(CustomerOrder.id),
    )

    # StockIn 部分：NOT EXISTS 排除已被采购单 source_order_ids 关联的 ID
    # （source_order_ids 中可能同时包含 Order ID 和 StockIn ID）
    stockin_part = select(
        literal('stockin').label('record_type'),
        StockIn.id.label('source_id'),
        StockIn.stockin_no.label('order_no'),
        StockIn.customer.label('customer'),
        StockIn.stockin_date.label('sort_date'),
    ).where(_build_not_processed_filter(StockIn.id))

    unified = union_all(order_part, stockin_part).subquery()

    # ---- 1. COUNT 总数（单次查询）----
    count_result = await db.execute(select(func.count()).select_from(unified))
    total = count_result.scalar() or 0

    if total == 0:
        return {
            'orders': [],
            'total': 0,
            'pages': calc_total_pages(0, per_page),
            'current_page': page,
        }

    # ---- 2. 分页查询当前页（数据库层排序 + LIMIT/OFFSET）----
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
        return {
            'orders': [],
            'total': total,
            'pages': calc_total_pages(total, per_page),
            'current_page': page,
        }

    # ---- 3. 按来源批量查询当前页完整数据 ----
    order_ids = [r.source_id for r in rows if r.record_type == 'order']
    stockin_ids = [r.source_id for r in rows if r.record_type == 'stockin']

    orders_map: dict[int, CustomerOrder] = {}
    if order_ids:
        order_result = await db.execute(
            select(CustomerOrder)
            .options(selectinload(CustomerOrder.items))
            .where(CustomerOrder.id.in_(order_ids))
        )
        for o in order_result.scalars().unique():
            orders_map[o.id] = o

    stockins_map: dict[int, StockIn] = {}
    if stockin_ids:
        stockin_result = await db.execute(
            select(StockIn).where(StockIn.id.in_(stockin_ids))
        )
        for s in stockin_result.scalars():
            stockins_map[s.id] = s

    # ---- 4. 按 SQL 排序顺序构建记录 ----
    all_records: list[dict] = []
    for r in rows:
        if r.record_type == 'order':
            o = orders_map.get(r.source_id)
            if o:
                all_records.append(_build_unprocessed_order_record(o))
        else:
            s = stockins_map.get(r.source_id)
            if s:
                all_records.append(_build_unprocessed_stockin_record(s))

    # ---- 5. 批量查询产品名称（覆盖所有 SKU 的 product_id）----
    product_ids_set: set[int] = set()
    for r in all_records:
        if r.get('product_id'):
            product_ids_set.add(r['product_id'])
        for item in r.get('items', []):
            if item.get('product_id'):
                product_ids_set.add(item['product_id'])
    product_ids = list(product_ids_set)
    pid_name_map: dict[int, str] = {}
    pid_barcode_map: dict[int, str] = {}
    if product_ids:
        prod_result = await db.execute(
            select(Product.id, Product.name, Product.barcode).where(Product.id.in_(product_ids))
        )
        for row in prod_result.all():
            pid_name_map[row[0]] = row[1]
            if row[2]:
                pid_barcode_map[row[0]] = row[2]

    # 批量查询 BOM 信息
    bom_product_ids = await _fetch_bom_product_ids(db, product_ids)

    def _enrich_items(items: list) -> list:
        enriched = []
        for item in items:
            pid = item.get('product_id')
            enriched.append({
                **item,
                'product_name': item.get('product_name') or pid_name_map.get(pid, '未知产品') if pid else '未知产品',
                'product_barcode': item.get('product_barcode') or pid_barcode_map.get(pid) if pid else None,
                'has_bom': pid in bom_product_ids if pid else False,
            })
        return enriched

    def _compute_order_has_bom(r: dict) -> bool:
        items = r.get('items') or []
        if not items:
            # 兼容无 items 的旧记录：按顶层 product_id 判断
            return r.get('product_id') in bom_product_ids if r.get('product_id') else False
        # 多 SKU：所有 SKU 均需配置 BOM，否则该单无法审核
        return all(item['product_id'] in bom_product_ids for item in items if item.get('product_id'))

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
                'product_name': pid_name_map.get(r['product_id'], '未知产品') if r['product_id'] else '未知产品',
                'quantity': r['quantity'],
                'order_date': r['order_date'],
                'has_bom': _compute_order_has_bom(r),
                'create_time': r['create_time'],
                'status': 'pending',
                'record_type': r['record_type'],
                'sku_count': r.get('sku_count', 1),
                'items': _enrich_items(r.get('items', [])),
            }
            for r in all_records
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
            PurchaseOrder.status == PurchaseOrderStatus.COMPLETED,
            or_(
                PurchaseOrder.order_no.ilike(like_pattern),
                PurchaseOrder.supplier_name.ilike(like_pattern),
            ),
        ).limit(10)
    )
    return [{'order_no': r.order_no, 'id': r.id} for r in result]


async def get_completed_order_quick_filters(db: AsyncSession) -> dict:
    today = datetime.now(UTC).replace(tzinfo=None).date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)
    # 单次查询 + 条件聚合：3 个 COUNT 合并为 1 次 roundtrip
    # 全局 WHERE status='completed' 缩小扫描行集，FILTER 仅按时间区分
    result = await db.execute(
        select(
            func.count(PurchaseOrder.id).filter(
                PurchaseOrder.completed_at >= today,
            ).label('today'),
            func.count(PurchaseOrder.id).filter(
                PurchaseOrder.completed_at >= week_ago,
            ).label('week'),
            func.count(PurchaseOrder.id).filter(
                PurchaseOrder.completed_at >= month_ago,
            ).label('month'),
        ).where(PurchaseOrder.status == PurchaseOrderStatus.COMPLETED)
    )
    row = result.one()
    return {
        'today': row.today or 0,
        'week': row.week or 0,
        'month': row.month or 0,
    }


async def query_supplier_groups(db: AsyncSession, keyword: str = '') -> list:
    """查询供应商分组列表"""
    query = select(
        PurchaseOrder.supplier_name,
        PurchaseOrder.supplier_id,
        func.count(PurchaseOrder.id).label('order_count'),
        func.sum(PurchaseOrder.total_amount).label('total_amount'),
    ).where(PurchaseOrder.status == PurchaseOrderStatus.COMPLETED)

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


# ===== 兼容 re-export：辅助函数与常量已迁移至 purchase_order_query_helpers.py =====
from fastapi_app.services.purchase_order_query_helpers import (  # noqa: F401
    _COMPLETED_SORT_MAP,
    _PO_SORT_MAP,
    _QUICK_FILTER_DAYS,
    _accumulate_factory_bom,
    _accumulate_factory_po_items,
    _apply_completed_filters,
    _apply_completed_quick_filter,
    _apply_po_list_filters,
    _apply_po_sort,
    _build_factory_group_map,
    _build_not_processed_filter,
    _build_po_items_by_order,
    _build_po_items_map,
    _build_po_source_fill_and_no_maps,
    _build_po_source_no_map,
    _build_po_source_sku_map,
    _build_supplier_mat_map,
    _build_unprocessed_order_record,
    _build_unprocessed_stockin_record,
    _fetch_bom_data,
    _fetch_bom_product_ids,
    _fetch_completed_items_and_arrived,
    _fetch_factory_cust_order_map,
    _fetch_po_items_by_order,
    _fetch_po_items_map,
    _fetch_prod_name_map,
    _fetch_supplier_cust_order_map,
    _is_filling_category,
    _merge_duplicate_skus,
    _parse_source_order_ids,
    _resolve_factory_po_info,
    _resolve_factory_source_info,
    _resolve_po_detail_product_name_qty,
    _resolve_po_product_name_qty,
    _resolve_po_qty_and_pid,
    _serialize_completed_item,
    _serialize_completed_order,
    _serialize_factory_groups,
    _serialize_po_item,
    _serialize_po_list_item,
)
