"""采购订单工厂维度辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.float_utils import round_qty
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

def _norm_sku_name(value) -> str:
    """SKU 名归一：仅 strip。**不** casefold —— 产品名要逐字匹配 `Product.name`（全局唯一）。"""
    return str(value or '').strip()


def _sku_material_rows(bom_rows: list, sku_qty: float, supplier_fallback: str) -> list[dict]:
    """把某个 SKU 的 BOM 行展开为「该 SKU 自己的物料行」（口径 A）。

    `quantity` = ``单件用量 × 该 SKU 数量``（**基准量**，不含损耗加放 —— 加放由前端按该
    物料的行损耗率实时做，故这里必须给基准值）。

    口径要点：
    - 过滤填充类（与工厂汇总既有展示口径一致）；
    - **同一 SKU 内多作用域（角色）重复行累加** —— 与生成路径一致；
    - **不同 SKU 之间不合并、不去重** —— 那是采购合计的口径（见
      `_build_factory_group_map` 的 `seen_materials`），本函数只服务「某一个 SKU 要多少料」。

    不查库，也**不抛错**（`bom_rows` 为空时返回 `[]`）。前提：`bom_rows` 由
    `_fetch_bom_data` 产出，其 `material_name/specification/unit/quantity` 键恒存在；
    本函数不做键存在性防御（与既有 `_accumulate_factory_bom` 同一约定）。

    **舍入口径必须与生成路径一致**：生成时 `purchase_order_generate._material_row` 逐
    (SKU, 角色, BOM 行) 执行 `round_qty(usage × qty)`（HALF-UP 2 位）。此处用**同一个**
    `round_qty` 逐行舍入，使「未编辑单的 Σ 按 SKU 推算 == Σ 落库真值」成为构造性事实。
    若此处不舍入，半厘边界会分叉：`usage=0.1235`、每 SKU 10 件 → 落库 `round_qty(1.235)=1.24`
    累计 2.48，而推算 1.235×2=2.47，差 0.01 > 容差 0.005 ⇒ 从未手改过的单也误弹
    「含手工调整」横幅（前端差异对照块的假告警）。
    """
    buckets: dict[tuple, dict] = {}
    for bom in bom_rows or []:
        if _is_filling_category(bom.get('category')):
            continue
        sup = bom.get('supplier_name') or supplier_fallback
        key = (sup, bom['material_name'], bom['specification'], bom['unit'])
        amount = round_qty(float(bom.get('quantity') or 0) * float(sku_qty or 0))
        if key in buckets:
            buckets[key]['quantity'] += amount
        else:
            buckets[key] = {
                'supplier_name': sup,
                'material_name': bom['material_name'],
                'specification': bom['specification'],
                'unit': bom['unit'],
                'quantity': amount,
            }
    # 稳定顺序：与既有 fabrics 的排序口径一致（供应商 → 物料名 → 规格 → 单位）
    return sorted(
        buckets.values(),
        key=lambda r: (r['supplier_name'], r['material_name'], r['specification'], r['unit']),
    )


def _accumulate_factory_sku_materials(
    group: dict, sku_lines: list, po, bom_data: dict, name_to_pid: dict,
) -> None:
    """**逐采购单**累加「按 SKU 的物料明细」，供应商兜底取**本单**的 `po.supplier_name`。

    为什么必须逐单累加（而不是只看首单 / 末单）：

    1. **必须覆盖组内每一张单**：同一分组可能汇聚多张采购单（同客户 + 同拼接产品名），
       显示口径是「各单合并后的数量」（见 ``merge_sku_lines``）。物料若只看首单/末单，
       会与显示的数量自相矛盾，并让前端的数量差异对照块把「没差异」误报成差异。
    2. **供应商归属必须与 fabrics 同源**：``_accumulate_factory_bom`` 的兜底是**本单**的
       `po.supplier_name`。若这里改用「分组级首个 PO 的供应商」做兜底，则当分组汇聚了
       多张不同供应商的采购单、而 BOM 行**没有** supplier_name 时，fabrics 会按各单供应商
       拆成两行，materials 却全落在首个 PO 名下 ⇒ 键漂移 ⇒ 前端该行 `coord=null` 退化成
       只读，且对照块误报「只在落库侧」。故这里**同样取本单供应商**。
    3. **键与累加方式**：SKU 名作外层桶键；物料以
       `(supplier, material_name, specification, unit)` 为内层键 **``+=`` 累加** ——
       多张单共用同一 SKU 名时数量相加（与既有语义一致）。逐单 `round_qty` 后相加，正好
       复现生成路径「逐单、逐 SKU 舍入后再汇总」的落库真值。绝不改回「按 SKU 名整体赋值」
       ——那会丢掉多单累加（Task-1 曾犯的缺陷）。
    """
    for sku in sku_lines:
        sku_name = _norm_sku_name(sku.get('product_name'))
        sku_pid = name_to_pid.get(sku_name)
        if sku_pid is None:
            continue
        sku_qty = float(sku.get('order_qty') or 0)
        supplier_fallback = po.supplier_name or '未指定供应商'
        bucket = group['_sku_materials'].setdefault(sku_name, {})
        for row in _sku_material_rows(bom_data.get(sku_pid) or [], sku_qty, supplier_fallback):
            key = (
                row['supplier_name'], row['material_name'],
                row['specification'], row['unit'],
            )
            if key in bucket:
                bucket[key]['quantity'] += row['quantity']
            else:
                bucket[key] = row


def _finalize_factory_sku_materials(group_map: dict) -> None:
    """把逐单累加的物料桶定稿为**稳定排序**的列表（与 ``_sku_material_rows`` 同序）。

    累加期 ``_sku_materials`` 是 ``{sku_name: {(sup, mat, spec, unit): row}}``（跨单 ``+=``）；
    此处转成 ``{sku_name: [row, ...]}``，排序键与 ``_sku_material_rows`` 一致
    （供应商 → 物料名 → 规格 → 单位），保证块内顺序稳定、且与既有 fabrics 同序。

    解析不出产品（无 pid）的 SKU 留空数组 —— 前端据此回退订单级单块，绝不编造。
    """
    for group in group_map.values():
        group['_sku_materials'] = {
            name: sorted(
                buckets.values(),
                key=lambda r: (r['supplier_name'], r['material_name'], r['specification'], r['unit']),
            )
            for name, buckets in group['_sku_materials'].items()
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
                '_sku_materials': {},
                '_order_ids': [],
            }
        group = group_map[key]
        if po.id not in group['_order_ids']:
            group['_order_ids'].append(po.id)

        # 逐 SKU 展示明细：优先取逐 SKU 快照，缺失时回退订单级单行
        sku_lines = (po_sku_map or {}).get(po.id) or []
        if sku_lines:
            group['_sku_lines'].extend(sku_lines)
        else:
            group['_sku_lines'].append({
                'product_name': prod, 'product_barcode': '', 'order_qty': order_qty,
            })

        # 逐单累加「按 SKU 的物料明细」（细节见 _accumulate_factory_sku_materials）：
        # 供应商兜底取**本单**的 po.supplier_name，与 fabrics 同源同键。
        name_to_pid = {name: pid for pid, name in (prod_name_map or {}).items()}
        _accumulate_factory_sku_materials(group, sku_lines, po, bom_data, name_to_pid)

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

    # 全部采购单累加完毕后，定稿为稳定排序的列表（细节见 helper）
    _finalize_factory_sku_materials(group_map)
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
            'order_ids': list(group.get('_order_ids') or []),
            'suppliers': suppliers,
            # 注意：既有 `suppliers/fabrics` 仍是**跨 SKU 合并的落库真值**（含手工编辑），
            # 前端用它做「实际下单」差异对照与编辑态定位；`skus[].materials` 才是按 SKU
            # 推算的展示口径（BOM 单件用量 × 该 SKU 数量）。
            # 逐 SKU 展示明细（前端逐 SKU 分行 + 合计子行）。新增 `materials`：
            # 该 SKU 自己的物料基准量（口径 A）；解析不出 / 无 BOM 时为空数组，前端回退。
            'skus': [
                {
                    **line,
                    'materials': (group.get('_sku_materials') or {}).get(
                        _norm_sku_name(line.get('product_name'))
                    ) or [],
                }
                for line in merge_sku_lines(group.get('_sku_lines') or [])
            ],
        })
    return groups
