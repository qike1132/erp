"""复现"定制订单美国"库存未显示问题"""
import asyncio
import sys

sys.path.insert(0, r'd:\erp_system')

from sqlalchemy import text

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.services.stock_service import get_inventory_paginated


async def main():
    async with _AsyncSessionLocal() as db:
        print('=== 场景1: 不传国家参数（应能返回所有类型库存）===')
        result = await get_inventory_paginated(
            db, search_customer='', search_product='', country='', page=1, per_page=50
        )
        for item in result['inventory_data']:
            co = item.get('country_orders', {})
            if co:
                print(f'  客户={item["customer"]}, 产品={item["product_name"]}, '
                      f'国家订单={co}, available_stock={item.get("available_stock")}')

        print('\n=== 场景2: 传 country="美国"（定制订单国家）===')
        result2 = await get_inventory_paginated(
            db, search_customer='', search_product='', country='美国', page=1, per_page=50
        )
        print(f'  total_items={result2["total_items"]}')
        for item in result2['inventory_data']:
            print(f'  客户={item["customer"]}, 产品={item["product_name"]}, '
                  f'国家订单={item.get("country_orders")}, available_stock={item.get("available_stock")}')

        if not result2['inventory_data']:
            print('  -> 没有任何带"美国"定制订单的库存！')

        # 直接查 country_agg 的 SQL 模拟
        print('\n=== 场景3: 直接查 country_agg CTE 数据（country=美国）===')
        r = await db.execute(text('''
            SELECT o.product_id, o.customer, COALESCE(o.country, '常规') AS country, SUM(o.quantity) AS qty
            FROM "order" o
            WHERE o.order_type = 'custom'
            GROUP BY o.product_id, o.customer, COALESCE(o.country, '常规')
            HAVING COALESCE(o.country, '常规') = '美国'
        '''))
        rows = r.all()
        print(f'  命中行数: {len(rows)}')
        for row in rows:
            print(f'  product_id={row.product_id}, customer={row.customer}, country={row.country}, qty={row.qty}')


asyncio.run(main())
