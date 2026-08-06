"""检查11寸企鹅是否有入库/订单"""
import asyncio
import sys
sys.path.insert(0, r'd:\erp_system')

from sqlalchemy import select, func, text
from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models import Product, StockIn, StockOut, Order


async def main():
    async with _AsyncSessionLocal() as db:
        r = await db.execute(select(Product).where(Product.name == '11寸企鹅'))
        product = r.scalar_one_or_none()
        if not product:
            print('产品不存在')
            return

        pid = product.id
        print(f'产品: id={pid}, name="{product.name}"')

        # 入库数
        si_count = (await db.execute(
            select(func.count()).select_from(StockIn).where(StockIn.product_id == pid)
        )).scalar()
        si_sum = (await db.execute(
            select(func.coalesce(func.sum(StockIn.quantity), 0)).where(StockIn.product_id == pid)
        )).scalar()
        print(f'入库: count={si_count}, total_qty={si_sum}')

        # 出库数
        so_count = (await db.execute(
            select(func.count()).select_from(StockOut).where(StockOut.product_id == pid)
        )).scalar()
        print(f'出库: count={so_count}')

        # 订单数
        od_count = (await db.execute(
            select(func.count()).select_from(Order).where(Order.product_id == pid, Order.is_deleted == False)
        )).scalar()
        print(f'订单: count={od_count}')

        # 模拟 CTE 中 filtered 阶段的判断
        has_stockin = si_count > 0
        has_order = od_count > 0
        print(f'\nfiltered 条件: has_stockin={has_stockin} OR has_order={has_order} -> {"保留" if (has_stockin or has_order) else "被过滤"}')


asyncio.run(main())
