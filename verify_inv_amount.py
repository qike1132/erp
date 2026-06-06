from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models.product import Product
from sqlalchemy import func, select
import asyncio

async def verify():
    async with _AsyncSessionLocal() as db:
        # 总库存金额 = 各产品 current_stock × price
        result = await db.execute(
            select(func.coalesce(func.sum(Product.current_stock * Product.price), 0))
        )
        total = round(float(result.scalar() or 0), 2)
        
        # 各产品明细
        prod = await db.execute(Product.__table__.select())
        print("产品详情:")
        for p in prod.all():
            val = round((p.current_stock or 0) * (p.price or 0), 2)
            print(f"  {p.name}: {p.current_stock} × ¥{p.price} = ¥{val}")
        print(f"\n总库存金额: ¥{total}")

if __name__ == "__main__":
    asyncio.run(verify())