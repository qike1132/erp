"""BOM 明细同步服务（task-3/4）。

对 pending 采购单按当前 BOM（与生成路径同口径）整单重建明细：
- 版本保护（``items_version`` 乐观锁，冲突抛 409）；
- 旧行的损耗率/单价/备注按匹配键继承（精确键消费式 + 回退键复用）；
  自定义数量仅按精确键继承，且要求该行 BOM 用量（unit_usage）未变
  （2026-11-13 口径：用量变了说明 BOM 需求变了，BOM 优先重算）；
- 规范序列无变化时不写库、不递增版本；
- 写路径落 ModificationLog(field_name='bom_sync')，事务由调用方控制。
- 产品级发现：来源订单链 + po_sku 快照名/条码解析受影响 pending 单；
  解析失败的单进 ``unresolved``（不静默），批量同步逐单 savepoint 隔离。
"""
import json
import logging
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import ItemsVersionConflict
from fastapi_app.services.purchase._common import (
    _resolve_pids_from_sku_lines,
    fetch_po_sku_lines_map,
    fetch_po_sku_pids_map,
)
from fastapi_app.services.purchase_order_crud import _recalc_item_total_price
from fastapi_app.services.purchase_order_generate import (
    _load_bom_context,
    _load_product_names,
    build_expected_items,
)
from fastapi_app.services.purchase_order_sku import fetch_po_sku_map
from fastapi_app.shared_models import Product, PurchaseOrder, PurchaseOrderItem
from fastapi_app.shared_models.purchase_center import ModificationLog
from fastapi_app.shared_models.purchase_order import PurchaseOrderStatus

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """单张采购单的同步结果。"""

    po_id: int
    changed: bool
    added: int = 0
    updated: int = 0
    removed: int = 0
    removed_rows: list = field(default_factory=list)
    skipped_reason: str | None = None
    # 目标明细（``build_expected_items`` 输出，含继承后的 loss_rate/unit_price/remark
    # 与用量未变行的自定义数量）：
    # 供离线校正脚本（scripts/sync_pending_po_items.py）逐行输出「旧→新」报告与
    # 判定 suspected_manual（复用同一份目标键，不在脚本里重抄解析流水线）。
    # 仅在 changed=True 时填充；未变更/跳过时为空。
    target_items: list[dict] = field(default_factory=list)


def _norm(value) -> str:
    return (value or '').strip()


def _norm_role(value) -> int:
    """role 归一：NULL（默认 BOM/历史/手工）与 None 统一为哨兵 0 参与键比较。"""
    return int(value) if value is not None else 0


def _existing_key(row: PurchaseOrderItem) -> tuple:
    # 2026-11-11 口径：键加入 role_id——同物料多角色各自成行，同步继承不得跨 role
    # 互相覆盖损耗率（问题 2 根因：旧键无 role，A 行改率会把 B 行一并顶掉）。
    return (
        _norm_role(getattr(row, 'role_id', None)),
        _norm(row.material_name), _norm(row.specification), _norm(row.unit),
        _norm(row.part_name), _norm(row.supplier_name), _norm(row.material_category),
    )


def _target_key(item: dict) -> tuple:
    return (
        _norm_role(item.get('role_id')),
        _norm(item.get('material_name')), _norm(item.get('specification')),
        _norm(item.get('unit')), _norm(item.get('part_name')),
        _norm(item.get('supplier_name')), _norm(item.get('category')),
    )


def _fallback_key(key: tuple) -> tuple:
    """去掉 part_name 的宽松匹配键（**同一 role 内**跨部位共享率/价）。

    2026-11-11 口径收窄：回退键保留 role_id（去掉它会让 A 角色的率覆盖 B 角色
    ——问题 2 病根）。跨角色永不回退；NULL-role 历史行的率/价只被 NULL-role
    目标行继承，不泄漏给角色行。
    """
    return (key[0], key[1], key[2], key[3], key[5], key[6])


def _canonical(item: dict) -> tuple:
    # 数量/用量按落库列精度比较（Numeric(12,2) / Numeric(10,4)），避免
    # 浮点表示差异和 Numeric 截断导致「刚同步过又被判为有变化」。
    return (
        _norm_role(item.get('role_id')),
        _norm(item.get('material_name')), _norm(item.get('specification')),
        _norm(item.get('unit')), _norm(item.get('part_name')),
        _norm(item.get('supplier_name')), _norm(item.get('category')),
        round(float(item.get('quantity') or 0), 2),
        round(float(item.get('unit_usage') or 0), 4),
    )


