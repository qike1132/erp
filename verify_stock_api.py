"""
验证库存 API 计算方式与 Product.current_stock 的区别
"""
import asyncio
from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models.product import Product
from fastapi_app.services.stock_service import get_inventory_paginated
from sqlalchemy import func, select

async def verify():
    async with _AsyncSessionLocal() as db:
        # 1. Product.current_stock 直接求和
        result = await db.execute(
            select(func.coalesce(func.sum(Product.current_stock), 0))
        )
        current_stock_sum = int(result.scalar() or 0)
        
        # 2. 各产品 current_stock 明细
        prods = await db.execute(
            select(Product.id, Product.name, Product.current_stock, Product.price)
        )
        print("=== Product.current_stock 明细 ===")
        for p in prods.all():
            val = (p.current_stock or 0) * (p.price or 0)
            print(f"  ID={p.id} {p.name}: current_stock={p.current_stock}, price=¥{p.price}, amount=¥{val}")
        print(f"  SUM(current_stock) = {current_stock_sum}")
        
        # 3. 库存 API 的计算方式（无分页，获取全部数据）
        inv_result = await get_inventory_paginated(db, page=1, per_page=10000)
        api_total_stock = inv_result.get('total_stock', 0)
        print(f"\n=== 库存 API total_stock (计算值) ===")
        print(f"  total_stock = {api_total_stock}")