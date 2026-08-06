"""用前端实际调用的方式调用 API，模拟前端过滤"""
import asyncio
import sys
sys.path.insert(0, r'd:\erp_system')

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.services.stock_service import get_inventory_paginated


async def main():
    async with _AsyncSessionLocal() as db:
        # 模拟前端：page=1, per_page=15, 无 country 过滤
        result = await get_inventory_paginated(
            db, search_customer='', search_product='', country='', page=1, per_page=15
        )
        print(f'total_items: {result["total_items"]}')
        print(f'total_available_stock: {result["total_available_stock"]}')
        print()
        for item in result['inventory_data']:
            print(f'  客户={item["customer"]}, 产品={item["product_name"]}')
            print(f'    order_quantity={item["order_quantity"]}')
            print(f'    country_orders={item.get("country_orders")}')
            print(f'    stockin_quantity={item["stockin_quantity"]}')
            print(f'    stockout_quantity={item["stockout_quantity"]}')
            print(f'    total_stock={item["total_stock"]}')
            print(f'    production_qty={item.get("production_qty", "<MISSING>")}')
            print(f'    available_stock={item.get("available_stock", "<MISSING>")}')
            print()


asyncio.run(main())
