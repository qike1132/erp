"""验证多 SKU 订单在采购中心未处理列表和详情中正确返回"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload

from fastapi_app.core.database import async_engine
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_item import OrderItem
from fastapi_app.services.purchase_order_query import get_unprocessed_orders

async_session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


async def verify():
    async with async_session() as db:
        result = await get_unprocessed_orders(db, page=1, per_page=15)
        print(f"未处理订单总数: {result['total']}")
        print(f"当前页订单数: {len(result['orders'])}")

        target_order = None
        for o in result['orders']:
            if o['order_no'] == 'PO-20260626-0004':
                target_order = o
                break

        if target_order:
            print(f"\n✅ 在未处理列表中找到测试订单:")
            print(f"  order_no: {target_order['order_no']}")
            print(f"  customer: {target_order['customer']}")
            print(f"  product_id (首SKU): {target_order['product_id']}")
            print(f"  quantity (首SKU): {target_order['quantity']}")
        else:
            print("\n❌ 未在未处理列表中找到测试订单!")
            print("前5条订单号:", [o['order_no'] for o in result['orders'][:5]])

        order_result = await db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.order_no == 'PO-20260626-0004')
        )
        order = order_result.scalar_one_or_none()
        if order:
            print(f"\n📋 订单详情验证 (id={order.id}):")
            print(f"  order_no: {order.order_no}")
            print(f"  customer: {order.customer}")
            print(f"  主表product_id: {order.product_id}")
            print(f"  主表quantity(聚合): {order.quantity}")
            print(f"  status: {order.status}")
            print(f"  items数量: {len(order.items)}")
            total_items_qty = 0
            for i, item in enumerate(order.items, 1):
                print(f"  SKU{i}: product_id={item.product_id}, name={item.product_name}, qty={item.quantity}")
                total_items_qty += item.quantity
            print(f"  items总数量: {total_items_qty} (主表quantity={order.quantity}, {'✅ 一致' if total_items_qty == order.quantity else '❌ 不一致'})")
        else:
            print("\n❌ 数据库中未找到测试订单!")


if __name__ == "__main__":
    asyncio.run(verify())
