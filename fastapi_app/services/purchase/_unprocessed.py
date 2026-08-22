"""采购未处理记录辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import cast, exists, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.shared_models import (
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
    PurchaseOrder,
)

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