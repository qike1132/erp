"""采购订单工厂维度辅助

从 purchase_order_query_helpers.py 按主题拆出,行为与原实现完全一致。
"""
import logging
from functools import partial

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.float_utils import round_qty
from fastapi_app.services.purchase._common import _parse_source_order_ids
from fastapi_app.services.purchase._list import _is_filling_category
from fastapi_app.services.purchase_order_sku import merge_sku_lines
from fastapi_app.shared_models import Product, ProductRole
from fastapi_app.shared_models.order import Order
from fastapi_app.utils.scope_quantities import allocate_scope_quantities

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
    return dict(prod_result.tuples().all())


async def _fetch_prod_name_and_ratio(
    db: AsyncSession, product_ids: list[int],
) -> tuple[dict[int, str], dict[int, dict]]:
    """一次查询取回产品名与盲盒口径上下文：``({pid: name}, {pid: entry})``。

    合并进原 ``_fetch_prod_name_map`` 的同一次往返（不新增固定查询——工厂汇总有
    「读查询数 ≤10」护栏，见 test_c12）。``entry`` 仅包含**盲盒 SKU**：
    ``{'ratio': P|None, 'has_hidden': bool}``；非盲盒 SKU 不进第二个字典。
    """
    if not product_ids:
        return {}, {}
    prod_result = await db.execute(
        select(
            Product.id, Product.name, Product.hidden_carton_ratio,
            Product.is_blind_box, Product.has_hidden_role,
        ).where(Product.id.in_(product_ids))
    )
    names: dict[int, str] = {}
    blind_ctx: dict[int, dict] = {}
    for pid, name, ratio, is_blind_box, has_hidden_role in prod_result.all():
        names[pid] = name
        if is_blind_box:
            blind_ctx[pid] = {
                'ratio': int(ratio) if ratio else None,
                'has_hidden': bool(has_hidden_role),
            }
    return names, blind_ctx


async def _fetch_roles_ctx(db: AsyncSession, blind_ctx: dict[int, dict]) -> dict[int, dict]:
    """按盲盒 SKU 加载角色名与隐藏款标记。

    返回 ``{pid: {'ratio', 'has_hidden', 'roles': {rid: name}, 'hidden_role_id'}}``。
    只在存在盲盒 SKU 时查询角色表（存量数据零额外查询，既有 SQLite 子集夹具
    无需补 ``product_role`` 表）。
    """
    if not blind_ctx:
        return {}
    role_result = await db.execute(
        select(
            ProductRole.id, ProductRole.product_id,
            ProductRole.role_name, ProductRole.is_hidden,
        ).where(ProductRole.product_id.in_(list(blind_ctx)))
    )
    roles: dict[int, dict[int, str]] = {}
    hidden_roles: dict[int, int] = {}
    for rid, pid, role_name, is_hidden in role_result.all():
        roles.setdefault(pid, {})[rid] = role_name or ''
        if is_hidden:
            hidden_roles[pid] = rid
    return {
        pid: {
            **entry,
            'roles': roles.get(pid, {}),
            # 右键指定的隐藏款（优先于名字识别）
            'hidden_role_id': hidden_roles.get(pid),
        }
        for pid, entry in blind_ctx.items()
    }


def _role_name_from_map(role_names: dict[int, str], rid: int) -> str | None:
    """``partial`` 用的角色名查找（避免 mypy 对闭包 lambda 的推断限制）。"""
    return role_names.get(rid)


def _factory_sku_allocation(ctx_entry: dict, sku_qty: float) -> dict | None:
    """按随箱配比算该 SKU 各作用域的数量乘子；结构非法时告警并回退全量（不阻断页面）。

    工厂汇总展示的是**已存在的采购单**：即使 SKU 当前角色结构不完整（历史脏数据），
    也不得让整页 500——回退历史全量口径只影响推算对照，不影响落库真值。
    """
    role_names = ctx_entry.get('roles') or {}
    try:
        return allocate_scope_quantities(
            sku_qty,
            set(role_names) | {None},
            hidden_carton_ratio=ctx_entry.get('ratio'),
            name_of=partial(_role_name_from_map, role_names),
            hidden_role_id=ctx_entry.get('hidden_role_id'),
            blind_box=True,
            has_hidden=bool(ctx_entry.get('has_hidden')),
        )
    except ValueError:
        logger.warning(
            '工厂汇总按 SKU 推算：陈列样配比分配失败（sku_qty=%s），回退全量口径',
            sku_qty, exc_info=True,
        )
        return None

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

