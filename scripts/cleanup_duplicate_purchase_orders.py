#!/usr/bin/env python
"""
清理历史重复采购订单脚本

针对 /purchase 一键审核可能产生的重复采购单进行一次性清理。

清理规则（同一"业务组"内只保留最早的一条 pending 采购单）：
- 业务组 = (source_order_ids JSON 集合归一化, customer_name, supplier_name)
- 仅清理 status='pending' 的采购单（不影响 confirmed/completed）
- 同一 (customer_name, supplier_name, source_order_ids) 下创建时间差 ≤ 60 秒的多条
  pending 单视为重复，保留最早一条
- 关联的下游记录（purchase_order_item）随订单一起删除

用法：
    # 仅扫描，不实际删除（推荐先 dry-run）
    python scripts/cleanup_duplicate_purchase_orders.py --dry-run

    # 真正执行删除
    python scripts/cleanup_duplicate_purchase_orders.py --apply

    # 限定时间窗口（默认 30 天内）
    python scripts/cleanup_duplicate_purchase_orders.py --days 7 --apply

退出码：
    0 - 成功（或 dry-run 完成）
    1 - 错误
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

# 允许在项目根目录运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from fastapi_app.core.database import get_async_db_context  # noqa: E402
from fastapi_app.shared_models import PurchaseOrder, PurchaseOrderItem  # noqa: E402


REPEAT_WINDOW_SECONDS = 60  # 同一业务组内"重复"判定时间窗


def _normalize_source_ids(raw: str | None) -> frozenset[int]:
    """将 source_order_ids JSON 字符串规范化为不可变集合（忽略空 / 无效值）"""
    if not raw:
        return frozenset()
    try:
        ids = json.loads(raw)
    except (ValueError, TypeError):
        return frozenset()
    if not isinstance(ids, list):
        return frozenset()
    return frozenset(int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit())


def _group_key(po: PurchaseOrder) -> tuple:
    """重复订单的分组 key：客户 + 供应商 + 关联源订单集合。"""
    return (
        po.customer_name or '',
        po.supplier_name or '',
        _normalize_source_ids(po.source_order_ids),
    )


async def find_duplicate_groups(db: AsyncSession, since: datetime) -> list[list[PurchaseOrder]]:
    """找出所有满足重复条件的订单组（每组 ≥ 2 条 pending 单）。

    仅扫描 since 之后、status='pending' 的采购单。
    """
    result = await db.execute(
        select(PurchaseOrder)
        .where(
            PurchaseOrder.status == 'pending',
            PurchaseOrder.create_time >= since,
        )
        .order_by(PurchaseOrder.create_time.asc())
    )
    pending_orders: list[PurchaseOrder] = list(result.scalars().all())

    # 按业务组聚合
    groups: dict[tuple, list[PurchaseOrder]] = {}
    for po in pending_orders:
        groups.setdefault(_group_key(po), []).append(po)

    # 仅保留真正的重复组：组内 ≥ 2 条且创建时间差均在窗口内
    duplicates: list[list[PurchaseOrder]] = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        # 取最早一条作为"基准"，其余与基准比较
        base = items[0]
        same_window = [base]
        for other in items[1:]:
            dt = (other.create_time - base.create_time).total_seconds()
            if abs(dt) <= REPEAT_WINDOW_SECONDS:
                same_window.append(other)
        if len(same_window) >= 2:
            duplicates.append(same_window)
    return duplicates


async def delete_purchase_orders(db: AsyncSession, orders: Iterable[PurchaseOrder]) -> int:
    """删除指定采购单及其明细。返回被删除订单数。"""
    order_ids = [o.id for o in orders if o.id is not None]
    if not order_ids:
        return 0
    # 先删明细，再删主单（避免外键悬挂）
    await db.execute(delete(PurchaseOrderItem).where(PurchaseOrderItem.order_id.in_(order_ids)))
    await db.execute(delete(PurchaseOrder).where(PurchaseOrder.id.in_(order_ids)))
    await db.commit()
    return len(order_ids)


async def main_async(args: argparse.Namespace) -> int:
    days = args.days
    since = datetime.now() - timedelta(days=days)
    print(f'[cleanup] 扫描范围：{since.isoformat(timespec="seconds")} 之后，窗口 {days} 天')
    print(f'[cleanup] 重复判定窗口：{REPEAT_WINDOW_SECONDS} 秒')
    print(f'[cleanup] 模式：{"DRY-RUN" if args.dry_run else "APPLY"}')
    print('-' * 60)

    total_deleted = 0
    async with get_async_db_context() as db:
        groups = await find_duplicate_groups(db, since=since)
        if not groups:
            print('[cleanup] 未发现重复采购订单 ✓')
            return 0

        print(f'[cleanup] 发现 {len(groups)} 组重复订单：')
        for idx, group in enumerate(groups, 1):
            key = _group_key(group[0])
            ids = [o.id for o in group]
            created = [o.create_time.isoformat(timespec='seconds') for o in group]
            print(
                f'  #{idx:>2}  customer={key[0]!r} supplier={key[1]!r} '
                f'source_ids={sorted(key[2])}'
            )
            print(f'        共 {len(group)} 条：ids={ids} created={created}')

            # 保留最早一条
            kept = group[0]
            to_delete = group[1:]
            print(f'        保留 id={kept.id} (最早)  删除 {[o.id for o in to_delete]}')

            if args.apply and not args.dry_run:
                deleted = await delete_purchase_orders(db, to_delete)
                total_deleted += deleted
                print(f'        -> 已删除 {deleted} 条')
            print()

    print('-' * 60)
    if args.dry_run:
        print(f'[cleanup] DRY-RUN 完成。如需实际删除，请加 --apply 参数。')
    else:
        print(f'[cleanup] 实际删除：{total_deleted} 条采购订单')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='清理历史重复的采购订单')
    parser.add_argument(
        '--apply', action='store_true',
        help='实际执行删除（不指定时为 dry-run 模式）',
    )
    parser.add_argument(
        '--dry-run', action='store_true', default=True,
        help='仅扫描不删除（默认行为，--apply 时自动关闭）',
    )
    parser.add_argument(
        '--days', type=int, default=30,
        help='扫描时间窗口（天），默认 30',
    )
    args = parser.parse_args()
    if args.apply:
        args.dry_run = False
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print('\n[cleanup] 用户中断', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
