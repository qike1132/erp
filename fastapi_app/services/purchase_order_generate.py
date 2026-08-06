"""
采购订单生成逻辑

职责：根据客户订单/备货记录生成采购订单。
从 purchase_order_service.py 拆分而来，保持函数签名不变。
"""
import json
import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.services.purchase_order_crud import (
    cleanup_orphan_pending_purchase_orders,
    create_purchase_order,
)
from fastapi_app.shared_models import (
    Product,
    ProductAccessory,
    ProductFabric,
    ProductMaterial,
)
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.purchase_order import PurchaseOrder

logger = logging.getLogger(__name__)


def _iter_source_skus(rec) -> list[tuple[int, int | float]]:
    """统一抽取源记录（Order / StockIn）中的 SKU 级 (product_id, quantity) 列表。

    多 SKU 模型下 Order.product_id/quantity 是兼容字段（分别存首个 SKU 的
    product_id 和所有 OrderItem 数量之和），新代码必须遍历 Order.items 才能
    正确生成每个 SKU 的 BOM 物料。StockIn 为单 SKU 记录，无 items 关系，
    直接使用 product_id/quantity。

    返回值: [(product_id, quantity), ...]；订单无 items 时回退到兼容字段。
    """
    items = getattr(rec, 'items', None)
    if items:
        return [(it.product_id, it.quantity) for it in items]
    # StockIn 或无 OrderItem 的旧订单：使用兼容字段
    return [(rec.product_id, rec.quantity)]


