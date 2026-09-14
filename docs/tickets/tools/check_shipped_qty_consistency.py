"""P0-02 存量数据一致性校验（**只读**）

用途
----
`_recalc_plans_common` 元数缺陷会让出货创建后的重算**静默中止**，
后果是 `purchase_plan_details.shipped_qty` 停留在旧值 —— 即「存量数据可能已被污染」。
2026-09-10 生产日志（logs/server_manager_20260910.log:345）实证触发过一次。

本脚本核对：**库中存储的 `shipped_qty` 是否等于按当前出货记录重算的结果**。

为什么不手写 SQL
----------------
`shipped_qty` 不是 `SUM(stock_out.quantity)`，而是按 `plan_date ASC` 的**累计 FIFO 分配**，
且还要扣除 `StockOut.returned_quantity`、受出货日期窗口限制、并有 product_id / name 双匹配分支。
手写 SQL 复刻极易产生假阳性，因此这里**直接调用应用自身的 fifo_allocation 代码路径**，
与实际写入 `shipped_qty` 的逻辑完全同源。

安全性
------
- 全程只做 SELECT；末尾显式 `rollback()`，**不写任何数据**
- 传 `plan_month=''` 绕过 Redis 缓存，保证拿到的是重新计算结果
- 不打印客户名以外的敏感字段

运行：
  C:/Users/Administrator/AppData/Local/Programs/Python/Python313/python.exe \
    docs/tickets/tools/check_shipped_qty_consistency.py
"""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))


async def main() -> int:
    from sqlalchemy import select

    from fastapi_app.core.database import get_async_db_context
    from fastapi_app.services.fifo_allocation import _get_shipped_fifo_map
    from fastapi_app.shared_models.purchase_plan import PurchasePlan, PurchasePlanDetail

    async with get_async_db_context() as db:
        details = (await db.execute(select(PurchasePlanDetail))).scalars().all()
        if not details:
            print('purchase_plan_details 为空，无需核对')
            await db.rollback()
            return 0

        plan_ids = {d.plan_id for d in details}
        plans = (
            await db.execute(select(PurchasePlan).where(PurchasePlan.id.in_(plan_ids)))
        ).scalars().all()
        plan_map = {p.id: p.customer_name for p in plans}
        plan_month_map = {p.id: p.plan_month for p in plans}

        print(f'待核对明细: {len(details)} 行，涉及主单 {len(plans)} 张')
        print('-' * 100)

        # ⚠️ 必须先把需要的字段取成普通数据：rollback() 会使 ORM 实例过期，
        #    之后再读属性会触发懒加载同步 IO → MissingGreenlet。
        rows = [
            {
                'detail_id': d.id,
                'plan_id': d.plan_id,
                'product': d.product_name,
                'quantity': d.quantity,
                'shipped_qty': d.shipped_qty,
            }
            for d in details
        ]

        try:
            # plan_month='' → 绕过 Redis 缓存，强制重新计算
            fifo = await _get_shipped_fifo_map(db, list(details), plan_map, '')
        except RuntimeError as e:
            print(f'⚠️ FIFO 重算不可用（{e}），无法判定。这本身不是数据问题，请在有库连接的环境重跑。')
            await db.rollback()
            return 2
        finally:
            await db.rollback()   # 只读保证：不做任何写入

        mismatches = []
        for r in rows:
            expected = fifo.get(r['detail_id'], 0)
            if r['shipped_qty'] != expected:
                mismatches.append({
                    'detail_id': r['detail_id'],
                    'customer': plan_map.get(r['plan_id'], '?'),
                    'plan_month': plan_month_map.get(r['plan_id'], '?'),
                    'product': r['product'],
                    'quantity': r['quantity'],
                    'stored_shipped_qty': r['shipped_qty'],
                    'expected_shipped_qty': expected,
                })

        if not mismatches:
            print(f'✅ 一致性通过：{len(details)} 行明细的 shipped_qty 全部等于重算值')
            return 0

        print(f'🔴 发现 {len(mismatches)} 行 shipped_qty 与重算值不一致：')
        print()
        header = f"{'detail_id':>9} {'客户':<22} {'月份':<8} {'产品':<26} {'plan_qty':>8} {'stored':>7} {'expect':>7}"
        print(header)
        print('-' * len(header))
        for m in mismatches:
            print(
                f"{m['detail_id']:>9} {m['customer'][:20]:<22} {m['plan_month']:<8} "
                f"{str(m['product'])[:24]:<26} {m['quantity']:>8} "
                f"{m['stored_shipped_qty']:>7} {m['expected_shipped_qty']:>7}"
            )
        print()
        print('判读：')
        print('  · stored < expect → 重算未跟上，符合本缺陷特征（出货后 shipped_qty 未更新）')
        print('  · stored > expect → 需查是否有其它写入路径，不能直接归因本缺陷')
        print('  · 修数前请先确认对应出货记录本身是否正确')
        return 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