def _norm_part_name(value) -> str:
    """产品部位归一：trim 后作为聚合键；空串表示无部位。"""
    return (value or '').strip()


# 展示用的固定分隔符 / 未标注标记（屏幕、前端打印、后端打印三处共用同一套词汇）。
PART_DISPLAY_SEP = '/'
PART_UNKNOWN_LABEL = '未标注'


def compose_part_display(parts, has_unknown: bool = False) -> str:
    """把「一条聚合行覆盖的全部部位」拼成展示文本。

    为什么需要它（2026-11-05 生产缺陷）：采购明细缺 ``part_name`` 时整组会退化为
    「按物料合并」（``_split_parts_by_group``），聚合键里的部位必须清空才能与无部位的
    明细匹配上，于是 ``part_name`` 恒为空 —— 前端「产品部位」整列空白，把「BOM 明确
    记录了部位」这件事实一起丢掉了。

    口径（**不丢信息 + 不撒谎**）：
    - 聚合行覆盖到的部位**全部列出**，用 ``/`` 连接，去重且保持首次出现顺序
      （BOM 行顺序，用户录入 BOM 的顺序就是最自然的阅读顺序）；
    - 只要**已知**至少一个部位、而该行还有贡献行没标注部位，末尾追加固定标记
      ``未标注`` —— 绝不把「已知的那几个部位」冒充成「这一行的全部部位」；
    - 一个部位都不知道时返回空串（与改动前逐字一致）：整列都没有部位是**数据缺失**，
      此时标 ``未标注`` 只会给每行添一样的噪声，不提供任何信息。

    展示文本**不参与聚合键**（聚合键仍只用 ``part_name``）：否则合并模式下不同 SKU
    覆盖的部位集合不同（A 只用身体、B 只用头部 → ``身体`` vs ``头部``），键会漂移，
    前端拿不到落库坐标 → 行退化成只读并误报「只在落库侧」的数量差异。
    """
    ordered: list[str] = []
    for part in parts or []:
        text = _norm_part_name(part)
        if text and text not in ordered:
            ordered.append(text)
    if has_unknown and ordered:
        ordered.append(PART_UNKNOWN_LABEL)
    return PART_DISPLAY_SEP.join(ordered)


def _new_part_tracking() -> dict:
    """部位展示用的内部记账字段（**不进接口**：finalize 时 pop 掉换成 ``part_display``）。"""
    return {'_part_names': [], '_part_unknown': False}


def _record_part(row: dict, part: str) -> None:
    """登记某聚合行覆盖的一个部位；``part`` 为空表示该贡献行没标注部位。"""
    if not part:
        row['_part_unknown'] = True
        return
    names = row.setdefault('_part_names', [])
    if part not in names:
        names.append(part)


def _merge_part_tracking(target: dict, source: dict) -> None:
    """把 ``source`` 的部位记账并入 ``target``（跨单累加同一聚合键时用）。"""
    for part in source.get('_part_names') or []:
        _record_part(target, part)
    if source.get('_part_unknown'):
        target['_part_unknown'] = True


def _finalize_part_display(row: dict) -> dict:
    """把内部记账字段压成 ``part_display``（接口只暴露这一个展示字段）。返回入参本身。

    **幂等**：行里已经没有任何记账字段 ⇒ 说明这一行定稿过了，此时原样保留既有
    ``part_display``，绝不按「空记账」重算成空串。这条守卫是「二次定稿不抹掉展示」
    的真正保证（``dict(row)`` 副本只保证不破坏源桶的累加态，两者职责不同、都要有）。
    """
    if '_part_names' not in row and '_part_unknown' not in row:
        row.setdefault('part_display', '')
        return row
    row['part_display'] = compose_part_display(
        row.pop('_part_names', []), row.pop('_part_unknown', False),
    )
    return row


