"""
采购订单生成逻辑

职责：根据客户订单/备货记录生成采购订单。
从 purchase_order_service.py 拆分而来，保持函数签名不变。
"""
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastapi_app.core.float_utils import round_qty
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
from fastapi_app.shared_models.order import ORDER_STATUS_PENDING_STOCK, ORDER_STATUS_STOCKED, Order
from fastapi_app.shared_models.purchase_order import PurchaseOrder, PurchaseOrderStatus
# 作用域显示名与排序口径统一收敛到 utils.scope_order，与物料计算器共用同一实现
# （架构设计 §7#2 / Q-05）。DEFAULT_SCOPE_LABEL 在此重新导出，保持既有导入路径可用。
from fastapi_app.utils.scope_order import (
    DEFAULT_SCOPE_LABEL,  # noqa: F401  re-export（保持 purchase_order_generate.DEFAULT_SCOPE_LABEL）
    order_scopes,
    scope_label,
)

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


def _scope_order(role_ids, name_of=None) -> list[int | None]:
    """作用域排序：默认 BOM(None) 恒首位，其余按角色名升序（名同按 id 升序）。

    委托 ``utils.scope_order.order_scopes``，与物料计算器
    (services/purchase_product_service.aggregate_materials_by_scope) 共用同一口径，
    保证「计算器算出来的」与「一键生成落单的」顺序、分组一致（Q-05）。

    Args:
        role_ids: 作用域 role_id 集合（可含 ``None``）。
        name_of: 可选的角色名解析函数 ``role_id -> str | None``；缺省时全部按
            「角色#id」排序（对既有调用方向后兼容）。
    """
    return order_scopes(role_ids, name_of)


def _bom_rows_by_scope(rows) -> dict[int | None, list]:
    """把带 role_id 的 BOM 行按作用域分桶。"""
    buckets: dict[int | None, list] = defaultdict(list)
    for row in rows:
        buckets[row.role_id].append(row)
    return buckets


def _scope_label(pid: int, role_id: int | None, role_names: dict[tuple[int, int], str]) -> str:
    """作用域显示名（委托 ``utils.scope_order.scope_label``）。

    角色名按 ``(product_id, role_id)`` 定位；缺失时退化为「角色#<id>」而不是
    静默丢弃，便于现场定位脏数据。
    """
    role_name = role_names.get((pid, role_id)) if role_id is not None else None
    return scope_label(role_id, role_name)


@dataclass(frozen=True)
class _MaterialSpec:
    """三类 BOM 物料的字段映射。

    三类物料的明细结构完全同形，差异只有「取哪个用量字段 / 叫什么名字 / 默认单位」，
    因此用表驱动替代三段近乎重复的 dict 构建（2026-09-14 重构，零行为变化）。
    """

    category: str
    map_attr: str          # _BomContext 上对应的分桶字段名
    usage_attr: str        # 源行上表示「单位用量」的字段
    default_unit: str
    name_attr: str | None = None   # None 表示用「产品名 + name_suffix」
    name_suffix: str = ''
    default_name: str = ''         # name_attr 取到空值时的兜底名


# 顺序即输出顺序：同一作用域下 填充物 → 面料 → 配件（与重构前一致）
_MATERIAL_SPECS: tuple[_MaterialSpec, ...] = (
    _MaterialSpec('filling', 'filling', 'cotton_usage', '克', name_suffix='-填充物'),
    _MaterialSpec('fabric', 'fabric', 'quantity', '米', name_attr='fabric_name', default_name='面料'),
    _MaterialSpec('accessory', 'accessory', 'quantity', '个', name_attr='accessory_name', default_name='配件'),
)


@dataclass
class _BomContext:
    """一次生成所需的 BOM 上下文（三类分桶 + 作用域清单 + 角色名）。"""

    filling: dict = field(default_factory=dict)
    fabric: dict = field(default_factory=dict)
    accessory: dict = field(default_factory=dict)
    scopes_by_pid: dict[int, list] = field(default_factory=dict)
    role_names: dict[tuple[int, int], str] = field(default_factory=dict)

    def scopes_for(self, pid: int) -> list:
        """产品无任何角色 BOM 时回退到 [None]（仅默认BOM），保持旧行为。"""
        return self.scopes_by_pid.get(pid) or [None]


def _material_row(
    spec: _MaterialSpec, row, qty: int | float,
    product_name: str, customer_name: str, scope_label: str,
) -> dict:
    """把一条 BOM 行展开为一条采购明细（字段口径与重构前逐字对齐）。"""
    usage = float(getattr(row, spec.usage_attr) or 0)
    if spec.name_attr is None:
        material_name = product_name + spec.name_suffix
    else:
        material_name = getattr(row, spec.name_attr) or spec.default_name
    return {
        'material_name': material_name,
        'material_code': row.material_code or '',
        'specification': row.specification or '',
        'unit': row.unit or spec.default_unit,
        'unit_price': 0,
        'quantity': round_qty(usage * qty),
        'supplier_name': row.supplier_name or '',
        'supplier_id': row.supplier_id,
        'customer_name': customer_name,
        'category': spec.category,
        'unit_usage': usage,
        'source_role': scope_label,
    }