def _same_usage(old, new) -> bool:
    """该行的 BOM 用量是否未变（按落库列精度 Numeric(10,4)）。"""
    if old is None or new is None:
        return False
    return round(float(old), 4) == round(float(new), 4)


def _inherit_fields(
    rows: list[PurchaseOrderItem], target: list[dict], *,
    inherit_quantity: bool = True,
) -> None:
    """把旧行的 loss_rate/unit_price/remark 与「自定义数量」继承到目标行（原地修改）。

    先按精确键消费式领取；未领到的行用「回退键可复用」的率/价
    （同一回退值应用到所有剩余行，不消费）。

    数量继承（2026-11-13 口径）：
    - 只按**精确键**（含 role_id/part_name）继承，绝不走回退键——业务范围是
      「该 SKU + 该角色 + 该部位」，跨部位复用数量会把身体的自定义值糊到脚底；
    - 仅当该行自己的 ``unit_usage``（BOM 用量快照）与目标行一致时继承。
      用量变了说明 BOM 需求变了，BOM 优先重算（2026-11-11 实时同步裁决，
      PO-2611 事故的前提）；用量未变而数量不同，只能是用户手工调整。
    - ``inherit_quantity=False``（强制重算）：盲盒配置变更等场景会整体改变每个
      角色应做的数量，旧数值全部作废，不能当手工值保留；率/价/备注仍按原口径继承。
    """
    pool: dict[tuple, deque] = defaultdict(deque)
    for row in rows:
        pool[_existing_key(row)].append(
            (row.loss_rate, row.unit_price, row.remark, row.quantity, row.unit_usage)
        )

    fallback_pool: dict[tuple, tuple] = {}
    for key, entries in pool.items():
        for loss_rate, unit_price, _remark, _quantity, _unit_usage in entries:
            if loss_rate is not None or unit_price is not None:
                fb = _fallback_key(key)
                if fb not in fallback_pool:
                    fallback_pool[fb] = (loss_rate, unit_price)

    assigned: set[int] = set()
    for item in target:
        key = _target_key(item)
        if pool.get(key):
            loss_rate, unit_price, remark, quantity, unit_usage = pool[key].popleft()
            item['loss_rate'] = loss_rate
            item['unit_price'] = unit_price
            item['remark'] = remark
            if inherit_quantity and _same_usage(unit_usage, item.get('unit_usage')):
                item['quantity'] = quantity
            assigned.add(id(item))

    reused: dict[tuple, tuple] = {}
    for item in target:
        if id(item) in assigned:
            continue
        fb = _fallback_key(_target_key(item))
        if fb not in reused:
            reused[fb] = fallback_pool.get(fb, (None, None))
        loss_rate, unit_price = reused[fb]
        if loss_rate is not None:
            item['loss_rate'] = loss_rate
        if unit_price is not None:
            item['unit_price'] = unit_price


async def _load_sku_lines_map(
    db: AsyncSession, orders: list[PurchaseOrder],
) -> dict[int, list[dict]]:
    """批量版逐 SKU 行三层回退：po_sku 快照 → OrderItem 回退 → 订单级单行。

    与单张 ``_load_sku_lines`` 同口径；产品级发现一次加载全部 pending 单的 sku 行，
    避免按单查询的 N+1。
    """
    sku_map = await fetch_po_sku_map(db, [order.id for order in orders])
    missing = [order for order in orders if not sku_map.get(order.id)]
    if missing:
        lines_map = await fetch_po_sku_lines_map(db, missing)
        for order in missing:
            lines = lines_map.get(order.id) or []
            if lines:
                sku_map[order.id] = lines
    for order in orders:
        if not sku_map.get(order.id):
            sku_map[order.id] = [
                {'product_name': order.product_name, 'order_qty': order.product_quantity},
            ]
    return sku_map


async def _load_sku_lines(db: AsyncSession, order: PurchaseOrder) -> list[dict]:
    """逐 SKU 行三层回退（单张版，口径与 ``_load_sku_lines_map`` 一致）。"""
    return (await _load_sku_lines_map(db, [order]))[order.id]


