"""精确检查哪些带美国定制订单的产品被过滤了"""
import asyncio
import sys
sys.path.insert(0, r'd:\erp_system')

from sqlalchemy import select, text
from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models import Product, StockIn, Order, StockOut
from sqlalchemy import func


async def main():
    async with _AsyncSessionLocal() as db:
        # 找所有有美国定制订单的产品+客户组合
        r = await db.execute(text('''
            SELECT DISTINCT product_id, customer
            FROM "order"
            WHERE order_type = 'custom' AND country = '美国' AND is_deleted = false
            ORDER BY product_id
        '''))
        usa_combos = r.all()
        print(f'有美国定制订单的产品+客户组合: {len(usa_combos)}')
        for pid, cust in usa_combos:
            # 查产品名
            p = (await db.execute(select(Product).where(Product.id == pid))).scalar_one_or_none()
            # 查入库
            si_count = (await db.execute(
                select(func.count()).select_from(StockIn)
                .where(StockIn.product_id == pid, StockIn.customer == cust)
            )).scalar()
            # 查订单
            od_count = (await db.execute(
                select(func.count()).select_from(Order)
                .where(Order.product_id == pid, Order.customer == cust, Order.is_deleted == False)
            )).scalar()
            # 出库
            so_count = (await db.execute(
                select(func.count()).select_from(StockOut)
                .where(StockOut.product_id == pid, StockOut.customer == cust)
            )).scalar()
            has_stockin = si_count > 0
            has_order = od_count > 0
            kept = has_stockin or has_order
            print(f'  product_id={pid} ({p.name if p else "?"}) 客户={cust}: '
                  f'stockin={si_count}, order={od_count}, stockout={so_count} '
                  f'-> kept={kept}')


asyncio.run(main())