def _build_material_items(records: list, ctx: _BomContext, pid_name_map: dict[int, str]) -> list:
    """为给定记录列表构建物料项。

    多 SKU 模型：遍历每条记录的所有 SKU（Order.items 或 StockIn 单 SKU），
    为每个 SKU 独立展开 BOM，并**对每个 BOM 作用域各算一遍**（都用该 SKU 的
    完整数量，不分摊），与物料计算器口径一致。
    """
    result_items: list = []
    for rec in records:
        customer_name = rec.customer
        for pid, qty in _iter_source_skus(rec):
            product_name = pid_name_map.get(pid, '未知产品')
            for role_id in ctx.scopes_for(pid):
                scope_label = _scope_label(pid, role_id, ctx.role_names)
                for spec in _MATERIAL_SPECS:
                    for row in getattr(ctx, spec.map_attr).get(role_id, []):
                        if row.product_id != pid:
                            continue
                        result_items.append(
                            _material_row(spec, row, qty, product_name, customer_name, scope_label)
                        )
    return result_items


def _split_composite_ids(composite_ids: list[str]) -> tuple[list[int], list[int]]:
    """拆分复合 ID：`stockin:3` → stockin_ids，`order:5` / 纯数字 → order_ids。

    复合前缀确保 Order 与 StockIn 的 ID 不会碰撞；纯数字为旧格式兼容。
    """
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
    return order_ids, stockin_ids


async def _load_source_records(
    db: AsyncSession, order_ids: list[int], stockin_ids: list[int],
) -> tuple[list, list]:
    """按类型分别加载源记录（Order 预加载 items 以支持多 SKU）。"""
    from fastapi_app.shared_models import StockIn

    cust_orders: list = []
    if order_ids:
        cust_result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id.in_(order_ids))
        )
        cust_orders = cust_result.scalars().all()

    stockins: list = []
    if stockin_ids:
        stockin_result = await db.execute(
            select(StockIn).where(StockIn.id.in_(stockin_ids))
        )
        stockins = stockin_result.scalars().all()
    return cust_orders, stockins


def _assert_orders_generatable(cust_orders: list) -> None:
    """仅「待入库」状态的订单可审核生成采购单。"""
    invalid_orders = [o for o in cust_orders if o.status != ORDER_STATUS_PENDING_STOCK]
    if invalid_orders:
        raise ValueError(
            f'订单 {invalid_orders[0].order_no} 当前状态为"{invalid_orders[0].status}"，'
            f'仅"{ORDER_STATUS_PENDING_STOCK}"状态可审核'
        )


def _collect_product_ids(records: list) -> list[int]:
    """收集所有源记录的 SKU 级 product_id。

    多 SKU 模型：必须遍历 Order.items 才能拿到全部 SKU 的 product_id，
    否则只会取到 Order.product_id（首个 SKU），遗漏其他 SKU 的 BOM。
    """
    product_ids_set: set[int] = set()
    for r in records:
        for pid, _qty in _iter_source_skus(r):
            product_ids_set.add(pid)
    return list(product_ids_set)


