"""采购订单供应商维度辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.purchase._common import _parse_source_order_ids
from fastapi_app.services.purchase._list import _is_filling_category
from fastapi_app.shared_models import PurchaseOrderItem
from fastapi_app.shared_models.order import Order

logger = logging.getLogger(__name__)


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

def _build_supplier_mat_map(orders, bom_data, items_map, items_by_order, cust_order_map,
                            po_pids_map=None) -> dict[tuple, dict]:
    """构建 (供应商, 物料, 规格, 单位) → 汇总物料行。

    ``po_pids_map``（``{po_id: [product_id, ...]}``）给出该采购单覆盖的**全部 SKU**，
    物料集合取各 SKU BOM 的并集；未传时退化为「首个 SKU」的旧口径。
    跨 SKU 去重规则与 ``_factory._build_factory_group_map`` 完全一致：物料数量取
    跨 SKU 合并后的采购单明细，故同一物料键只能累加一次，否则数量翻倍。
    """
    mat_map: dict[tuple, dict] = {}
    for po in orders:
        order_qty, pid = _resolve_po_qty_and_pid(po, cust_order_map)

        if po_pids_map is None:
            pids = [pid] if pid else []
        else:
            pids = list(po_pids_map.get(po.id) or ([pid] if pid else []))

        seen_materials: set[tuple] = set()
        has_bom = False
        for idx, sku_pid in enumerate(pids):
            bom_list = bom_data.get(sku_pid, [])
            if bom_list:
                has_bom = True
            for bom in bom_list:
                if _is_filling_category(bom.get('category')):
                    continue
                sup = bom['supplier_name'] or po.supplier_name or '未指定供应商'
                key = (sup, bom['material_name'], bom['specification'], bom['unit'])
                # 必须先判重再登记（登记不能在 idx==0 时被跳过），否则第 2 个 SKU
                # 会再累加一次同一物料 → 数量翻倍。
                if idx > 0 and key in seen_materials:
                    continue
                seen_materials.add(key)
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

        if not has_bom:
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
