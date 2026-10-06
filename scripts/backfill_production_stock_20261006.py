"""一次性补录：历史生产记录同步入库存（2026-10-06「生产即入库」裁决）。

背景：daily_production_record 此前不写库存；联动上线后新录入自动入账，
但上线前已录入的历史记录（含用户当天已录的 8888）需要一次性补入
product.current_stock，否则出货仍报库存不足。

幂等：InventoryLog.idem_key = 'prod_backfill:{record.id}'，依赖
uq_inventory_log_idem 部分唯一索引——重复执行自动跳过已补录行。

用法（从仓库根目录运行）：
  python scripts/backfill_production_stock_20261006.py            # dry-run
  python scripts/backfill_production_stock_20261006.py --execute  # 备份后执行
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from fastapi_app.shared.stock_concurrency import get_product_for_update
from fastapi_app.shared_models import DailyProductionRecord, InventoryLog, Product


async def main(execute: bool) -> int:
    from fastapi_app.core.database import (
        ensure_engine_for_current_loop,
        require_async_session_local,
    )

    await ensure_engine_for_current_loop()
    session_factory = require_async_session_local()

    async with session_factory() as db:
        records = (await db.execute(
            select(DailyProductionRecord).where(DailyProductionRecord.product_id.is_not(None))
        )).scalars().all()

        # 已补录过的记录（幂等键命中即跳过）
        done_ids = set((await db.execute(
            select(InventoryLog.related_id).where(
                InventoryLog.idem_key.like('prod_backfill:%'))
        )).scalars().all())

        todo = [r for r in records if str(r.id) not in done_ids]
        skipped = len(records) - len(todo)
        print(f'历史生产记录（含产品档案）：{len(records)} 条；已补录：{skipped} 条；待补录：{len(todo)} 条')

        # 未匹配产品档案的记录无法入库存（与 available_stock 口径一致）
        product_ids = sorted({r.product_id for r in todo})
        products = {p.id: p for p in (await db.execute(
            select(Product).where(Product.id.in_(product_ids))
        )).scalars().all()} if product_ids else {}

        by_product: dict[int, int] = {}
        skipped_no_product = 0
        for r in todo:
            if r.product_id not in products:
                skipped_no_product += 1
                continue
            by_product[r.product_id] = by_product.get(r.product_id, 0) + r.quantity

        print(f'按产品汇总：{len(by_product)} 个产品将增加库存'
              + (f'；{skipped_no_product} 条未匹配产品档案，跳过' if skipped_no_product else ''))
        for pid, qty in sorted(by_product.items()):
            print(f'  - {products[pid].name} (id={pid}) +{qty}')

        if not by_product:
            print('无需补录')
            return 0

        if not execute:
            print('\n[dry-run] 未做任何修改。确认无误后加 --execute 执行。')
            return 0

        backup_dir = Path('logs')
        backup_dir.mkdir(exist_ok=True)
        backup_path = backup_dir / f'production_stock_backfill_backup_{datetime.now().strftime("%Y%m%d-%H%M%S")}.json'
        backup_path.write_text(json.dumps({
            'schema_version': 1,
            'backfilled_at': datetime.now().isoformat(),
            'products_before': {
                str(pid): {'current_stock': products[pid].current_stock, 'delta': qty}
                for pid, qty in by_product.items()
            },
            'records': [r.to_dict() if hasattr(r, 'to_dict') else {'id': r.id, 'quantity': r.quantity} for r in todo],
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'备份已写入：{backup_path}')

        total_logs = 0
        for r in todo:
            if r.product_id not in products:
                continue
            product = await get_product_for_update(db, r.product_id)
            if product is None:
                continue
            product.current_stock += r.quantity
            db.add(InventoryLog(
                product_id=r.product_id,
                change_type='生产入库',
                change_quantity=r.quantity,
                related_id=str(r.id),
                idem_key=f'prod_backfill:{r.id}',
                note=f'历史生产补录 {r.department} {r.production_date}',
            ))
            total_logs += 1
        await db.commit()
        print(f'补录完成：库存流水 {total_logs} 条（事务已提交）')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='历史生产记录一次性补入库存')
    parser.add_argument('--execute', action='store_true', help='真正执行（默认 dry-run）')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.execute)))
