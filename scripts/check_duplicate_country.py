"""检查同一客户+产品的 country_orders 是否有重复国家"""
import asyncio
import sys
sys.path.insert(0, r'd:\erp_system')

from sqlalchemy import text
from fastapi_app.core.database import _AsyncSessionLocal


async def main():
    async with _AsyncSessionLocal() as db:
        r = await db.execute(text('''
            SELECT product_id, customer, country, COUNT(*) AS order_count, SUM(quantity) AS total
            FROM "order"
            WHERE order_type = 'custom' AND is_deleted = false
            GROUP BY product_id, customer, country
            HAVING COUNT(*) > 1
        '''))
        rows = r.all()
        if rows:
            print(f'有重复国家的客户+产品组合: {len(rows)}')
            for row in rows:
                print(f'  product_id={row.product_id}, customer={row.customer}, '
                      f'country={row.country}, order_count={row.order_count}, total={row.total}')
        else:
            print('没有重复国家')


asyncio.run(main())