def _diff_counts(rows, target: list[dict]) -> tuple[int, int, int, list[int]]:
    """按匹配键 multiset 差值算 added/updated/removed 与将被删除的行 id。"""
    existing_keys = Counter(_existing_key(r) for r in rows)
    target_keys = Counter(_target_key(t) for t in target)
    added = sum((target_keys - existing_keys).values())
    removed = sum((existing_keys - target_keys).values())
    updated = sum((existing_keys & target_keys).values())
    removed_rows = [r.id for r in rows if r.id is not None]
    return added, updated, removed, removed_rows


# 审计 new_value 里删除行快照的行数上限：BOM 整体换版可能一次删几百行，
# 快照无限大既不便于人工复核，也把 modification_log 行撑大。
_AUDIT_REMOVED_ROWS_LIMIT = 200


def _removed_row_snapshot(row: PurchaseOrderItem) -> dict:
    """审计用删除行快照（纯 JSON 可序列化值；Numeric 列转 float/None）。"""
    def _num(value):
        return float(value) if value is not None else None

    return {
        'material_name': row.material_name,
        'specification': row.specification,
        'unit': row.unit,
        'part_name': row.part_name,
        'role_id': getattr(row, 'role_id', None),
        'supplier_name': row.supplier_name,
        'quantity': _num(row.quantity),
        'loss_rate': _num(row.loss_rate),
        'unit_price': _num(row.unit_price),
    }


def _removed_items(
    rows: list[PurchaseOrderItem], target: list[dict],
) -> list[PurchaseOrderItem]:
    """键差异口径下真正被删除的旧行（与 added/updated/removed 计数同源）。

    ``_rewrite_items`` 是重建式同步（删全部旧行再插入），但业务口径的「删除」
    是 multiset 键差异：同键换成新 id 的行属于「更新」，不能进删除快照。
    按 ``rows`` 顺序消费目标键余量，余量耗尽的旧行才是 removed。
    """
    remaining = Counter(_target_key(t) for t in target)
    result: list[PurchaseOrderItem] = []
    for row in rows:
        key = _existing_key(row)
        if remaining.get(key, 0) > 0:
            remaining[key] -= 1
        else:
            result.append(row)
    return result


async def _rewrite_items(
    db: AsyncSession, order: PurchaseOrder, target: list[dict],
    counts: tuple[int, int, int, list[int]],
) -> None:
    """删旧行 → 批量插入目标行 → 重算总额/版本 → 落审计 → flush（不 commit）。"""
    added, updated, removed, _removed_rows = counts
    rows = (await db.execute(
        select(PurchaseOrderItem)
        .where(PurchaseOrderItem.order_id == order.id)
        .order_by(PurchaseOrderItem.id)
    )).scalars().all()
    # 删除行快照必须在 DELETE/expunge 之前取：之后对象属性不可依赖。
    removed_snapshot = [
        _removed_row_snapshot(r) for r in _removed_items(rows, target)
    ]
    await db.execute(delete(PurchaseOrderItem).where(PurchaseOrderItem.order_id == order.id))
    # Core DELETE 不同步 identity map：旧行对象已从库中消失，移出会话避免后续
    # 按主键取到幽灵对象或在 flush 时被误写回。
    for old in rows:
        db.expunge(old)

    total = Decimal('0')
    for t in target:
        item = PurchaseOrderItem(
            order_id=order.id,
            product_name=order.product_name,
            customer_name=order.customer_name,
            material_name=t.get('material_name') or '',
            material_code=t.get('material_code') or '',
            specification=t.get('specification') or '',
            unit=t.get('unit') or '',
            quantity=Decimal(str(t.get('quantity') or 0)),
            unit_price=t.get('unit_price'),
            loss_rate=t.get('loss_rate'),
            remark=t.get('remark'),
            material_category=t.get('category') or '',
            part_name=t.get('part_name'),
            role_id=t.get('role_id'),
            supplier_name=t.get('supplier_name') or '',
            unit_usage=t.get('unit_usage'),
        )
        _recalc_item_total_price(item, order.spare_rate)
        total += item.total_price or Decimal('0')
        db.add(item)

    order.total_amount = total
    order.items_version = (order.items_version or 0) + 1
    summary: dict = {'added': added, 'updated': updated, 'removed': removed,
                     'removed_rows': removed_snapshot[:_AUDIT_REMOVED_ROWS_LIMIT]}
    if len(removed_snapshot) > _AUDIT_REMOVED_ROWS_LIMIT:
        summary['removed_truncated'] = True
    db.add(ModificationLog(
        target_type='purchase_order', target_id=order.id, field_name='bom_sync',
        old_value=None,
        new_value=json.dumps(summary, ensure_ascii=False),
        modifier_name='system:bom_sync',
    ))
    await db.flush()


