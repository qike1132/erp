"""检查11寸企鹅的生产记录是否有 product_id"""
import asyncio
import sys
sys.path.insert(0, r'd:\erp_system')

from sqlalchemy import select, text
from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models import Product
from fastapi_app.shared_models.daily_production_record import DailyProductionRecord


async def main():
    async with _AsyncSessionLocal() as db:
        # 1. 找11寸企鹅产品
        print('=== 1. 产品库中的11寸企鹅 ===')
        r = await db.execute(select(Product).where(Product.name.like('%11寸企鹅%')))
        products = r.scalars().all()
        for p in products:
            print(f'  product_id={p.id}, name="{p.name}", barcode={p.barcode}')

        if not products:
            print('  -> 产品库中没有此产品！请先在产品库中创建。')
            return

        product_ids = [p.id for p in products]

        # 2. 生产记录详情
        print('\n=== 2. daily_production_record 中匹配的记录 ===')
        r = await db.execute(
            select(DailyProductionRecord)
            .where(DailyProductionRecord.product_name.like('%11寸企鹅%'))
            .order_by(DailyProductionRecord.id.desc())
            .limit(10)
        )
        rows = r.scalars().all()
        for rec in rows:
            print(f'  id={rec.id}, product_id={rec.product_id} ({"NULL" if rec.product_id is None else "OK"}), '
                  f'name="{rec.product_name}", qty={rec.quantity}, dept={rec.department}, '
                  f'barcode={rec.barcode}, date={rec.production_date}')

        if not rows:
            print('  -> 生产表中没有11寸企鹅的记录！')
            return

        # 3. 按 product_id 聚合模拟 production_agg
        print('\n=== 3. production_agg CTE 模拟（按 product_id IS NOT NULL 过滤）===')
        r = await db.execute(text('''
            SELECT product_id, SUM(quantity) AS production_qty
            FROM daily_production_record
            WHERE product_id IS NOT NULL
              AND product_id = ANY(:pids)
            GROUP BY product_id
        '''), {'pids': tuple(product_ids)})
        for row in r.all():
            print(f'  product_id={row.product_id}, production_qty={row.production_qty}')

        # 4. 对比：包含 NULL 的总数
        print('\n=== 4. 不带 IS NOT NULL 过滤的总量（含 product_id IS NULL）===')
        r = await db.execute(text('''
            SELECT product_id, product_name, SUM(quantity) AS total_qty
            FROM daily_production_record
            WHERE product_name LIKE '%11寸企鹅%'
            GROUP BY product_id, product_name
        '''))
        for row in r.all():
            print(f'  product_id={row.product_id} ({"NULL!" if row.product_id is None else "OK"}), '
                  f'name="{row.product_name}", total_qty={row.total_qty}')


asyncio.run(main())