async def generate_purchase_orders_from_customer_orders(
    db: AsyncSession, composite_ids: list[str], idempotency_key: str = '',
) -> dict:
    """根据复合 ID 列表生成采购单

    composite_ids 格式为 ['order:5', 'stockin:3', ...]，确保 Order 和 StockIn
    的 ID 不会碰撞。

    idempotency_key 为可选的幂等键，当前由数据库唯一约束 uq_po_pending_dedup
    和 endpoint 层的 IntegrityError 处理保证幂等，此参数保留用于未来扩展。
    """
    if not composite_ids:
        raise ValueError('未选择任何订单')

    from fastapi_app.shared_models import StockIn

    # 拆分复合 ID
    order_ids: list[int] = []
    stockin_ids: list[int] = []
    for cid in composite_ids:
        if ':' in cid:
            rtype, rid_str = cid.split(':', 1)
            rid = int(rid_str)
            if rtype == 'stockin':
                stockin_ids.append(rid)
            else:
                order_ids.append(rid)
        else:
            # 兼容旧格式（纯数字 ID，视为 Order ID）
            order_ids.append(int(cid))

    # 分别查询 Order 和 StockIn
    cust_orders = []
    if order_ids:
        cust_result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id.in_(order_ids))
        )
        cust_orders = cust_result.scalars().all()

    stockins = []
    if stockin_ids:
        stockin_result = await db.execute(
            select(StockIn).where(StockIn.id.in_(stockin_ids))
        )
        stockins = stockin_result.scalars().all()

    # 验证订单状态
    invalid_orders = [o for o in cust_orders if o.status != '待备货']
    if invalid_orders:
        raise ValueError(f'订单 {invalid_orders[0].order_no} 当前状态为"{invalid_orders[0].status}"，仅"待备货"状态可审核')

    # 合并所有记录（Order + StockIn）用于物料计算
    all_source_records = list(cust_orders) + list(stockins)
    # 多 SKU 模型：必须遍历 Order.items 收集所有 SKU 的 product_id，
    # 否则只会取到 Order.product_id（首个 SKU），遗漏其他 SKU 的 BOM。
    product_ids_set: set[int] = set()
    for r in all_source_records:
        for pid, _qty in _iter_source_skus(r):
            product_ids_set.add(pid)
    product_ids = list(product_ids_set)
    pid_name_map: dict[int, str] = {}
    if product_ids:
        prod_result = await db.execute(
            select(Product.id, Product.name).where(Product.id.in_(product_ids))
        )
        pid_name_map = dict(prod_result.all())

    filling_map: dict[int, list] = {}
    fabric_map: dict[int, list] = {}
    accessory_map: dict[int, list] = {}

    if product_ids:
        fill_result = await db.execute(
            select(ProductMaterial).where(ProductMaterial.product_id.in_(product_ids))
        )
        for row in fill_result.scalars().all():
            filling_map.setdefault(row.product_id, []).append(row)

        fab_result = await db.execute(
            select(ProductFabric).where(ProductFabric.product_id.in_(product_ids))
        )
        for row in fab_result.scalars().all():
            fabric_map.setdefault(row.product_id, []).append(row)

        acc_result = await db.execute(
            select(ProductAccessory).where(ProductAccessory.product_id.in_(product_ids))
        )
        for row in acc_result.scalars().all():
            accessory_map.setdefault(row.product_id, []).append(row)

    def _build_items(records: list) -> list:
        """为给定记录列表构建物料项。

        多 SKU 模型：遍历每条记录的所有 SKU（Order.items 或 StockIn 单 SKU），
        为每个 SKU 独立查询 BOM 并按其自身数量计算物料用量。
        """
        result_items = []
        for rec in records:
            customer_name = rec.customer
            # 按 SKU 粒度迭代，确保多 SKU 订单的每个 SKU 都生成 BOM 物料
            for pid, qty in _iter_source_skus(rec):
                product_name = pid_name_map.get(pid, '未知产品')

                for bom in filling_map.get(pid, []):
                    material_qty = float(bom.cotton_usage or 0) * qty
                    result_items.append({
                        'material_name': product_name + '-填充物',
                        'material_code': bom.material_code or '',
                        'specification': bom.specification or '',
                        'unit': bom.unit or '克',
                        'unit_price': 0,
                        'quantity': material_qty,
                        'supplier_name': bom.supplier_name or '',
                        'supplier_id': bom.supplier_id,
                        'customer_name': customer_name,
                        'category': 'filling',
                        'unit_usage': float(bom.cotton_usage or 0),
                    })

                for fabric in fabric_map.get(pid, []):
                    material_qty = float(fabric.quantity or 0) * qty
                    result_items.append({
                        'material_name': fabric.fabric_name or '面料',
                        'material_code': fabric.material_code or '',
                        'specification': fabric.specification or '',
                        'unit': fabric.unit or '米',
                        'unit_price': 0,
                        'quantity': material_qty,
                        'supplier_name': fabric.supplier_name or '',
                        'supplier_id': fabric.supplier_id,
                        'customer_name': customer_name,
                        'category': 'fabric',
                        'unit_usage': float(fabric.quantity or 0),
                    })

                for acc in accessory_map.get(pid, []):
                    material_qty = float(acc.quantity or 0) * qty
                    result_items.append({
                        'material_name': acc.accessory_name or '配件',
                        'material_code': acc.material_code or '',
                        'specification': acc.specification or '',
                        'unit': acc.unit or '个',
                        'unit_price': 0,
                        'quantity': material_qty,
                        'supplier_name': acc.supplier_name or '',
                        'supplier_id': acc.supplier_id,
                        'customer_name': customer_name,
                        'category': 'accessory',
                        'unit_usage': float(acc.quantity or 0),
                    })
        return result_items

    # 幂等性检查：先清理关联这些客户订单/备货记录的旧 pending 采购单，防止重复审核产生重复订单
    if order_ids or stockin_ids:
        await cleanup_orphan_pending_purchase_orders(
            db, order_ids=order_ids or None, stockin_ids=stockin_ids or None
        )
        # 强制 flush，让 DELETE 在后续 INSERT 之前实际执行，避免唯一约束冲突
        await db.flush()

    all_items = _build_items(all_source_records)
    if not all_items:
        raise ValueError('所选订单的产品未配置BOM物料，无法生成采购单')

    # 按客户分组生成采购单
    customer_groups: dict[str, list] = defaultdict(list)
    for rec in all_source_records:
        customer_groups[rec.customer].append(rec)

    generated_orders = []

    for customer_name, records in customer_groups.items():
        cust_items = _build_items(records)
        if not cust_items:
            continue

        # 多 SKU 模型：按 SKU 粒度收集产品名与数量，避免使用 Order.product_id
        # （仅首个 SKU）和 Order.quantity（所有 SKU 之和）造成统计错误
        product_names = sorted({
            pid_name_map.get(pid, '未知产品')
            for r in records
            for pid, _qty in _iter_source_skus(r)
        })
        total_qty = sum(qty for r in records for _pid, qty in _iter_source_skus(r))

        result = await one_click_generate_order(
            db, cust_items,
            customer_name=customer_name,
            source_order_ids=[r.id for r in records],
            product_name='、'.join(product_names) if len(product_names) > 1 else (product_names[0] if product_names else ''),
            product_quantity=total_qty,
        )
        generated_orders.extend(result.get('orders', []))

    # 更新订单状态
    for o in cust_orders:
        o.status = '已备货'

    # 不在此处 commit，由外层 db_transaction 统一管理事务原子性
    await db.flush()

    return {
        'success': True,
        'message': f'成功生成 {len(generated_orders)} 个采购订单',
        'created_count': len(generated_orders),
        'orders': generated_orders,
    }