async def _load_pid_by_barcode(
    db: AsyncSession, barcodes: set[str],
) -> dict[str, int]:
    """条码 → pid。同一码对应多个 pid（``Product.barcode`` 只建索引、非唯一）视为歧义，
    不进入映射并告警——宁可判 unresolved，也不能把采购单判给错误产品写错 BOM。
    """
    if not barcodes:
        return {}
    rows = await db.execute(
        select(Product.id, Product.barcode).where(Product.barcode.in_(barcodes))
    )
    pids_by_barcode: dict[str, set[int]] = defaultdict(set)
    for pid, barcode in rows.all():
        pids_by_barcode[_norm(barcode)].add(pid)
    result: dict[str, int] = {}
    for barcode, candidate_pids in pids_by_barcode.items():
        if len(candidate_pids) == 1:
            result[barcode] = next(iter(candidate_pids))
        else:
            logger.warning(
                'bom_sync 条码对应多个产品，不按条码解析 barcode=%s pids=%s',
                barcode, sorted(candidate_pids),
            )
    return result


async def _resolve_sku_pids(
    db: AsyncSession, po_id: int, sku_lines: list[dict], pids: list[int],
    *, pid_name_map: dict[int, str] | None = None,
    pid_by_barcode: dict[str, int] | None = None,
) -> dict[str, int] | None:
    """sku 行 → {产品名: pid}。**全部**行可解才返回映射，任一行失败返回 None。

    名称解析不到时按条码回退（覆盖「产品改名后 po_sku 快照名对不上」：名称是快照、
    条码更稳定）；条码对应多个产品时不解析（见 ``_load_pid_by_barcode``）。解析到的
    pid 会补进 ``pids``（供后续加载 BOM 上下文 / 发现层判定产品归属）。

    ``pid_name_map`` / ``pid_by_barcode`` 可传入调用方批量预算好的结果（产品级发现
    用一次查询覆盖全部 pending 单）；不传则按本单 pid / 条码现查。
    """
    if pid_name_map is None:
        pid_name_map = await _load_product_names(db, pids) if pids else {}
    allowed = set(pids)
    name_to_pid = {
        _norm(name): pid for pid, name in pid_name_map.items() if pid in allowed
    }

    unresolved = [line for line in sku_lines if _norm(line.get('product_name')) not in name_to_pid]
    if not unresolved:
        return name_to_pid

    if pid_by_barcode is None:
        barcodes = {b for b in (_norm(line.get('product_barcode')) for line in unresolved) if b}
        pid_by_barcode = await _load_pid_by_barcode(db, barcodes)

    for line in unresolved:
        name = _norm(line.get('product_name'))
        barcode = _norm(line.get('product_barcode'))
        pid = pid_by_barcode.get(barcode)
        if pid is None:
            logger.warning(
                'bom_sync unresolved sku po=%s name=%s barcode=%s',
                po_id, name, line.get('product_barcode'),
            )
            return None
        name_to_pid[name] = pid
        if pid not in pids:
            pids.append(pid)
    return name_to_pid