async def _load_product_names(db: AsyncSession, product_ids: list[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    prod_result = await db.execute(
        select(Product.id, Product.name).where(Product.id.in_(product_ids))
    )
    return dict(prod_result.all())


async def _load_bom_context(db: AsyncSession, product_ids: list[int]) -> _BomContext:
    """加载三类 BOM 分桶、各产品的作用域清单与角色名。"""
    ctx = _BomContext()
    if not product_ids:
        return ctx

    fill_result = await db.execute(
        select(ProductMaterial).where(ProductMaterial.product_id.in_(product_ids))
    )
    ctx.filling = _bom_rows_by_scope(fill_result.scalars().all())

    fab_result = await db.execute(
        select(ProductFabric).where(ProductFabric.product_id.in_(product_ids))
    )
    ctx.fabric = _bom_rows_by_scope(fab_result.scalars().all())

    acc_result = await db.execute(
        select(ProductAccessory).where(ProductAccessory.product_id.in_(product_ids))
    )
    ctx.accessory = _bom_rows_by_scope(acc_result.scalars().all())

    from fastapi_app.shared_models import ProductRole, Role

    # 展示名优先取全局角色名（§7#10），缺失回退镜像列 role_name：迁移回填完成前
    # global_role_id 可能为 NULL，故用外连接而非内连接，避免角色整行丢失。
    role_result = await db.execute(
        select(ProductRole.id, ProductRole.product_id, ProductRole.role_name, Role.name)
        .join(Role, ProductRole.global_role_id == Role.id, isouter=True)
        .where(ProductRole.product_id.in_(product_ids))
    )
    role_ids_by_pid: dict[int, set[int]] = defaultdict(set)
    for rid, rpid, rname, gname in role_result.all():
        ctx.role_names[(rpid, rid)] = gname or rname or ''
        role_ids_by_pid[rpid].add(rid)

    for pid in product_ids:
        # 作用域清单 = 物料上出现过的 role_id ∪ 产品实际声明的角色 ∪ {None}。
        # ★ None 必须显式并入：product_role 表里**没有**「默认BOM」这一行，
        #   它只以「物料 role_id IS NULL」的形式存在，漏掉就会把整个产品级 BOM 丢了。
        #   与物料计算器 aggregate_materials_by_scope 的 ordered = ([None] if None in ...) 口径一致。
        # 用并集而非「物料 role_id 集合」，是为了让「配了角色但该角色暂无物料」也能被
        # 纳入作用域枚举（该作用域最终不产出任何明细，等价于被跳过）。
        material_roles = {
            row.role_id
            for m in (ctx.filling, ctx.fabric, ctx.accessory)
            for row in m.get(pid, [])
            if row.product_id == pid
        } | set(role_ids_by_pid.get(pid, ())) | {None}
        ctx.scopes_by_pid[pid] = _scope_order(
            material_roles,
            name_of=lambda rid, _pid=pid: ctx.role_names.get((_pid, rid)),
        )
    return ctx


async def _cleanup_pending_for(
    db: AsyncSession, order_ids: list[int], stockin_ids: list[int],
) -> None:
    """幂等性前置：清理关联这些客户订单/备货记录的旧 pending 采购单。

    不清理会导致重复审核产生重复订单。
    """
    if not (order_ids or stockin_ids):
        return
    await cleanup_orphan_pending_purchase_orders(
        db, order_ids=order_ids or None, stockin_ids=stockin_ids or None
    )
    # 强制 flush，让 DELETE 在后续 INSERT 之前实际执行，避免唯一约束冲突
    await db.flush()


def _group_by_customer(records: list) -> dict[str, list]:
    groups: dict[str, list] = defaultdict(list)
    for rec in records:
        groups[rec.customer].append(rec)
    return groups


async def _generate_per_customer(
    db: AsyncSession, groups: dict[str, list], ctx: _BomContext, pid_name_map: dict[int, str],
) -> list:
    """按客户分组生成采购单（1 个客户 = 1 个采购单）。"""
    generated_orders: list = []
    for customer_name, records in groups.items():
        cust_items = _build_material_items(records, ctx, pid_name_map)
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
    return generated_orders


async def generate_purchase_orders_from_customer_orders(
    db: AsyncSession, composite_ids: list[str], idempotency_key: str = '',
) -> dict:
    """根据复合 ID 列表生成采购单

    composite_ids 格式为 ['order:5', 'stockin:3', ...]，确保 Order 和 StockIn
    的 ID 不会碰撞。

    idempotency_key 为可选的幂等键，当前由数据库唯一约束 uq_po_pending_dedup
    和 endpoint 层的 IntegrityError 处理保证幂等，此参数保留用于未来扩展。

    BOM 口径：**产品所有 BOM 作用域（默认BOM + 各角色）的物料都会落入采购单**，
    每个作用域都用该 SKU 的完整数量计算（不做分摊），与物料计算器一致。
    多角色 SKU 因此会把同一个「哈哈」按不同角色各算一次，采购明细按
    (物料名, 规格, 单位) 合并后数量累加 —— 即该产品的**总采购需求**。
    """
    if not composite_ids:
        raise ValueError('未选择任何订单')

    order_ids, stockin_ids = _split_composite_ids(composite_ids)
    cust_orders, stockins = await _load_source_records(db, order_ids, stockin_ids)
    _assert_orders_generatable(cust_orders)

    all_source_records = list(cust_orders) + list(stockins)
    product_ids = _collect_product_ids(all_source_records)
    pid_name_map = await _load_product_names(db, product_ids)
    ctx = await _load_bom_context(db, product_ids)

    await _cleanup_pending_for(db, order_ids, stockin_ids)

    all_items = _build_material_items(all_source_records, ctx, pid_name_map)
    if not all_items:
        raise ValueError('所选订单的产品未配置BOM物料，无法生成采购单')

    generated_orders = await _generate_per_customer(
        db, _group_by_customer(all_source_records), ctx, pid_name_map
    )

    # 更新订单状态
    for o in cust_orders:
        o.status = ORDER_STATUS_STOCKED

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
            PurchaseOrder.status == PurchaseOrderStatus.PENDING,
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