def _ensure_fabric_row(group, po, bom, *, split_parts, accumulate):
    """定位（必要时创建）该 BOM 行对应的聚合行，并登记它的展示部位。

    **行定位逻辑只有这一份**：跨 SKU 的只登记分支与正常累加分支共用本函数，
    避免第二套定位代码分叉后两边键算法跑偏（``sup`` / ``fabric_map`` / ``fkey`` /
    建行四件事必须永远一致）。

    Returns:
        ``(row, sup, fkey, part_key)``；``row is None`` 表示「只登记、行却不存在」
        的不可达分支（见下方注释），调用方应直接返回。
    """
    sup = bom['supplier_name'] or po.supplier_name or '未指定供应商'
    if sup not in group['_supplier_map']:
        group['_supplier_map'][sup] = {
            'supplier_name': sup,
            '_fabric_map': {},
        }
    fabric_map = group['_supplier_map'][sup]['_fabric_map']
    # BOM 行自己的部位：它是**展示**的唯一权威来源。
    bom_part = _norm_part_name(bom.get('part_name'))
    # 聚合键里的部位：只在拆行模式下参与，合并模式下必须为空串才能与无部位明细匹配。
    part_key = bom_part if split_parts else ''
    fkey = (bom['material_name'], bom['specification'], bom['unit'], part_key)

    existing = fabric_map.get(fkey)
    if existing is None:
        if not accumulate:
            # 只登记、行却不存在：逻辑上不可达，靠三条不变量支撑 ——
            #   (1) 调用方只在 `skey in seen_materials` 时才传 accumulate=False，
            #   (2) `skey` 与这里的 `fkey` 是同一套算法（供应商 + 物料 + 规格 + 单位 + 部位），
            #   (3) 产生该 skey 的那次正常累加必然已建行（建行在数量累加之前）。
            # 真被破坏时症状只是「部位少标一个」，静默就永远没人发现，故打一条 warning 让
            # 不变量破坏可观测；返回语义不变：**不建行**（建 quantity=0 的幽灵行会在表里
            # 多出一行空物料、还会进「落库侧」比对，比少一个部位标记更糟）、**不抛异常**
            # （展示层面的补登记不该拖垮整个汇总接口）。
            logger.warning(
                'part_tracking_missing_row po_id=%s supplier=%s material=%s spec=%s unit=%s',
                po.id, sup, bom['material_name'], bom['specification'], bom['unit'],
            )
            return None, sup, fkey, part_key
        existing = fabric_map[fkey] = {
            'fabric_name': bom['material_name'],
            'part_name': part_key or None,
            'specification': bom['specification'],
            'quantity': 0.0,
            'unit': bom['unit'],
            'item_ids': [],
            **_new_part_tracking(),
        }
    # **必须先登记部位再判重**：合并模式下同一物料的多条 BOM 行（身体/头部）共享同一个
    # 聚合键，第二条会命中 `_stored_seen` 提前返回；若把登记放在判重之后，
    # 第二条的部位就永远进不了展示文本（生产缺陷的同一根因，换个位置复发）。
    _record_part(existing, bom_part)
    return existing, sup, fkey, part_key


def _matching_po_items(po, bom, items_map, items_map_by_part, *, split_parts, part_key):
    """该 BOM 行对应的采购明细：拆行模式按部位精确匹配，合并模式按物料匹配。"""
    if split_parts:
        return (items_map_by_part or {}).get(
            (po.id, bom['material_name'], bom['specification'], bom['unit'], part_key), [],
        )
    return items_map.get(
        (po.id, bom['material_name'], bom['specification'], bom['unit']), [],
    )


