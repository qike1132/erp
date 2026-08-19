"""模拟前端 inventory computed 转换"""
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
        # 模拟前端 inventory computed
        raw = result['inventory_data']
        inventory = []
        for item in raw:
            if item.get('_custom_details'):
                inventory.append(item)
                continue
            co = item.get('country_orders') or {}
            details = []
            for k, v in co.items():
                if k != '常规' and v:
                    details.append({'country': k, 'qty': int(v)})
            new_item = {**item, '_custom_details': details}
            inventory.append(new_item)

        # 模拟 totalCustomQty
        total_custom = 0
        for i in inventory:
            for d in i['_custom_details']:
                total_custom += d['qty']

        # 模拟 totalRegularQty
        total_order_qty = result['total_order_qty']
        total_regular = max(0, total_order_qty - total_custom)

        print(f'total_order_quantity (从后端): {total_order_qty}')
        print(f'total_custom (从 inventory 累加): {total_custom}')
        print(f'total_regular (max 0, total_order - total_custom): {total_regular}')
        print(f'total_stockin_quantity: {result["total_stockin_qty"]}')
        print(f'total_stock: {result["total_stock"]}')
        print(f'total_available_stock: {result["total_available_stock"]}')
        print()
        print('=== 每行 _custom_details ===')
        for i in inventory:
            if i['_custom_details']:
                print(f'  {i["customer"]} / {i["product_name"]}: {i["_custom_details"]}')


asyncio.run(main())
