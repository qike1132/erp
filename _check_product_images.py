"""检查 product 表中 image 字段的当前值"""
import asyncio
from fastapi_app.core.database import _AsyncSessionLocal
from sqlalchemy import select
from fastapi_app.shared_models import Product

async def check():
    if _AsyncSessionLocal is None:
        print("数据库未初始化")
        return
    async with _AsyncSessionLocal() as db:
        result = await db.execute(
            select(Product.id, Product.name, Product.image).order_by(Product.id.desc()).limit(10)
        )
        rows = result.all()
        for row in rows:
            print(f'ID={row[0]}, name={row[1]}, image={repr(row[2])}')

if __name__ == '__main__':
    asyncio.run(check())