def _accumulate_factory_bom(group, po, bom, items_map, order_qty, *,
                            items_map_by_part=None, split_parts=False, accumulate=True):
    """把一条 BOM 行并入「(供应商, 物料, 规格, 单位, 部位)」聚合行。

    ``accumulate=False`` = **只登记展示部位、不碰数量**：跨 SKU 去重（
    ``_build_factory_group_map`` 的 ``seen_materials``）命中时，该 BOM 行的用量已经
    被其它 SKU 的那一行代表过了（同一物料在采购明细里只有一份），数量不能再加；
    但它的「部位」是新信息，必须登记进来 —— 否则落库合并行的展示部位只覆盖第一个
    SKU（2026-11-05 QA Low-1：2 个 SKU 共用物料、部位 身体/头部 → 只显示 身体）。

    行定位见 ``_ensure_fabric_row``（唯一一份），明细匹配见 ``_matching_po_items``。
    """
    existing, sup, fkey, part_key = _ensure_fabric_row(
        group, po, bom, split_parts=split_parts, accumulate=accumulate,
    )
    if existing is None:
        return
    if not accumulate:
        # 展示部位已登记，数量一律不动（跨 SKU 去重的本意就是「只计一次」）。
        return

    matching_items = _matching_po_items(
        po, bom, items_map, items_map_by_part, split_parts=split_parts, part_key=part_key,
    )

    if matching_items:
        # 采购明细真值：同一张单在同一聚合键上只能计一次——同 SKU 内多角色 /
        # 同部位重复的 BOM 行共享同一份明细，逐行累加会翻倍。
        seen = group.setdefault('_stored_seen', set())
        seen_key = (po.id, sup, fkey)
        if seen_key in seen:
            return
        seen.add(seen_key)
        per_order_qty = sum(float(it.quantity or 0) for it in matching_items)
        cur_item_ids = [it.id for it in matching_items]
    else:
        # 无对应采购明细（BOM 生成后新增）：按 BOM 用量逐行累加
        per_order_qty = bom['quantity'] * order_qty
        cur_item_ids = []

    existing['quantity'] += per_order_qty
    existing['item_ids'].extend(cur_item_ids)

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
        part_key = _norm_part_name(item.part_name)
        fkey = (item.material_name, item.specification or '', item.unit or '', part_key)
        if fkey in fabric_map:
            fabric_map[fkey]['quantity'] += float(item.quantity or 0)
            if item.id not in fabric_map[fkey]['item_ids']:
                fabric_map[fkey]['item_ids'].append(item.id)
        else:
            fabric_map[fkey] = {
                'fabric_name': item.material_name,
                'part_name': part_key or None,
                'specification': item.specification or '',
                'quantity': float(item.quantity or 0),
                'unit': item.unit or '',
                'item_ids': [item.id] if item.id else [],
                **_new_part_tracking(),
            }
        # 本回退路径（BOM 完全不可用）里聚合键已含部位，故同一键的部位恒相同；
        # 仍走统一记账，保证接口字段在两条路径上完全同形。
        _record_part(fabric_map[fkey], part_key)

def _norm_sku_name(value) -> str:
    """SKU 名归一：仅 strip。**不** casefold —— 产品名要逐字匹配 `Product.name`（全局唯一）。"""
    return str(value or '').strip()