def _po_for_update_stmt(po_id: int):
    """采购单行锁查询（显式 ``SELECT ... FOR UPDATE``，供生产库真正加锁）。

    Why 不用 ``db.get(..., with_for_update=True)``：对象已在 identity map 时
    ``Session.get`` 直接返回缓存、不发 SQL，锁根本未获取（产品级发现会先整行
    加载全部 pending 单，随后逐单同步即命中缓存——评审 Minor 3）。
    ``populate_existing`` 同时强制刷新属性，确保 ``expected_version`` 校验读到
    加锁后的行。sqlite 方言忽略 FOR UPDATE，锁语义只能靠 PG 方言编译断言。
    """
    return (
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def sync_purchase_order_items(
    db: AsyncSession, po_id: int, *,
    expected_version: int | None = None, dry_run: bool = False,
    force_quantity_from_bom: bool = False,
) -> SyncResult:
    """单张采购单按当前 BOM 整体重建明细。事务由调用方控制（本函数只 flush）。

    dry_run 不持行锁：批量预览若也 FOR UPDATE，会把所有匹配采购单锁到外层
    事务提交，阻塞用户编辑；dry-run 无写入，无锁读即可。

    ``force_quantity_from_bom=True``：不继承旧数量，一律按 BOM 重算。用于盲盒
    配置变更（开关/隐藏款/配比）这类「每个角色应做多少」整体失效的场景，避免
    旧分配值被当成用户自定义数量保留。
    """
    if dry_run:
        order = await db.get(PurchaseOrder, po_id)
    else:
        order = (await db.execute(_po_for_update_stmt(po_id))).scalar_one_or_none()
    if order is None:
        return SyncResult(po_id=po_id, changed=False, skipped_reason='not_found')
    if order.status != PurchaseOrderStatus.PENDING:
        return SyncResult(po_id=po_id, changed=False,
                          skipped_reason=f'status:{order.status}')
    if expected_version is not None and (order.items_version or 0) != expected_version:
        raise ItemsVersionConflict()

    sku_lines = await _load_sku_lines(db, order)
    po_pids_map = await fetch_po_sku_pids_map(db, [order])
    pids = list(po_pids_map.get(po_id) or [])
    if not pids:
        # 备货「一键生成」单主表 source_order_ids 为 NULL（2026-11-07 生产缺陷同款）：
        # 与产品级发现同口径，先按快照产品名反查 pid；条码回退仍由 _resolve_sku_pids 兜底。
        pids_by_po: dict[int, list[int]] = {po_id: pids}
        await _resolve_pids_from_sku_lines(db, pids_by_po, {po_id: sku_lines})
        pids = pids_by_po[po_id]

    name_to_pid = await _resolve_sku_pids(db, po_id, sku_lines, pids)
    if name_to_pid is None:
        return SyncResult(po_id=po_id, changed=False, skipped_reason='unresolved_sku')

    ctx = await _load_bom_context(db, pids)
    target = build_expected_items(sku_lines, ctx, name_to_pid, order.customer_name or '')

    rows = (await db.execute(
        select(PurchaseOrderItem)
        .where(PurchaseOrderItem.order_id == po_id)
        .order_by(PurchaseOrderItem.id)
    )).scalars().all()

    _inherit_fields(rows, target, inherit_quantity=not force_quantity_from_bom)

    existing_sig = sorted(
        (
            _norm_role(getattr(r, 'role_id', None)),
            *_existing_key(r)[1:],
            round(float(r.quantity or 0), 2), round(float(r.unit_usage or 0), 4),
        )
        for r in rows
    )
    target_sig = sorted(_canonical(t) for t in target)
    if existing_sig == target_sig:
        return SyncResult(po_id=po_id, changed=False)

    counts = _diff_counts(rows, target)
    added, updated, removed, removed_rows = counts
    if dry_run:
        return SyncResult(po_id=po_id, changed=True, added=added,
                          updated=updated, removed=removed,
                          removed_rows=removed_rows, target_items=target)

    await _rewrite_items(db, order, target, counts)
    return SyncResult(po_id=po_id, changed=True, added=added,
                      updated=updated, removed=removed,
                      removed_rows=removed_rows, target_items=target)


async def _backfill_pids_from_sku_snapshots(
    db: AsyncSession, pids_map: dict[int, list[int]],
    sku_lines_map: dict[int, list[dict]],
) -> None:
    """给主表来源解析不出 pid 的采购单按 sku 快照**产品名**补 pid（原地修改）。

    Why：备货「一键生成」的采购单主表 ``source_order_ids`` 为 NULL，来源只落在快照表里，
    ``fetch_po_sku_pids_map`` 对其恒空（与撤销路径 2026-11-07 生产缺陷同款）。按产品名反查
    （``_resolve_pids_from_sku_lines``，与撤销/工厂汇总同口径）；条码回退不在此做——统一由
    ``_resolve_sku_pids`` 处理，保证发现层与单张同步共用同一份（含歧义保护）的条码解析。
    补不到的单保持空 pids，由调用方计入 unresolved —— 解析失败不静默。
    """
    empty_ids = [po_id for po_id, pids in pids_map.items() if not pids]
    if not empty_ids:
        return
    await _resolve_pids_from_sku_lines(db, pids_map, sku_lines_map)


async def product_has_bom(db: AsyncSession, product_id: int) -> bool:
    """该产品当前是否存在任一 BOM 行（填充物/面料/辅料）。

    与撤销链 ``revoke_pending_purchase_orders_for_product`` **同口径**（同用
    ``_fetch_bom_product_ids``）——「BOM 是否已删空」两处判定必须一致：撤销层按名称
    回退解析不到的单（如备货一键生成 + 产品改名）撤不掉，若同步层凭条码回退仍命中它，
    空 BOM 会让目标行集合为空、把整单明细删光，留下 0 明细 pending 单（2026-11-11
    评审 Important）。因此同步前必须先过本守卫。
    """
    from fastapi_app.services.purchase._unprocessed import _fetch_bom_product_ids

    return bool(await _fetch_bom_product_ids(db, [product_id]))


async def find_pending_po_ids_for_product(
    db: AsyncSession, product_id: int,
) -> tuple[list[int], list[int]]:
    """待同步采购单：pending 且**全部** sku 行可解析（返回 (命中, 解析失败) 两组 po_id）。

    判定口径与 ``sync_purchase_order_items`` 共用 ``_resolve_sku_pids``：任一行解析失败
    的单计入 unresolved（批量同步对它是 ``synced=0``）。只凭部分行命中就判 matched 会让
    该单在报告里既不命中也不 unresolved —— 静默失踪。
    """
    pos = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.status == PurchaseOrderStatus.PENDING)
        .order_by(PurchaseOrder.id)
    )).scalars().all()
    if not pos:
        return [], []
    sku_lines_map = await _load_sku_lines_map(db, list(pos))
    pids_map = await fetch_po_sku_pids_map(db, list(pos))
    await _backfill_pids_from_sku_snapshots(db, pids_map, sku_lines_map)

    # 批量预算名称/条码映射：发现层与单张同步的解析结果逐字一致，且无 N+1。
    all_pids = sorted({pid for pids in pids_map.values() for pid in pids})
    pid_name_map = await _load_product_names(db, all_pids)
    all_barcodes = {
        _norm(line.get('product_barcode'))
        for lines in sku_lines_map.values() for line in lines
    } - {''}
    pid_by_barcode = await _load_pid_by_barcode(db, all_barcodes)

    matched: list[int] = []
    unresolved: list[int] = []
    for po in pos:
        pids = list(pids_map.get(po.id) or [])
        name_to_pid = await _resolve_sku_pids(
            db, po.id, sku_lines_map.get(po.id) or [], pids,
            pid_name_map=pid_name_map, pid_by_barcode=pid_by_barcode,
        )
        if name_to_pid is None:
            logger.warning(
                'bom_sync 产品级发现：采购单 sku 无法全部解析，计入 unresolved po_id=%s product_id=%s',
                po.id, product_id,
            )
            unresolved.append(po.id)
        elif product_id in pids:
            matched.append(po.id)
    return matched, unresolved