async def one_click_generate_order(
    db: AsyncSession, items: list, supplier_stats: dict | None = None,
    customer_name: str = '', source_order_ids: list[int] | None = None,
    product_name: str = '', product_quantity: int | float = 0,
) -> dict:
    if not items:
        raise ValueError('物料列表为空')

    source_ids_json = json.dumps(source_order_ids) if source_order_ids else None

    # 1 个客户订单 = 1 个采购订单，所有供应商的物料作为该订单的明细。
    # 供应商信息保留在 PurchaseOrderItem.supplier_name，/material 页面按明细级别分组显示。
    order = await create_purchase_order(db, {
        'items': items,
        'customer_name': customer_name or items[0].get('customer_name', ''),
        'note': '一键生成',
        'source_order_ids': source_ids_json,
        'product_name': product_name,
        'product_quantity': product_quantity,
    }, include_summary=False, _auto_commit=False)

    return {'orders': [order], 'count': 1}


async def fetch_existing_pending_for_composite_ids(
    db: AsyncSession, composite_ids: list[str],
) -> list[dict]:
    """回查已存在的 pending 采购订单（按 composite_ids 匹配）。

    在 uq_po_pending_dedup 唯一约束命中时，endpoint 层回滚后调用此函数
    以幂等方式返回已存在的 pending 采购单，避免向客户端报错。

    匹配逻辑与 cleanup_orphan_pending_purchase_orders 一致：
    解析 composite_ids → order_ids + stockin_ids → 查询 source_order_ids
    JSON 数组中包含任一目标 ID 的 pending 采购单。
    """
    if not composite_ids:
        return []

    order_ids: list[int] = []
    stockin_ids: list[int] = []
    for cid in composite_ids:
        if ':' in cid:
            rtype, rid_str = cid.split(':', 1)
            rid = int(rid_str)
            if rtype == 'stockin':
                stockin_ids.append(rid)
            else:
                order_ids.append(rid)
        else:
            order_ids.append(int(cid))

    source_ids = order_ids + stockin_ids
    if not source_ids:
        return []

    result = await db.execute(
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.items))
        .where(
            PurchaseOrder.source_order_ids.isnot(None),
            PurchaseOrder.status == 'pending',
        )
    )
    matched: list[dict] = []
    for po in result.scalars().all():
        try:
            ids = json.loads(po.source_order_ids)
        except (ValueError, TypeError):
            continue
        if any(i in source_ids for i in ids):
            matched.append(po.to_dict())
    return matched