def _sku_material_rows(
    bom_rows: list, sku_qty: float, supplier_fallback: str, split_parts: bool = False,
    allocation: dict | None = None,
) -> list[dict]:
    """把某个 SKU 的 BOM 行展开为「该 SKU 自己的物料行」（口径 A）。

    `quantity` = ``单件用量 × 该 SKU 数量``（**基准量**，不含损耗加放 —— 加放由前端按该
    物料的行损耗率实时做，故这里必须给基准值）。

    ``allocation``：陈列样随箱配比的 ``{role_id: 数量乘子}``（见
    ``utils/scope_quantities.allocate_scope_quantities``）。传入时按 BOM 行的
    ``role_id`` 取对应乘子（常规款均分值 / 隐藏款 ceil 值 / 默认 BOM 全量），
    使「按 SKU 推算」与生成路径落库值同口径；``None`` = 历史口径（每行都用
    ``sku_qty``，未配置配比的 SKU 行为零变化）。

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
        bom_part = _norm_part_name(bom.get('part_name'))
        part_key = bom_part if split_parts else ''
        key = (sup, bom['material_name'], bom['specification'], bom['unit'], part_key)
        row_qty = sku_qty if allocation is None else allocation.get(bom.get('role_id'), sku_qty)
        amount = round_qty(float(bom.get('quantity') or 0) * float(row_qty or 0))
        if key in buckets:
            buckets[key]['quantity'] += amount
        else:
            buckets[key] = {
                'supplier_name': sup,
                'material_name': bom['material_name'],
                'part_name': part_key or None,
                'specification': bom['specification'],
                'unit': bom['unit'],
                'quantity': amount,
                **_new_part_tracking(),
            }
        # 展示部位在这里登记（合并模式下同一物料的多条 BOM 行会落到同一桶）。
        _record_part(buckets[key], bom_part)
    # 稳定顺序：供应商 → 部位 → 物料名 → 规格 → 单位
    return sorted(
        buckets.values(),
        key=lambda r: (
            r['supplier_name'], r['part_name'] or '', r['material_name'], r['specification'], r['unit'],
        ),
    )


def _accumulate_factory_sku_materials(
    group: dict, sku_lines: list, po, bom_data: dict, name_to_pid: dict, *,
    split_parts: bool = False, blind_box_ctx: dict | None = None,
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
    4. **陈列样随箱配比 SKU**（``blind_box_ctx`` 有该 pid）：同一张采购单内先把各来源行
       数量**合并成订单总数量**再分配（常规 6 款均分 / 隐藏款 ``ceil(N/P)``，ceil 只进位
       一次），与生成路径「同客户组同 SKU 先合并再分配」同口径——逐行分配会让隐藏款重复
       进位，前端差异对照块就会把「没差异」误报成手工调整。未配置的 SKU 走原逐行全量路径。
    """
    # 配置了配比的 SKU：先按本单来源行合并数量（生成时同一批来源已合并过一次）
    merged_configured_qty: dict[str, float] = {}
    if blind_box_ctx:
        for sku in sku_lines:
            sku_name = _norm_sku_name(sku.get('product_name'))
            if name_to_pid.get(sku_name) in blind_box_ctx:
                merged_configured_qty[sku_name] = (
                    merged_configured_qty.get(sku_name, 0.0) + float(sku.get('order_qty') or 0)
                )

    emitted_configured: set[str] = set()
    for sku in sku_lines:
        sku_name = _norm_sku_name(sku.get('product_name'))
        sku_pid = name_to_pid.get(sku_name)
        if sku_pid is None:
            continue
        ctx_entry = (blind_box_ctx or {}).get(sku_pid)
        if ctx_entry:
            if sku_name in emitted_configured:
                # 合并口径下该 SKU 的物料已整体产出，跳过后续来源行避免重复累加
                continue
            emitted_configured.add(sku_name)
            sku_qty = merged_configured_qty.get(sku_name, float(sku.get('order_qty') or 0))
            allocation = _factory_sku_allocation(ctx_entry, sku_qty)
        else:
            sku_qty = float(sku.get('order_qty') or 0)
            allocation = None
        supplier_fallback = po.supplier_name or '未指定供应商'
        bucket = group['_sku_materials'].setdefault(sku_name, {})
        for row in _sku_material_rows(
            bom_data.get(sku_pid) or [], sku_qty, supplier_fallback,
            split_parts=split_parts, allocation=allocation,
        ):
            key = (
                row['supplier_name'], row['material_name'],
                row['specification'], row['unit'], row.get('part_name') or '',
            )
            if key in bucket:
                bucket[key]['quantity'] += row['quantity']
                # 跨单累加同一聚合键：部位记账必须一起并入（合并模式下不同单的 BOM
                # 可能各覆盖一部分部位，丢掉任一侧都会让展示文本少列部位）。
                _merge_part_tracking(bucket[key], row)
            else:
                bucket[key] = row


