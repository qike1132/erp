"""检查新字段 available_stock_by_country"""
import asyncio
import sys
sys.path.insert(0, r'd:\erp_system')

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.services.stock_service import get_inventory_paginated


async def main():
    async with _AsyncSessionLocal() as db:
        result = await get_inventory_paginated(
            db, search_customer='', search_product='', country='', page=1, per_page=15
        )
        for item in result['inventory_data']:
            co = item.get('country_orders') or {}
            abc = item.get('available_stock_by_country', '<MISSING>')
            if co and '美国' in co:
                print(f'  {item["customer"]} / {item["product_name"]}:')
                print(f'    country_orders = {co}')
                print(f'    available_stock = {item.get("available_stock")}')
                print(f'    available_stock_by_country = {abc}')
                print()


asyncio.run(main())