async def sync_pending_items_for_product(
    db: AsyncSession, product_id: int, *, dry_run: bool = False,
    force_quantity_from_bom: bool = False,
) -> dict:
    """同步所有覆盖该产品的 pending 采购单；逐单 savepoint，单张失败不污染其他单。"""
    matched, unresolved = await find_pending_po_ids_for_product(db, product_id)
    # 一次 BOM 保存影响面过大是异常信号（多半是公共物料挂在大量产品上）：
    # 打印 warning 供运维在日志里发现，便于核实是否需要人工复核批量改写。
    if len(matched) > 20:
        logger.warning(
            'BOM 同步影响采购单较多: product=%s count=%s', product_id, len(matched),
        )
    results: list[SyncResult] = []
    synced = 0
    skipped = len(unresolved)
    for po_id in matched:
        try:
            async with db.begin_nested():
                res = await sync_purchase_order_items(
                    db, po_id, dry_run=dry_run,
                    force_quantity_from_bom=force_quantity_from_bom,
                )
            results.append(res)
            if res.changed:
                synced += 1
            else:
                skipped += 1
        except ItemsVersionConflict:
            skipped += 1
            results.append(SyncResult(po_id=po_id, changed=False,
                                      skipped_reason='version_conflict'))
        except Exception:  # defensive: 逐单隔离，单张失败回滚该单并继续其余采购单
            skipped += 1
            logger.exception('BOM 同步失败 po_id=%s（该单已回滚）', po_id)
            results.append(SyncResult(po_id=po_id, changed=False,
                                      skipped_reason='error'))
    return {'synced': synced, 'skipped': skipped,
            'unresolved_po_ids': unresolved, 'results': results}