def _finalize_factory_sku_materials(group_map: dict) -> None:
    """把逐单累加的物料桶定稿为**稳定排序**的列表（与 ``_sku_material_rows`` 同序）。

    累加期 ``_sku_materials`` 是 ``{sku_name: {(sup, mat, spec, unit, part): row}}``（跨单 ``+=``）；
    此处转成 ``{sku_name: [row, ...]}``，排序键与 ``_sku_material_rows`` 一致
    （供应商 → 部位 → 物料名 → 规格 → 单位），保证块内顺序稳定、且与既有 fabrics 同序。

    解析不出产品（无 pid）的 SKU 留空数组 —— 前端据此回退订单级单块，绝不编造。

    **本函数必须可重复调用（幂等）**，两条措施各司其职：
    - 定稿时对每行取 ``dict(row)`` 副本再压展示文本 —— 就地 pop 会把桶里的
      ``_part_names/_part_unknown`` 记账字段吃掉，累加态被破坏（与
      ``_serialize_factory_groups`` 同写法：定稿是「投影成接口形状」，不该反向改写累加态）；
    - 第二轮进来时 ``_sku_materials`` 已经是 list（首轮定稿结果），故两种形状都要认；
      此时行里没有记账字段，``_finalize_part_display`` 原样保留既有 ``part_display``，
      绝不按「空记账」重算成空串。
    """
    for group in group_map.values():
        finalized: dict[str, list[dict]] = {}
        for name, buckets in group['_sku_materials'].items():
            rows = list(buckets.values()) if isinstance(buckets, dict) else list(buckets)
            finalized[name] = sorted(
                (_finalize_part_display(dict(row)) for row in rows),
                key=lambda r: (
                    r['supplier_name'], r.get('part_name') or '',
                    r['material_name'], r['specification'], r['unit'],
                ),
            )
        group['_sku_materials'] = finalized


def _split_parts_by_group(orders, items_by_order, cust_order_map, prod_name_map) -> dict[tuple, bool]:
    """组内所有采购明细都带 part_name 才按部位拆；混入旧单/手工无部位行则整组合并。

    - 一张 PO 内只要有一条明细 part_name 为空（手工加行、旧接口写入 NULL），该 PO
      即按物料合并——拆行模式下空部位明细无法与带部位的 BOM 行精确匹配，会少计且不可编辑。
    - 无明细的 PO 不参与判定，避免它把同组新单的拆行也压掉。
    """
    parts_aware_by_po: dict[int, bool] = {}
    for po in orders:
        items = items_by_order.get(po.id) or []
        if items:
            parts_aware_by_po[po.id] = all(_norm_part_name(it.part_name) for it in items)

    split_by_group: dict[tuple, bool] = {}
    for po in orders:
        aware = parts_aware_by_po.get(po.id)
        if aware is None:
            continue
        cust, prod, _order_qty, _pid = _resolve_factory_po_info(po, cust_order_map, prod_name_map)
        key = (cust, prod)
        split_by_group[key] = split_by_group.get(key, True) and aware
    return split_by_group


def _resolve_po_pids(po_pids_map, po, pid) -> list:
    """该采购单覆盖的产品 ID 列表（缺 ``po_pids_map`` 时退化为首个 SKU 的 pid）。"""
    if po_pids_map is None:
        return [pid] if pid else []
    return list(po_pids_map.get(po.id) or ([pid] if pid else []))


