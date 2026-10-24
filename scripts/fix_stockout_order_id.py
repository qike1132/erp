"""修复历史出货记录的订单ID关联（默认 dry-run，--apply 才写库）。

将没有关联订单ID的出货记录按 FIFO 原则关联到对应订单。

2026-10-24 审计 P1 修复：
1. 默认 dry-run，只打印候选映射；`--apply` 才写库，且必须通过生产写授权；
2. 接入 `require_prod_write_consent`（本区 49 个写库脚本都有，此脚本原先漏接）；
3. **同产品同客户存在多张可容纳订单时跳过并告警** —— 原先「取第一张 available>0 的
   订单」，同产品同客户的多次出货必然错配，且错误关联会污染订单状态、备货抵扣与
   报表口径，没有回滚脚本；
4. 输出待改 id 清单，便于人工复核或反向回退。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func

from fastapi_app.core.database import SyncSessionLocal
from fastapi_app.shared_models import Order, StockOut


def _plan(session) -> tuple[list[tuple[int, int]], list[str]]:
    """返回 (可安全关联的 [(stockout_id, order_id)], 跳过原因列表)。"""
    stockouts = session.query(StockOut).filter(
        StockOut.order_id.is_(None),
        StockOut.stockin_id.is_(None),
        StockOut.customer.isnot(None),
        StockOut.customer != '',
    ).order_by(StockOut.stockout_date.asc()).all()

    print(f"找到 {len(stockouts)} 条候选出货记录")
    plan: list[tuple[int, int]] = []
    skipped: list[str] = []

    for stockout in stockouts:
        orders = session.query(Order).filter_by(
            product_id=stockout.product_id,
            customer=stockout.customer,
        ).order_by(Order.order_date.asc()).all()
        if not orders:
            skipped.append(f"{stockout.stockout_no}: 没有对应订单")
            continue

        candidates = []
        for order in orders:
            already_shipped = session.query(func.sum(StockOut.quantity)).filter(
                StockOut.order_id == order.id,
                StockOut.stockin_id.is_(None),
                StockOut.id != stockout.id,
            ).scalar() or 0
            if order.quantity - already_shipped > 0:
                candidates.append(order)

        if not candidates:
            skipped.append(f"{stockout.stockout_no}: 相关订单均无剩余可出货量")
            continue
        if len(candidates) > 1:
            # 多张订单都能容纳：FIFO 猜测必然可能错配，交人工判定
            skipped.append(
                f"{stockout.stockout_no}: 同产品同客户有 {len(candidates)} 张可容纳订单"
                f"（{','.join(o.order_no for o in candidates[:3])}），需人工确认"
            )
            continue

        plan.append((stockout.id, candidates[0].id))
        print(f"  候选：出货 {stockout.stockout_no} → 订单 {candidates[0].order_no}")

    return plan, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="修复历史出货记录的订单ID关联")
    parser.add_argument('--apply', action='store_true', help='真正写库（默认只预览）')
    args = parser.parse_args()

    session = SyncSessionLocal()
    try:
        plan, skipped = _plan(session)

        if skipped:
            print(f"\n跳过 {len(skipped)} 条：")
            for line in skipped[:50]:
                print(f"  - {line}")
            if len(skipped) > 50:
                print(f"  ...（共 {len(skipped)} 条）")

        if not plan:
            print("\n没有可安全自动关联的记录。")
            return 0

        print(f"\n待关联 {len(plan)} 条：ids={[sid for sid, _ in plan]}")
        if not args.apply:
            print("\n[DRY RUN] 未写库。确认清单后加 --apply 执行。")
            return 0

        from _prod_write_guard import require_prod_write_consent

        require_prod_write_consent(
            f'改写 {len(plan)} 条历史出货记录的 order_id 关联',
            hint='该关联会影响订单状态/备货抵扣/报表口径，且无自动回退；请先备份 stock_out。',
        )

        updated = 0
        for stockout_id, order_id in plan:
            stockout = session.get(StockOut, stockout_id)
            if stockout is None or stockout.order_id is not None:
                continue
            stockout.order_id = order_id
            updated += 1
        session.commit()
        print(f"\n已写入 {updated} 条关联。")
        return 0
    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
