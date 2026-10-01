"""历史回填：为既有的 completed 采购单补写逐 SKU 数量快照（purchase_order_sku）。

**背景**（方案 C 治本，见 ``evidence/beile_multisku/多SKU订单数量显示-根因与方案.md``）：
采购单主表只存订单级合计（product_quantity / spare_quantity），逐 SKU 下单量未持久化。
新增 ``purchase_order_sku`` 表后，需要在库中对**历史**采购单补写逐 SKU 行。

**口径**（与写路径 ``services/purchase_order_sku.build_po_sku_rows`` 完全同源）：
- 每张 completed 采购单解析 ``source_order_ids``；
- 对每个来源记录（Order 取 ``items``，StockIn 取单 SKU）取该 SKU 的数量；
- 同 (来源类型, 来源id, 产品名) 合并为一行；``order_qty`` 为合并后数量；
- ``spare_qty = calc_spare_quantity(order_qty, po.spare_rate)``。

**硬要求**：
1. **幂等**：按采购单「先删后插」（``DELETE FROM purchase_order_sku WHERE po_id=?``），
   可重复执行而不产生重复行；
2. **默认 dry-run**：只有显式 ``--apply`` 才写库；
3. 打印**每张采购单**的对账结果，并把「数值不一致」（Σ order_qty 与主表不符）与
   「源记录缺失」（source_order_ids 指向的记录已不存在）**分成两类**分别计数与列出；
   源记录缺失单不写任何逐 SKU 行（读路径降级为订单级），**绝不静默写 0 值行**；
4. ``--apply`` 前必须打印将影响的行数。

用法::

    python scripts/backfill_purchase_order_sku.py            # 只看对账，不写库
    python scripts/backfill_purchase_order_sku.py --apply    # 实际写库（幂等）

⚠️ 本脚本是生产数据写入工具，执行 ``--apply`` 前请先备份数据库并确认迁移已执行。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# 允许直接 `python scripts/backfill_purchase_order_sku.py` 运行（把仓库根加入 sys.path）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload, sessionmaker

from fastapi_app.core.config import settings
from fastapi_app.services.purchase_order_sku import build_po_sku_rows
from fastapi_app.services.purchase_utils import parse_source_order_ids
from fastapi_app.shared_models import (
    Order,
    Product,
    PurchaseOrder,
    PurchaseOrderSku,
    PurchaseOrderStatus,
    StockIn,
)

_COMPLETED = PurchaseOrderStatus.COMPLETED

# ==================== 对账分类 ====================
# 逐采购单的派生结果分类，用于把「源记录缺失」（脏数据）与「数值不一致」（疑似算法错）分开：
_DERIVED = 'derived'                 # 成功派生逐 SKU 行（再与主表 product_quantity 比对得 ok/mismatch）
_SOURCE_MISSING = 'source_missing'   # 有 source_order_ids，但所指向的订单/备货记录不存在
_NO_SOURCE_IDS = 'no_source_ids'     # source_order_ids 为空（无来源可依）


async def _load_source_records(db: AsyncSession, source_ids: list[int], order_ids: list[int], stockin_ids: list[int]):
    """按类型加载来源记录（Order 预加载 items；StockIn 单记录）。"""
    orders: list = []
    if order_ids:
        result = await db.execute(
            select(Order).options(selectinload(Order.items)).where(Order.id.in_(order_ids))
        )
        orders = list(result.scalars().all())
    stockins: list = []
    if stockin_ids:
        result = await db.execute(select(StockIn).where(StockIn.id.in_(stockin_ids)))
        stockins = list(result.scalars().all())
    return orders, stockins


async def _collect_product_ids(records) -> list[int]:
    pids: set[int] = set()
    for rec in records:
        items = getattr(rec, 'items', None)
        if items:
            pids.update(it.product_id for it in items)
        else:
            pids.add(rec.product_id)
    return list(pids)


async def _plan_for_po(db: AsyncSession, po) -> tuple[list[dict], float, str, list[int]]:
    """为单张采购单计算待写入行与 Σ order_qty（不写库），并给出分类。

    Returns:
        (rows, total_order_qty, kind, missing_source_ids)
        - kind=_DERIVED        ：派生成功，rows/total 有效；
        - kind=_SOURCE_MISSING ：有 source_order_ids 但来源记录不存在，rows=[]，
          ``missing_source_ids`` 为声明了却查不到的 id；
        - kind=_NO_SOURCE_IDS  ：source_order_ids 为空，rows=[]。
    """
    source_ids = parse_source_order_ids(po.source_order_ids)
    if not source_ids:
        return [], 0.0, _NO_SOURCE_IDS, []
    # 订单与备货 id 会撞号：分别加载后合并（本脚本按 id 覆盖两张表，无害）
    orders, stockins = await _load_source_records(db, source_ids, source_ids, source_ids)
    records = list(orders) + list(stockins)
    if not records:
        # 声明的来源记录一条都不存在 → 源记录缺失（脏数据），不当成「数值不一致」
        return [], 0.0, _SOURCE_MISSING, list(source_ids)
    pids = await _collect_product_ids(records)
    pid_name_map: dict[int, str] = {}
    if pids:
        name_rows = await db.execute(select(Product.id, Product.name).where(Product.id.in_(pids)))
        pid_name_map = dict(name_rows.all())
    rows = build_po_sku_rows(records, pid_name_map, po.spare_rate)
    total_order_qty = sum(float(r['order_qty'] or 0) for r in rows)
    return rows, total_order_qty, _DERIVED, []


async def _run(apply: bool) -> int:
    engine = create_async_engine(settings.ASYNC_DATABASE_URL, echo=False)
    maker = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    exit_code = 0
    try:
        async with maker() as db:
            pos = (await db.execute(
                select(PurchaseOrder).where(PurchaseOrder.status == _COMPLETED).order_by(PurchaseOrder.id)
            )).scalars().all()

            print(f'completed 采购单总数：{len(pos)}')
            plan: list[tuple] = []
            for po in pos:
                rows, total, kind, missing = await _plan_for_po(db, po)
                plan.append((po, rows, total, kind, missing))

            total_rows = sum(len(r) for _po, r, _t, _k, _m in plan)
            ok_items: list[str] = []
            mismatches: list[tuple] = []
            source_missing: list[tuple] = []
            no_source_ids: list[str] = []
            print('\n=== 逐采购单对账（Σ order_qty vs 主表 product_quantity） ===')
            for po, rows, total, kind, missing in plan:
                product_quantity = float(po.product_quantity or 0)
                if kind == _SOURCE_MISSING:
                    # 来源记录不存在（脏数据）：不参与数值对账，跳过不写
                    print(f'⛔PO {po.id} {po.order_no}: 源记录缺失 '
                          f'(source_order_ids={missing}) → 跳过，不写任何逐 SKU 行')
                    source_missing.append((po.order_no, missing))
                    continue
                if kind == _NO_SOURCE_IDS:
                    print(f'⛔PO {po.id} {po.order_no}: 无 source_order_ids → 跳过，不写任何逐 SKU 行')
                    no_source_ids.append(po.order_no)
                    continue
                matched = abs(total - product_quantity) < 1e-6
                flag = 'OK ' if matched else '❌ '
                print(f'{flag}PO {po.id} {po.order_no}: Σ order_qty={total:g} '
                      f'product_quantity={product_quantity:g} 行数={len(rows)}')
                if matched:
                    ok_items.append(po.order_no)
                else:
                    mismatches.append((po.order_no, total, product_quantity))

            print(f'\n待写入快照行合计：{total_rows}')
            print(
                f'对账一致：{len(ok_items)} 张；数值不一致：{len(mismatches)} 张；'
                f'源记录缺失：{len(source_missing)} 张；无 source_order_ids：{len(no_source_ids)} 张'
            )
            if mismatches:
                print(f'数值不一致 {len(mismatches)} 张（Σ 与主表 product_quantity 不符，疑似算法/数据问题）:')
                for order_no, total, pq in mismatches:
                    print(f'  - {order_no}: Σ={total:g} != 主表 {pq:g}')
            if source_missing:
                print(f'源记录缺失 {len(source_missing)} 张'
                      f'（source_order_ids 指向的订单/备货记录已不存在；跳过不写，读路径降级为订单级）:')
                for order_no, missing in source_missing:
                    print(f'  - {order_no}: 缺失 id {missing}')
            if no_source_ids:
                print(f'无 source_order_ids {len(no_source_ids)} 张（跳过不写）: '
                      + ', '.join(str(x) for x in no_source_ids))

            # 失败判定：仅「数值不一致」视为失败（疑似算法错）；
            # 「源记录缺失 / 无来源」属脏数据，行为是显式跳过降级，不算失败。
            exit_code = 1 if mismatches else 0

            if not apply:
                print('\n[dry-run] 未写库。加 --apply 才实际写入。')
                return exit_code

            print(f'\n[apply] 将写入 {total_rows} 行（逐单先删后插，幂等；源缺失/无来源单跳过）…')
            for po, rows, _total, kind, _missing in plan:
                if kind != _DERIVED:
                    # 源记录缺失 / 无来源：不写任何逐 SKU 行（**不得静默写 0 值行**），
                    # 也不删除既有行 → 该采购单读路径降级为订单级口径。
                    continue
                await db.execute(
                    delete(PurchaseOrderSku).where(PurchaseOrderSku.po_id == po.id)
                )
                for row in rows:
                    db.add(PurchaseOrderSku(po_id=po.id, **row))
            await db.commit()
            print(f'[apply] 完成，已写入 {total_rows} 行。')
    finally:
        await engine.dispose()
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description='回填 completed 采购单的逐 SKU 数量快照')
    parser.add_argument('--apply', action='store_true', help='实际写库（默认 dry-run 只对账）')
    args = parser.parse_args()
    return asyncio.run(_run(apply=args.apply))


if __name__ == '__main__':
    raise SystemExit(main())