def _accumulate_po_bom_rows(group, po, pids, bom_data, items_map, order_qty, *,
                            items_map_by_part=None, split_parts=False) -> bool:
    """把该采购单覆盖的**全部 SKU** 的 BOM 行并入分组。

    Returns:
        是否有任何 SKU 配了 BOM（``False`` 时调用方回退到采购明细口径）。
    """
    seen_materials: set[tuple] = set()
    has_bom = False
    for idx, sku_pid in enumerate(pids):
        bom_list = bom_data.get(sku_pid, [])
        if bom_list:
            has_bom = True
        for bom in bom_list:
            if _is_filling_category(bom.get('category')):
                continue
            part_key = _norm_part_name(bom.get('part_name')) if split_parts else ''
            skey = (
                bom['supplier_name'] or po.supplier_name or '未指定供应商',
                bom['material_name'], bom['specification'], bom['unit'], part_key,
            )
            # 跨 SKU 去重：第 1 个 SKU 走正常累加（保持同 SKU 内多角色重复行的既有行为），
            # 从第 2 个 SKU 起对已出现过的物料键只补登记部位、不累加数量。两条约束并存：
            #   (a) `seen_materials.add(skey)` 必须发生在**数量累加**
            #       （下面的 `_accumulate_factory_bom`）之前 —— 否则首个 SKU 的键不登记，
            #       第 2 个 SKU 会再累加一次，数量翻倍；
            #   (b) 命中 `skey in seen_materials` 时**仍要补登记部位**
            #       （`accumulate=False`）—— 同一物料在不同 SKU 可以用于不同部位，
            #       跳过整条 BOM 行会让合并行的部位集合缺项（QA Low-1 就栽在这里）。
            #       删掉下面这个 accumulate=False 调用，`test_cross_sku_shared_material_
            #       lists_every_sku_part` 会红。
            if idx > 0 and skey in seen_materials:
                # 跳过的是**数量**，不是这条 BOM 行的全部信息：它的部位还没进过
                # 展示文本（不同 SKU 可以把这个物料用在别的部位），故以
                # accumulate=False 补登记一次，数量一律不动。
                _accumulate_factory_bom(
                    group, po, bom, items_map, order_qty,
                    items_map_by_part=items_map_by_part, split_parts=split_parts,
                    accumulate=False,
                )
                continue
            seen_materials.add(skey)
            _accumulate_factory_bom(
                group, po, bom, items_map, order_qty,
                items_map_by_part=items_map_by_part, split_parts=split_parts,
            )
    return has_bom


def _build_factory_group_map(orders, bom_data, items_map, items_by_order, cust_order_map,
                             prod_name_map, po_pids_map=None, po_sku_map=None,
                             items_map_by_part=None, blind_box_ctx=None) -> dict[tuple, dict]:
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
    # 分组级拆行判定：组内所有采购单明细都带 part_name 才按部位拆；混入旧单则整组合并。
    split_by_group = _split_parts_by_group(orders, items_by_order, cust_order_map, prod_name_map)

    group_map: dict[tuple, dict] = {}
    for po in orders:
        cust, prod, order_qty, pid = _resolve_factory_po_info(po, cust_order_map, prod_name_map)
        key = (cust, prod)
        split_parts = split_by_group.get(key, False)
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
            # P2（2026-10-24）：同客户同产品名的多张采购单汇总时，订单数量必须累加。
            # 原先只在首次创建时写入 product_quantity/order_quantity，而 _sku_lines 是
            # 跨单累加的 —— 结果「订单数量」只等于第一张单，与 skus 合计、物料量自相矛盾。
            # 仅在首次入组时不重复加（上面 group_map[key] 的初始化已含本单数量）。
            if len(group['_order_ids']) > 1:
                group['product_quantity'] = int(group['product_quantity'] or 0) + int(order_qty or 0)
                group['order_quantity'] = int(group['order_quantity'] or 0) + int(order_qty or 0)

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
        _accumulate_factory_sku_materials(
            group, sku_lines, po, bom_data, name_to_pid, split_parts=split_parts,
            blind_box_ctx=blind_box_ctx,
        )

        pids = _resolve_po_pids(po_pids_map, po, pid)
        if not _accumulate_po_bom_rows(
            group, po, pids, bom_data, items_map, order_qty,
            items_map_by_part=items_map_by_part, split_parts=split_parts,
        ):
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
            fabrics = sorted(
                (_finalize_part_display(dict(f)) for f in supplier['_fabric_map'].values()),
                key=lambda x: (x.get('part_name') or '', x['fabric_name']),
            )
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
