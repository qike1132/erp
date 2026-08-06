"""检查 order_type 字段的实际情况"""
import asyncio
import sys
sys.path.insert(0, r'd:\erp_system')

from sqlalchemy import select, func, text
from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models import Order, Product


async def main():
    async with _AsyncSessionLocal() as db:
        print('=== order_type 取值分布 ===')
        r = await db.execute(text('''
            SELECT order_type, COUNT(*) AS cnt, SUM(quantity) AS total_qty
            FROM "order"
            WHERE is_deleted = false
            GROUP BY order_type
            ORDER BY cnt DESC
        '''))
        for row in r.all():
            print(f'  order_type="{row.order_type}" ({type(row.order_type).__name__}), '
                  f'count={row.cnt}, total_qty={row.total_qty}')

        print('\n=== 10寸企鹅的所有订单详情 ===')
        r = await db.execute(select(Product).where(Product.name == '10寸企鹅'))
        p = r.scalar_one_or_none()
        if p:
            r = await db.execute(
                select(Order).where(Order.product_id == p.id, Order.customer == 'MINISO国际', Order.is_deleted == False)
            )
            orders = r.scalars().all()
            print(f'  共 {len(orders)} 条')
            for o in orders:
                print(f'    id={o.id}, qty={o.quantity}, order_type="{o.order_type}" '
                      f'({type(o.order_type).__name__}), country="{o.country}"')

        # 直接模拟 CTE 计算
        print('\n=== 模拟 CTE: 10寸企鹅+MINISO国际 的 order_agg ===')
        r = await db.execute(text('''
            SELECT
              SUM(CASE WHEN order_type IS NULL OR order_type = 'regular' THEN quantity ELSE 0 END) AS regular_qty,
              SUM(CASE WHEN order_type = 'custom' THEN quantity ELSE 0 END) AS custom_qty
            FROM "order"
            WHERE product_id = (SELECT id FROM product WHERE name='10寸企鹅')
              AND customer = 'MINISO国际'
              AND is_deleted = false
        '''))
        row = r.first()
        print(f'  regular_qty={row.regular_qty}, custom_qty={row.custom_qty}')

        # 再看 country_agg
        print('\n=== 模拟 CTE: country_agg ===')
        r = await db.execute(text('''
            SELECT COALESCE(country, '常规') AS country, SUM(quantity) AS qty
            FROM "order"
            WHERE product_id = (SELECT id FROM product WHERE name='10寸企鹅')
              AND customer = 'MINISO国际'
              AND is_deleted = false
              AND order_type = 'custom'
            GROUP BY COALESCE(country, '常规')
        '''))
        for row in r.all():
            print(f'  country="{row.country}", qty={row.qty}')


asyncio.run(main())
