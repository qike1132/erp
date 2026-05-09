"""
性能测试数据生成器 - 生成超过 20,000 条真实结构测试数据

用法:
  python scripts/perf_seed_data.py --count 20000 --model order
  python scripts/perf_seed_data.py --count 50000 --model product
  python scripts/perf_seed_data.py --count 20000 --model stockin
  python scripts/perf_seed_data.py --count 20000 --model purchase_order
  python scripts/perf_seed_data.py --all  # 生成所有模型各20000条
"""
import argparse
import asyncio
import random
import string
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import _AsyncSessionLocal, _init_async_engine


BATCH_SIZE = 500
CUSTOMERS = [f"客户_{i:04d}" for i in range(200)]
SUPPLIERS = [f"供应商_{i:04d}" for i in range(50)]
PRODUCT_NAMES = [f"产品_{i:04d}" for i in range(500)]
BARCODES = [f"BC{random.randint(100000, 999999)}" for _ in range(500)]
STATUSES = ["pending", "confirmed", "completed", "cancelled", "processing"]


async def seed_products(session: AsyncSession, count: int) -> int:
    from fastapi_app.shared_models import Product

    existing = (await session.execute(select(func.count(Product.id)))).scalar() or 0
    if existing >= count:
        print(f"  产品已有 {existing} 条，跳过")
        return existing

    need = count - existing
    print(f"  需生成 {need} 条产品...")

    for offset in range(0, need, BATCH_SIZE):
        batch = min(BATCH_SIZE, need - offset)
        products = []
        for j in range(batch):
            idx = offset + j
            products.append(Product(
                name=f"产品_{(existing + idx):05d}",
                barcode=f"BC{random.randint(100000, 999999)}",
                price=round(random.uniform(10, 9999), 2),
                initial_stock=random.randint(0, 10000),
                current_stock=random.randint(0, 10000),
            ))
        session.add_all(products)
        await session.flush()
        print(f"    已插入 {offset + batch}/{need}")

    await session.commit()
    return count


async def seed_orders(session: AsyncSession, count: int) -> int:
    from fastapi_app.shared_models import Order, Product

    product_ids = (await session.execute(select(Product.id))).scalars().all()
    if not product_ids:
        print("  无产品数据，先创建产品...")
        product_ids_count = await seed_products(session, 500)
        product_ids = (await session.execute(select(Product.id))).scalars().all()

    existing = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    if existing >= count:
        print(f"  订单已有 {existing} 条，跳过")
        return existing

    need = count - existing
    print(f"  需生成 {need} 条订单...")

    base_date = datetime(2024, 1, 1)
    for offset in range(0, need, BATCH_SIZE):
        batch = min(BATCH_SIZE, need - offset)
        orders = []
        for j in range(batch):
            idx = offset + j
            order_date = base_date + timedelta(days=random.randint(0, 730))
            orders.append(Order(
                customer_name=random.choice(CUSTOMERS),
                product_id=random.choice(product_ids),
                quantity=random.randint(1, 500),
                status=random.choice(STATUSES),
                order_date=order_date,
                create_time=order_date,
            ))
        session.add_all(orders)
        await session.flush()
        print(f"    已插入 {offset + batch}/{need}")

    await session.commit()
    return count


async def seed_stockins(session: AsyncSession, count: int) -> int:
    from fastapi_app.shared_models import StockIn, Product

    product_ids = (await session.execute(select(Product.id))).scalars().all()
    if not product_ids:
        product_ids_count = await seed_products(session, 500)
        product_ids = (await session.execute(select(Product.id))).scalars().all()

    existing = (await session.execute(select(func.count(StockIn.id)))).scalar() or 0
    if existing >= count:
        print(f"  入库记录已有 {existing} 条，跳过")
        return existing

    need = count - existing
    print(f"  需生成 {need} 条入库记录...")

    base_date = datetime(2024, 1, 1)
    for offset in range(0, need, BATCH_SIZE):
        batch = min(BATCH_SIZE, need - offset)
        stockins = []
        for j in range(batch):
            idx = offset + j
            si_date = base_date + timedelta(days=random.randint(0, 730))
            stockins.append(StockIn(
                product_id=random.choice(product_ids),
                quantity=random.randint(1, 1000),
                customer_name=random.choice(CUSTOMERS),
                date=si_date.date(),
                create_time=si_date,
            ))
        session.add_all(stockins)
        await session.flush()
        print(f"    已插入 {offset + batch}/{need}")

    await session.commit()
    return count


async def seed_purchase_orders(session: AsyncSession, count: int) -> int:
    from fastapi_app.shared_models import PurchaseOrder, PurchaseOrderItem

    existing = (await session.execute(select(func.count(PurchaseOrder.id)))).scalar() or 0
    if existing >= count:
        print(f"  采购订单已有 {existing} 条，跳过")
        return existing

    need = count - existing
    print(f"  需生成 {need} 条采购订单...")

    base_date = datetime(2024, 1, 1)
    for offset in range(0, need, BATCH_SIZE):
        batch = min(BATCH_SIZE, need - offset)
        orders = []
        for j in range(batch):
            idx = offset + j
            order_date = base_date + timedelta(days=random.randint(0, 730))
            order = PurchaseOrder(
                order_no=f"PO{datetime.now().strftime('%Y%m%d')}{existing + idx:06d}",
                supplier_name=random.choice(SUPPLIERS),
                customer_name=random.choice(CUSTOMERS),
                order_date=order_date.date(),
                status=random.choice(STATUSES),
                product_name=random.choice(PRODUCT_NAMES),
                product_quantity=random.randint(100, 5000),
                total_amount=round(random.uniform(1000, 500000), 2),
                create_time=order_date,
            )
            orders.append(order)
        session.add_all(orders)
        await session.flush()

        for order in orders:
            item_count = random.randint(1, 5)
            for _ in range(item_count):
                item = PurchaseOrderItem(
                    order_id=order.id,
                    product_name=order.product_name,
                    barcode=f"BC{random.randint(100000, 999999)}",
                    material_name=f"物料_{random.randint(1, 200)}",
                    quantity=random.randint(10, 1000),
                    unit_price=round(random.uniform(1, 100), 2),
                    total_price=round(random.uniform(10, 10000), 2),
                )
                session.add(item)
        await session.flush()
        print(f"    已插入 {offset + batch}/{need}")

    await session.commit()
    return count


MODELS = {
    "product": seed_products,
    "order": seed_orders,
    "stockin": seed_stockins,
    "purchase_order": seed_purchase_orders,
}


async def main():
    parser = argparse.ArgumentParser(description="性能测试数据生成器")
    parser.add_argument("--count", type=int, default=20000, help="生成数据条数")
    parser.add_argument("--model", choices=list(MODELS.keys()), help="目标模型")
    parser.add_argument("--all", action="store_true", help="为所有模型生成数据")
    args = parser.parse_args()

    _init_async_engine()
    start = time.perf_counter()

    async with _AsyncSessionLocal() as session:
        if args.all:
            for name, fn in MODELS.items():
                print(f"\n=== 生成 {name} ({args.count} 条) ===")
                await fn(session, args.count)
        elif args.model:
            print(f"\n=== 生成 {args.model} ({args.count} 条) ===")
            await MODELS[args.model](session, args.count)
        else:
            print("请指定 --model 或 --all")
            parser.print_help()
            return

    elapsed = time.perf_counter() - start
    print(f"\n总耗时: {elapsed:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
