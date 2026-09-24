"""采购订单工厂维度辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.services.purchase._common import _parse_source_order_ids
from fastapi_app.services.purchase._list import _is_filling_category
from fastapi_app.services.purchase_order_sku import merge_sku_lines
from fastapi_app.shared_models import Product
from fastapi_app.shared_models.order import Order

logger = logging.getLogger(__name__)


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
    prod = po.product_name or ''
    order_qty = float(po.product_quantity or 0)
    pid, cust, order_qty = _resolve_factory_source_info(po, cust_order_map, cust, order_qty)
    # 产品名以采购单主表为准（多 SKU 时为 '、' 拼接的完整清单）。
    # 绝不能用「首个 SKU 的产品名」覆盖它：那会把 4 个 SKU 的采购单显示成 1 个 SKU
    # （历史缺陷：`prod = prod_name_map[pid]` 无条件覆盖 → 「汇总下单只有一个 SKU」）。
    # 仅在主表 product_name 为空（旧数据 / 无快照）时才退化到来源产品名。
    if not prod and pid and pid in prod_name_map:
        prod = prod_name_map[pid]
    return cust, prod or '未知产品', order_qty, pid

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

def _build_factory_group_map(orders, bom_data, items_map, items_by_order, cust_order_map,
                             prod_name_map, po_pids_map=None, po_sku_map=None) -> dict[tuple, dict]:
    """构建 (客户, 产品名) → 汇总分组。

    ``po_pids_map``（``{po_id: [product_id, ...]}``）给出该采购单覆盖的**全部 SKU**，
    物料集合取各 SKU BOM 的并集，避免多 SKU 采购单只展开首个 SKU 的物料（漏料）。
    未传该参数时退化为「首个 SKU」的旧口径，保证其它调用方零行为变化。

    ``po_sku_map``（``{po_id: [{product_name, product_barcode, order_qty}, ...]}``）
    给出**逐 SKU 展示明细**，装配到 ``group['skus']`` 供前端逐 SKU 分行；
    缺省该参数或某单无明细时，回退为「订单级单行」——前端因此无需做兼容分支。

    **跨 SKU 去重**：物料数量优先取采购单明细（``items_map``，含人工编辑后的真值），
    而该明细是**跨 SKU 合并**后的结果 —— 同一 (物料,规格,单位) 在多个 SKU 的 BOM 中
    重复出现时必须只累加一次，否则数量翻倍。第 1 个 SKU 保持原累加路径（含同 SKU 内
    多角色重复行的既有行为），从第 2 个 SKU 起跳过已出现过的物料键。
    """
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
                '_sku_lines': [],
            }
        group = group_map[key]

        # 逐 SKU 展示明细：优先取逐 SKU 快照，缺失时回退订单级单行
        sku_lines = (po_sku_map or {}).get(po.id) or []
        if sku_lines:
            group['_sku_lines'].extend(sku_lines)
        else:
            group['_sku_lines'].append({
                'product_name': prod, 'product_barcode': '', 'order_qty': order_qty,
            })

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
                skey = (
                    bom['supplier_name'] or po.supplier_name or '未指定供应商',
                    bom['material_name'], bom['specification'], bom['unit'],
                )
                # 第 1 个 SKU 走原累加路径（保持同 SKU 内多角色重复行的既有行为），
                # 从第 2 个 SKU 起跳过已出现过的物料键。注意：**必须先判重再登记**，
                # 否则首个 SKU 的键不登记，第 2 个 SKU 会再累加一次（数量翻倍）。
                if idx > 0 and skey in seen_materials:
                    continue
                seen_materials.add(skey)
                _accumulate_factory_bom(group, po, bom, items_map, order_qty)

        if not has_bom:
            # BOM 完全不可用（所选 SKU 均未配 BOM）时的既有回退
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
            # 逐 SKU 展示明细（前端逐 SKU 分行 + 合计子行）。
            # 注意：逐 SKU 只有**订单数量**是权威的；物料数量在采购单侧是跨 SKU 合并值，
            # 无法拆分到 SKU，故物料仍按订单级展示（与 /beile-order 已确立的口径一致）。
            'skus': merge_sku_lines(group.get('_sku_lines') or []),
        })
    return groups
