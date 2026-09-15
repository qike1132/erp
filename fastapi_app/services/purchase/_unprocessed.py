"""采购未处理记录辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。

2026-09-14：`get_unprocessed_orders` 由 152 行拆为编排函数 + 本模块内的辅助函数，
零行为变化（SQL 构造、排序、字段口径、BOM 判定均逐条对齐）。
"""
import logging

from sqlalchemy import cast, desc, exists, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.shared_models import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
)
from fastapi_app.utils import calc_total_pages

logger = logging.getLogger(__name__)


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


def _build_unprocessed_union():
    """构建 Order + StockIn 的 UNION ALL 子查询（轻量列，数据库层排序+分页）。

    P-1：UNION ALL 将 Order + StockIn 合并为单次 SQL，数据库层完成排序 +
    LIMIT/OFFSET，仅对当前页批量查 items（selectinload），内存 O(页大小)。

    两段都用同一个 NOT EXISTS 过滤：`source_order_ids` 中可能同时包含
    Order ID 与 StockIn ID。
    """
    from fastapi_app.shared_models import Order as CustomerOrder
    from fastapi_app.shared_models import StockIn
    from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK

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

    stockin_part = select(
        literal('stockin').label('record_type'),
        StockIn.id.label('source_id'),
        StockIn.stockin_no.label('order_no'),
        StockIn.customer.label('customer'),
        StockIn.stockin_date.label('sort_date'),
    ).where(_build_not_processed_filter(StockIn.id))

    return union_all(order_part, stockin_part).subquery()


async def _count_unprocessed(db: AsyncSession, unified) -> int:
    """COUNT 总数（单次查询）。"""
    count_result = await db.execute(select(func.count()).select_from(unified))
    return count_result.scalar() or 0


async def _fetch_unprocessed_page(db: AsyncSession, unified, page: int, per_page: int) -> list:
    """数据库层排序（日期降序，NULL 最后）+ LIMIT/OFFSET 取当前页。"""
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
    return page_result.all()


async def _load_unprocessed_sources(db: AsyncSession, rows: list) -> tuple[dict, dict]:
    """按来源批量查询当前页的完整数据，返回 (orders_map, stockins_map)。"""
    from fastapi_app.shared_models import Order as CustomerOrder
    from fastapi_app.shared_models import StockIn

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
    return orders_map, stockins_map


def _build_records_in_sql_order(rows: list, orders_map: dict, stockins_map: dict) -> list[dict]:
    """按 SQL 的排序结果构建记录列表（顺序即分页顺序，不得重排）。"""
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
    return all_records


def _collect_record_product_ids(all_records: list) -> list[int]:
    """收集顶层与各 SKU 的 product_id（必须覆盖所有 SKU，而非仅首个）。"""
    product_ids_set: set[int] = set()
    for r in all_records:
        if r.get('product_id'):
            product_ids_set.add(r['product_id'])
        for item in r.get('items', []):
            if item.get('product_id'):
                product_ids_set.add(item['product_id'])
    return list(product_ids_set)


async def _fetch_product_name_barcode(db: AsyncSession, product_ids: list) -> tuple[dict, dict]:
    """批量查询产品名与条码，返回 (pid_name_map, pid_barcode_map)。"""
    from fastapi_app.shared_models import Product

    pid_name_map: dict[int, str] = {}
    pid_barcode_map: dict[int, str] = {}
    if not product_ids:
        return pid_name_map, pid_barcode_map
    prod_result = await db.execute(
        select(Product.id, Product.name, Product.barcode).where(Product.id.in_(product_ids))
    )
    for row in prod_result.all():
        pid_name_map[row[0]] = row[1]
        if row[2]:
            pid_barcode_map[row[0]] = row[2]
    return pid_name_map, pid_barcode_map


def _enrich_unprocessed_items(
    items: list, pid_name_map: dict, pid_barcode_map: dict, bom_product_ids: set,
) -> list:
    """补全每个 SKU 的产品名/条码/BOM 标记。

    条件表达式与重构前**逐字一致**：`a or b if pid else c` 的分组是
    `(a or b) if pid else c`，不要"顺手"加括号改变求值顺序。
    """
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


def _order_has_bom(record: dict, bom_product_ids: set) -> bool:
    """整单是否可审核：多 SKU 时必须**所有** SKU 都配置了 BOM。"""
    items = record.get('items') or []
    if not items:
        # 兼容无 items 的旧记录：按顶层 product_id 判断
        return record.get('product_id') in bom_product_ids if record.get('product_id') else False
    # 多 SKU：所有 SKU 均需配置 BOM，否则该单无法审核
    return all(item['product_id'] in bom_product_ids for item in items if item.get('product_id'))


def _build_unprocessed_response(
    all_records: list, total: int, per_page: int, page: int,
    pid_name_map: dict, pid_barcode_map: dict, bom_product_ids: set,
) -> dict:
    """组装未处理订单响应体。"""
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
                'has_bom': _order_has_bom(r, bom_product_ids),
                'create_time': r['create_time'],
                'status': 'pending',
                'record_type': r['record_type'],
                'sku_count': r.get('sku_count', 1),
                'items': _enrich_unprocessed_items(
                    r.get('items', []), pid_name_map, pid_barcode_map, bom_product_ids
                ),
            }
            for r in all_records
        ],
        'total': total,
        'pages': calc_total_pages(total, per_page),
        'current_page': page,
    }
