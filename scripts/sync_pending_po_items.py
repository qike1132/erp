"""存量 pending 采购单的 BOM 明细校正（backfill，task-8）。

上线「BOM 实时同步」后的首次全量校正工具（设计：
``docs/superpowers/specs/2026-11-11-bom-live-sync-design.md`` §上线 backfill）。

- 默认 dry-run：只读，逐单打印四类清单（① 数量变更 ② 新增行 ③ 删除行 ④ 解析失败）；
- ``--apply``：走与在线回调**同一个**同步服务 ``sync_purchase_order_items`` 写库；
  每单独立事务（单张失败回滚该单、继续其余，失败逐张列出，不静默）；
- ``--product-id N``：只处理覆盖该产品的 pending 单（与产品级发现同口径）。

``removed`` 行的 ``suspected_manual`` 判定：该行物料键去掉部位后的宽松键
（``_manual_key``：物料/规格/单位/供应商/分类，忽略 role/部位）不在任何目标行中
→ 疑似手工添加行。
部位拆行（旧行无部位、新 BOM 有部位）属 BOM 自身演化，**不**标记为手工行；
真正的删除行无论是否标记都会逐行列出供人工复核（spec：BOM 已不存在的行一律删除）。

用法::

    python scripts/sync_pending_po_items.py                     # dry-run（默认，不写库）
    python scripts/sync_pending_po_items.py --apply             # 实际写库（需显式授权）
    python scripts/sync_pending_po_items.py --product-id 201 --apply

⚠️ 生产数据写入工具：``--apply`` 前先备份数据库，并先跑 dry-run 复核
``removed / suspected_manual``。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))       # scripts/：_prod_write_guard
sys.path.insert(0, str(_HERE.parents[1]))   # 仓库根：fastapi_app

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.exceptions import ItemsVersionConflict
from fastapi_app.services.purchase.bom_sync import (
    _existing_key,
    _target_key,
    find_pending_po_ids_for_product,
    sync_purchase_order_items,
)
from fastapi_app.shared_models import PurchaseOrder, PurchaseOrderItem
from fastapi_app.shared_models.purchase_order import PurchaseOrderStatus


@dataclass
class BackfillReport:
    """一次校正扫描的四类清单（行级明细），供 CLI 打印与测试断言。

    ``matched_unchanged``：匹配键相同且数量/用量也相同的行数（仅为计数，
    不算变更、不逐行打印）。
    """

    dry_run: bool
    scanned: int = 0
    affected_po_ids: list[int] = field(default_factory=list)
    changed: list[dict] = field(default_factory=list)
    added: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)
    matched_unchanged: int = 0
    unresolved: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def _num(value) -> float:
    return float(value or 0)


def _row_snapshot(row: PurchaseOrderItem) -> dict:
    """旧行快照（apply 会整单删旧行，必须先落成纯数据）。"""
    return {
        'key': _existing_key(row),
        'material_name': row.material_name or '',
        'specification': row.specification or '',
        'unit': row.unit or '',
        'part_name': row.part_name,
        'supplier_name': row.supplier_name or '',
        'category': row.material_category or '',
        'quantity': _num(row.quantity),
        'unit_usage': _num(row.unit_usage),
    }


def _base_fields(po_id: int, order_no: str | None, row: dict) -> dict:
    return {
        'po_id': po_id,
        'order_no': order_no,
        'material_name': row['material_name'],
        'specification': row['specification'],
        'unit': row['unit'],
        'part_name': row['part_name'],
        'supplier_name': row['supplier_name'],
        'category': row['category'],
    }


def _target_entry(po_id: int, order_no: str | None, item: dict) -> dict:
    return {
        'po_id': po_id,
        'order_no': order_no,
        'material_name': (item.get('material_name') or '').strip(),
        'specification': (item.get('specification') or '').strip(),
        'unit': (item.get('unit') or '').strip(),
        'part_name': item.get('part_name'),
        'supplier_name': (item.get('supplier_name') or '').strip(),
        'category': (item.get('category') or '').strip(),
        'quantity': _num(item.get('quantity')),
        'unit_usage': _num(item.get('unit_usage')),
    }


def _same_quantity(old: dict, item: dict) -> bool:
    """按落库列精度比较数量/用量（与 ``bom_sync._canonical`` 同口径）。"""
    return (round(old['quantity'], 2) == round(_num(item.get('quantity')), 2)
            and round(old['unit_usage'], 4) == round(_num(item.get('unit_usage')), 4))


def _manual_key(key: tuple) -> tuple:
    """疑似手工判定的物料身份键：**去掉 role 与部位**（物料/规格/单位/供应商/分类）。

    role 是同一物料的「分账维度」而非物料身份（2026-11-11）：历史 pending 单
    的明细 role=NULL（哨兵 0），目标是各角色行（11..N）——若判定键保留 role，
    同一物料的存在性会判否，所有旧行都被误报成「疑似手工」（真实 dry-run
    实测 PO-2611-005 27/27 误报）。
    """
    return (key[1], key[2], key[3], key[5], key[6])


def _classify_rows(po_id: int, order_no: str | None,
                   old_rows: list[dict], target: list[dict],
                   ) -> tuple[list[dict], list[dict], list[dict], int]:
    """按匹配键 multiset 把旧行/目标行配成 changed / added / removed。

    与 ``bom_sync._diff_counts`` 同源：同键两侧各取 min(旧数, 目标数) 配对；
    剩余旧行 = removed，剩余目标行（含同键目标行多于旧行时的多余行）= added，
    故 ``len(changed)+matched_unchanged == updated``、added/removed 逐项相等，
    调用方据此断言（评审 Important：此前多余目标行被 zip 丢弃，导致该单永远
    「报告分类不一致」而无法校正）。

    配对行数量/用量完全一致计入 ``matched_unchanged``（不打印为变更，评审
    Minor 4）——``_diff_counts.updated`` 按键交集计数，包含无变化行。

    ``suspected_manual``：删除行的**物料身份键**（去 role/部位，见 ``_manual_key``）
    不在任何目标行中 → 该物料在当前 BOM 里完全不存在，最可能是手工加行。
    跨部位/跨角色调整的旧行身份键仍命中目标行，不算手工行（2026-11-11 修误报）。
    """
    target_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for item in target:
        target_by_key[_target_key(item)].append(item)
    target_fallback_keys = {_manual_key(_target_key(item)) for item in target}

    old_by_key: dict[tuple, list[dict]] = defaultdict(list)
    for row in old_rows:
        old_by_key[row['key']].append(row)

    changed: list[dict] = []
    added: list[dict] = []
    removed: list[dict] = []
    matched_unchanged = 0
    for key, olds in old_by_key.items():
        bucket = target_by_key.pop(key, [])
        # 同键多行（盲盒角色均分等）按数量排序配对，避免错位后报出虚假的旧→新差值
        olds_sorted = sorted(olds, key=lambda r: r['quantity'])
        bucket_sorted = sorted(bucket, key=lambda t: _num(t.get('quantity')))
        for old, item in zip(olds_sorted, bucket_sorted, strict=False):
            if _same_quantity(old, item):
                matched_unchanged += 1
                continue
            entry = _base_fields(po_id, order_no, old)
            entry.update({
                'old_quantity': old['quantity'],
                'new_quantity': _num(item.get('quantity')),
                'old_unit_usage': old['unit_usage'],
                'new_unit_usage': _num(item.get('unit_usage')),
            })
            changed.append(entry)
        for old in olds_sorted[len(bucket_sorted):]:
            entry = _base_fields(po_id, order_no, old)
            entry.update({
                'quantity': old['quantity'],
                'unit_usage': old['unit_usage'],
                'suspected_manual': _manual_key(key) not in target_fallback_keys,
            })
            removed.append(entry)
        for item in bucket_sorted[len(olds_sorted):]:
            added.append(_target_entry(po_id, order_no, item))

    for bucket in target_by_key.values():
        for item in bucket:
            added.append(_target_entry(po_id, order_no, item))
    return changed, added, removed, matched_unchanged


async def _load_old_rows(db: AsyncSession, po_id: int) -> list[dict]:
    rows = (await db.execute(
        select(PurchaseOrderItem)
        .where(PurchaseOrderItem.order_id == po_id)
        .order_by(PurchaseOrderItem.id)
    )).scalars().all()
    return [_row_snapshot(row) for row in rows]


async def _sync_one(db: AsyncSession, po_id: int, order_no: str | None, *,
                    dry_run: bool, report: BackfillReport) -> None:
    """单张采购单：同步 → 分类 →（apply 提交）→ 落报告；失败回滚并记 errors。

    apply 下**提交成功后才落报告汇总**（评审 Minor 2）：commit 失败时该单
    不显示「已变更」，只进 errors。
    """
    try:
        old_rows = await _load_old_rows(db, po_id)
        res = await sync_purchase_order_items(db, po_id, dry_run=dry_run)
        if res.changed and not res.target_items and old_rows:
            # 目标为空 = 该单覆盖的产品 BOM 已整体删空。在线回调对这种情况走
            # 「撤销采购单」而非「按空 BOM 重建」（Task 5 评审 Important）——
            # 校正脚本没有撤销职责，必须拒绝把明细整单删光，留给人工处置。
            raise RuntimeError(
                '目标明细为空（疑似产品 BOM 已删空，应走撤销链而非同步）'
                '— 拒绝按空 BOM 整单删光明细')
        if res.changed:
            changed, added, removed, matched = _classify_rows(
                po_id, order_no, old_rows, res.target_items)
            actual = (len(changed) + matched, len(added), len(removed))
            expected = (res.updated, res.added, res.removed)
            if actual != expected:
                raise RuntimeError(
                    f'报告分类与服务计数不一致 po_id={po_id}: '
                    f'{actual} != {expected}')
        if not dry_run:
            # 每单独立提交：立即释放 FOR UPDATE 行锁并让单张成败互不牵连
            await db.commit()
        if res.changed:
            report.affected_po_ids.append(po_id)
            report.changed.extend(changed)
            report.added.extend(added)
            report.removed.extend(removed)
            report.matched_unchanged += matched
        elif res.skipped_reason:
            report.unresolved.append({
                'po_id': po_id, 'order_no': order_no,
                'reason': res.skipped_reason,
            })
    except ItemsVersionConflict:
        await db.rollback()
        report.errors.append({
            'po_id': po_id, 'order_no': order_no,
            'reason': 'version_conflict',
        })
    except Exception as exc:  # 逐单隔离：单张失败回滚该单并继续其余采购单
        await db.rollback()
        report.errors.append({
            'po_id': po_id, 'order_no': order_no,
            'reason': f'{type(exc).__name__}: {exc}',
        })


async def run_backfill(db: AsyncSession, *, dry_run: bool = True,
                       product_id: int | None = None) -> BackfillReport:
    """扫描 pending 单执行同步；dry_run 时不写库。返回四类清单。

    ``product_id`` 为 None 时扫描**全部** pending 采购单（逐单解析，解析失败进
    ``unresolved``）；传入时先用产品级发现（``find_pending_po_ids_for_product``）
    收窄范围，只处理覆盖该产品的单。
    """
    report = BackfillReport(dry_run=dry_run)

    if product_id is not None:
        matched, unresolved_ids = await find_pending_po_ids_for_product(db, product_id)
        po_ids = list(matched)
    else:
        po_ids = list((await db.execute(
            select(PurchaseOrder.id)
            .where(PurchaseOrder.status == PurchaseOrderStatus.PENDING)
            .order_by(PurchaseOrder.id)
        )).scalars().all())
        unresolved_ids = []
    report.scanned = len(po_ids)

    all_ids = sorted(set(po_ids) | set(unresolved_ids))
    order_no_map: dict[int, str | None] = {}
    if all_ids:
        order_no_map = dict((await db.execute(
            select(PurchaseOrder.id, PurchaseOrder.order_no)
            .where(PurchaseOrder.id.in_(all_ids))
        )).all())
    for po_id in unresolved_ids:
        report.unresolved.append({
            'po_id': po_id, 'order_no': order_no_map.get(po_id),
            'reason': 'unresolved_sku',
        })

    for po_id in po_ids:
        await _sync_one(db, po_id, order_no_map.get(po_id),
                        dry_run=dry_run, report=report)
    return report


def _describe(row: dict) -> str:
    parts = [row['material_name']]
    if row['specification']:
        parts.append(row['specification'])
    if row['unit']:
        parts.append(row['unit'])
    if row['part_name']:
        parts.append(f'[{row["part_name"]}]')
    if row['supplier_name']:
        parts.append(f'供应商={row["supplier_name"]}')
    return ' '.join(parts)


def _fmt(value: float) -> str:
    return f'{value:g}'


def print_report(report: BackfillReport) -> None:
    mode = 'dry-run（不写库）' if report.dry_run else 'apply（已写库）'
    print(f'=== pending 采购单 BOM 明细校正：{mode} ===')
    print(f'扫描 pending 单 {report.scanned} 张；受影响 '
          f'{len(report.affected_po_ids)} 张')

    by_po: dict[int, dict[str, list[dict]]] = defaultdict(
        lambda: {'changed': [], 'added': [], 'removed': []})
    for name in ('changed', 'added', 'removed'):
        for row in getattr(report, name):
            by_po[row['po_id']][name].append(row)

    for po_id in report.affected_po_ids:
        rows = by_po[po_id]
        first = rows['changed'] or rows['added'] or rows['removed']
        order_no = first[0]['order_no'] if first else None
        print(f'\nPO {po_id} {order_no}: 变更 {len(rows["changed"])} / '
              f'新增 {len(rows["added"])} / 删除 {len(rows["removed"])}')
        for row in rows['changed']:
            print(f'  [变更] {_describe(row)}  数量 '
                  f'{_fmt(row["old_quantity"])} → {_fmt(row["new_quantity"])}'
                  f'（单位用量 {_fmt(row["old_unit_usage"])} → '
                  f'{_fmt(row["new_unit_usage"])}）')
        for row in rows['added']:
            print(f'  [新增] {_describe(row)}  数量 {_fmt(row["quantity"])}')
        for row in rows['removed']:
            flag = '  ← 疑似手工行，删除前请确认' if row['suspected_manual'] else ''
            print(f'  [删除] {_describe(row)}  数量 {_fmt(row["quantity"])}{flag}')

    if report.unresolved:
        print(f'\n解析失败/跳过 {len(report.unresolved)} 张：')
        for item in report.unresolved:
            print(f'  - PO {item["po_id"]} {item["order_no"]}: {item["reason"]}')
    if report.errors:
        print(f'\n执行失败 {len(report.errors)} 张（该单已回滚）：')
        for item in report.errors:
            print(f'  - PO {item["po_id"]} {item["order_no"]}: {item["reason"]}')

    manual = sum(1 for row in report.removed if row['suspected_manual'])
    print(f'\n汇总：变更 {len(report.changed)} 行 / 新增 {len(report.added)} 行 / '
          f'删除 {len(report.removed)} 行（其中疑似手工 {manual} 行）/ '
          f'同键无变化 {report.matched_unchanged} 行（不计变更）/ '
          f'unresolved {len(report.unresolved)} 张 / 失败 {len(report.errors)} 张')
    if report.dry_run:
        print('[dry-run] 未写库。复核无误后加 --apply 执行。')


async def _run(*, dry_run: bool, product_id: int | None) -> int:
    from fastapi_app.core.database import (
        ensure_engine_for_current_loop,
        require_async_session_local,
    )

    await ensure_engine_for_current_loop()
    session_factory = require_async_session_local()
    async with session_factory() as db:
        report = await run_backfill(db, dry_run=dry_run, product_id=product_id)
    print_report(report)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='按当前 BOM 校正存量 pending 采购单明细（默认 dry-run 只读）')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--dry-run', action='store_true',
                       help='只读报告（默认行为）')
    group.add_argument('--apply', action='store_true',
                       help='实际写库（每单独立事务；需显式授权）')
    parser.add_argument('--product-id', type=int, default=None,
                        help='只校正覆盖该产品的 pending 单')
    parser.add_argument('--allow-prod-write', action='store_true',
                        help='写生产库显式授权（等价 ERP_ALLOW_PROD_WRITE=1）')
    args = parser.parse_args()

    if args.apply:
        from _prod_write_guard import require_prod_write_consent
        require_prod_write_consent(
            '按 BOM 重建 pending 采购单明细（backfill）',
            hint='建议先备份数据库，并先跑 --dry-run 复核 removed/suspected_manual',
        )
    return asyncio.run(_run(dry_run=not args.apply, product_id=args.product_id))


if __name__ == '__main__':
    raise SystemExit(main())
