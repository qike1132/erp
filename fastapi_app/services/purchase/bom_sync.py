"""BOM 明细同步服务（task-3）。

对 pending 采购单按当前 BOM（与生成路径同口径）整单重建明细：
- 版本保护（``items_version`` 乐观锁，冲突抛 409）；
- 旧行的损耗率/单价/备注按匹配键继承（精确键消费式 + 回退键复用）；
- 规范序列无变化时不写库、不递增版本；
- 写路径落 ModificationLog(field_name='bom_sync')，事务由调用方控制。
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


def _norm(value) -> str:
    return (value or '').strip()


def _existing_key(row: PurchaseOrderItem) -> tuple:
    return (
        _norm(row.material_name), _norm(row.specification), _norm(row.unit),
        _norm(row.part_name), _norm(row.supplier_name), _norm(row.material_category),
    )


def _target_key(item: dict) -> tuple:
    return (
        _norm(item.get('material_name')), _norm(item.get('specification')),
        _norm(item.get('unit')), _norm(item.get('part_name')),
        _norm(item.get('supplier_name')), _norm(item.get('category')),
    )


def _fallback_key(key: tuple) -> tuple:
    """去掉 part_name 的宽松匹配键（同一物料跨部位共享率/价）。"""
    return (key[0], key[1], key[2], key[4], key[5])


def _canonical(item: dict) -> tuple:
    # 数量/用量按落库列精度比较（Numeric(12,2) / Numeric(10,4)），避免
    # 浮点表示差异和 Numeric 截断导致「刚同步过又被判为有变化」。
    return (
        _norm(item.get('material_name')), _norm(item.get('specification')),
        _norm(item.get('unit')), _norm(item.get('part_name')),
        _norm(item.get('supplier_name')), _norm(item.get('category')),
        round(float(item.get('quantity') or 0), 2),
        round(float(item.get('unit_usage') or 0), 4),
    )


def _inherit_fields(rows: list[PurchaseOrderItem], target: list[dict]) -> None:
    """把旧行的 loss_rate/unit_price/remark 继承到目标行（原地修改）。

    先按精确键消费式领取；未领到的行用「回退键可复用」的率/价
    （同一回退值应用到所有剩余行，不消费）。
    """
    pool: dict[tuple, deque] = defaultdict(deque)
    for row in rows:
        pool[_existing_key(row)].append((row.loss_rate, row.unit_price, row.remark))

    fallback_pool: dict[tuple, tuple] = {}
    for key, entries in pool.items():
        for loss_rate, unit_price, _remark in entries:
            if loss_rate is not None or unit_price is not None:
                fb = _fallback_key(key)
                if fb not in fallback_pool:
                    fallback_pool[fb] = (loss_rate, unit_price)

    assigned: set[int] = set()
    for item in target:
        key = _target_key(item)
        if pool.get(key):
            loss_rate, unit_price, remark = pool[key].popleft()
            item['loss_rate'] = loss_rate
            item['unit_price'] = unit_price
            item['remark'] = remark
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


async def _load_sku_lines(db: AsyncSession, order: PurchaseOrder) -> list[dict]:
    """逐 SKU 行三层回退：po_sku 快照 → OrderItem 回退 → 订单级单行。"""
    sku_map = await fetch_po_sku_map(db, [order.id])
    lines = sku_map.get(order.id) or []
    if not lines:
        lines = (await fetch_po_sku_lines_map(db, [order])).get(order.id) or []
    if not lines:
        lines = [{'product_name': order.product_name, 'order_qty': order.product_quantity}]
    return lines


def _diff_counts(rows, target: list[dict]) -> tuple[int, int, int, list[int]]:
    """按匹配键 multiset 差值算 added/updated/removed 与将被删除的行 id。"""
    existing_keys = Counter(_existing_key(r) for r in rows)
    target_keys = Counter(_target_key(t) for t in target)
    added = sum((target_keys - existing_keys).values())
    removed = sum((existing_keys - target_keys).values())
    updated = sum((existing_keys & target_keys).values())
    removed_rows = [r.id for r in rows if r.id is not None]
    return added, updated, removed, removed_rows


async def _rewrite_items(
    db: AsyncSession, order: PurchaseOrder, target: list[dict],
    counts: tuple[int, int, int, list[int]],
) -> None:
    """删旧行 → 批量插入目标行 → 重算总额/版本 → 落审计 → flush（不 commit）。"""
    added, updated, removed, _removed_rows = counts
    rows = (await db.execute(
        select(PurchaseOrderItem)
        .where(PurchaseOrderItem.order_id == order.id)
    )).scalars().all()
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
            supplier_name=t.get('supplier_name') or '',
            unit_usage=t.get('unit_usage'),
        )
        _recalc_item_total_price(item, order.spare_rate)
        total += item.total_price or Decimal('0')
        db.add(item)

    order.total_amount = total
    order.items_version = (order.items_version or 0) + 1
    summary = {'added': added, 'updated': updated, 'removed': removed}
    db.add(ModificationLog(
        target_type='purchase_order', target_id=order.id, field_name='bom_sync',
        old_value=None,
        new_value=json.dumps(summary, ensure_ascii=False),
        modifier_name='system:bom_sync',
    ))
    await db.flush()


async def _resolve_sku_pids(
    db: AsyncSession, po_id: int, sku_lines: list[dict], pids: list[int],
) -> dict[str, int] | None:
    """sku 行 → {产品名: pid}。名称解析不到时按条码回退；仍失败返回 None。

    条码回退覆盖「产品改名后 po_sku 快照名对不上」：名称是快照、条码更稳定。
    解析到的 pid 会补进 ``pids``（供后续加载 BOM 上下文）。
    """
    name_to_pid: dict[str, int] = {}
    if pids:
        pid_name_map = await _load_product_names(db, pids)
        name_to_pid = {(name or '').strip(): pid for pid, name in pid_name_map.items()}

    unresolved = [line for line in sku_lines if _norm(line.get('product_name')) not in name_to_pid]
    if not unresolved:
        return name_to_pid

    barcodes = [b for b in (_norm(line.get('product_barcode')) for line in unresolved) if b]
    pid_by_barcode: dict[str, int] = {}
    if barcodes:
        rows = await db.execute(
            select(Product.id, Product.barcode).where(Product.barcode.in_(barcodes))
        )
        for pid, barcode in rows.all():
            pid_by_barcode.setdefault(barcode, pid)

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


async def sync_purchase_order_items(
    db: AsyncSession, po_id: int, *,
    expected_version: int | None = None, dry_run: bool = False,
) -> SyncResult:
    """单张采购单按当前 BOM 整体重建明细。事务由调用方控制（本函数只 flush）。

    dry_run 不持行锁：批量预览若也 FOR UPDATE，会把所有匹配采购单锁到外层
    事务提交，阻塞用户编辑；dry-run 无写入，无锁读即可。
    """
    order = await db.get(PurchaseOrder, po_id, with_for_update=not dry_run)
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

    _inherit_fields(rows, target)

    existing_sig = sorted(
        (*_existing_key(r), round(float(r.quantity or 0), 2), round(float(r.unit_usage or 0), 4))
        for r in rows
    )
    target_sig = sorted(_canonical(t) for t in target)
    if existing_sig == target_sig:
        return SyncResult(po_id=po_id, changed=False)

    counts = _diff_counts(rows, target)
    added, updated, removed, removed_rows = counts
    if dry_run:
        return SyncResult(po_id=po_id, changed=True, added=added,
                          updated=updated, removed=removed, removed_rows=removed_rows)

    await _rewrite_items(db, order, target, counts)
    return SyncResult(po_id=po_id, changed=True, added=added,
                      updated=updated, removed=removed, removed_rows=removed_rows)


async def find_pending_po_ids_for_product(
    db: AsyncSession, product_id: int,
) -> tuple[list[int], list[int]]:
    """待同步采购单：pending 且覆盖该 pid（返回 (命中, pid 解析失败) 两组 po_id）。"""
    pos = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.status == PurchaseOrderStatus.PENDING)
        .order_by(PurchaseOrder.id)
    )).scalars().all()
    if not pos:
        return [], []
    pids_map = await fetch_po_sku_pids_map(db, list(pos))
    matched: list[int] = []
    unresolved: list[int] = []
    for po in pos:
        po_pids = pids_map.get(po.id) or []
        if not po_pids:
            unresolved.append(po.id)
        elif product_id in po_pids:
            matched.append(po.id)
    return matched, unresolved


async def sync_pending_items_for_product(
    db: AsyncSession, product_id: int, *, dry_run: bool = False,
) -> dict:
    """同步所有覆盖该产品的 pending 采购单；逐单 savepoint，单张失败不污染其他单。"""
    matched, unresolved = await find_pending_po_ids_for_product(db, product_id)
    results: list[SyncResult] = []
    synced = 0
    skipped = len(unresolved)
    for po_id in matched:
        try:
            async with db.begin_nested():
                res = await sync_purchase_order_items(db, po_id, dry_run=dry_run)
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
