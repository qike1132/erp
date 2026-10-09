"""product 20857 负库存对平脚本（2026-10-05 迭代遗留修复）

背景
----
2026-10-05 下午 ALLOW_NEGATIVE_STOCK 生效窗口内，页面真实提交的出货
SO-20261005-0002（1）+ SO-20261005-0003（10000）（客户"网易"，订单
PO-20260929-0014）把 product 20857 库存扣成 -13001。负库存改动已全量
回滚（见 docs/iteration-review-2026-10-05.md），但该存量行被 NOT VALID
的约束豁免。用户拍板：补 +13001 对平后 VALIDATE 约束。

做法（应用同源代码路径，不裸写 SQL）
----
1. get_product_for_update 行锁下读当前库存；
2. 仅当 current_stock == -13001 时执行（幂等闸：库存已被人工处理过则跳过）；
3. update_stock_with_optimistic_lock(db, 20857, +13001) —— 与页面入库
   同一写入口（乐观锁 + 流水一致）；
4. log_inventory_change(change_type='入库', note='2026-10-05 负库存对平：
   冲平 ALLOW_NEGATIVE_STOCK 窗口期误扣的出货 SO-20261005-0002/0003')；
5. 同事务 VALIDATE 约束（存量负值清零后应通过）；
6. 全程单事务提交，失败自动回滚零痕迹。

用法
----
    .venv/Scripts/python.exe scripts/diag/reconcile_20857_negative_stock.py [--dry-run]
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PRODUCT_ID = 20857
EXPECTED_NEGATIVE = -13001
ADJUSTMENT = 13001
RELATED_STOCKOUTS = 'SO-20261005-0002,SO-20261005-0003'
NOTE = '2026-10-05 负库存对平：冲平策略窗口期出货 SO-20261005-0002/0003 的超额扣减'


async def main(dry_run: bool) -> int:
    from fastapi_app.core.database import get_async_db
    from fastapi_app.shared.stock_concurrency import (
        get_product_for_update,
        update_stock_with_optimistic_lock,
    )
    from fastapi_app.utils import log_inventory_change

    async for db in get_async_db():
        product = await get_product_for_update(db, PRODUCT_ID)
        current = product.current_stock
        print(f'锁定产品 {PRODUCT_ID}「{product.name}」当前库存: {current}')

        if current != EXPECTED_NEGATIVE:
            print(f'跳过：当前库存 {current} != 预期 {EXPECTED_NEGATIVE}，'
                  '库存已被处理过（幂等闸生效），不做任何修改。')
            return 0

        if dry_run:
            print(f'[dry-run] 将执行：库存 +{ADJUSTMENT} -> 0，'
                  f'写流水 change_type=入库，note={NOTE!r}，随后 VALIDATE 约束。')
            await db.rollback()
            return 0

        await update_stock_with_optimistic_lock(db, PRODUCT_ID, ADJUSTMENT)
        log_inventory_change(
            db, product_id=PRODUCT_ID,
            change_type='入库', change_quantity=ADJUSTMENT,
            related_id='', note=NOTE,
        )
        await db.flush()

        # 对平后立即 VALIDATE：若期间又出现负值会在此暴露（事务一并回滚）
        from sqlalchemy import text
        await db.execute(text(
            'ALTER TABLE product VALIDATE CONSTRAINT ck_product_current_stock_nonneg'
        ))

        await db.commit()
        print(f'完成：库存 {current} -> 0；流水已记；约束已 VALIDATE。')
        return 0
    return 1


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
    from _prod_write_guard import require_prod_write_consent
    if '--dry-run' not in sys.argv:
        require_prod_write_consent('对平 product 20857 负库存（+13001 并 VALIDATE 约束）',
                                   hint='走服务层写入口，单事务；幂等闸只认库存恰为 -13001')
    raise SystemExit(asyncio.run(main('--dry-run' in sys.argv)))
