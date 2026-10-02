"""
创建多 SKU 测试订单数据脚本

创建一个包含多个 OrderItem（不同 SKU）的客户订单，用于验证多 SKU 聚合功能。
测试订单：
  - 客户: MINISO国际
  - 状态: 待备货（会出现在采购中心未处理列表）
  - 包含 3 个 SKU:
    1. 墩墩鸡系列-8号椰子鸡公仔 (id=20424), qty=500
    2. 墩椰毛绒挂件 (id=20425), qty=300
    3. 10寸企鹅公仔(粉色) (id=20430), qty=200
  - 总数量: 1000
"""
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# 让 `python scripts/create_multi_sku_test.py` 能直接跑（原先缺这段，会 ModuleNotFoundError）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.database import async_engine
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_item import OrderItem
from fastapi_app.shared_models.product import Product

async_session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


TEST_SKUS = [
    {"product_id": 20424, "quantity": 500},
    {"product_id": 20425, "quantity": 300},
    {"product_id": 20430, "quantity": 200},
]
TEST_CUSTOMER = "MINISO国际"
TEST_NOTE = "多SKU聚合测试订单-20260626"


async def create_multi_sku_order():
    async with async_session() as db:
        products_result = await db.execute(
            select(Product.id, Product.name, Product.barcode)
            .where(Product.id.in_([s["product_id"] for s in TEST_SKUS]))
        )
        product_map = {p[0]: {"name": p[1], "barcode": p[2]} for p in products_result}
        print("Products loaded:")
        for pid, info in product_map.items():
            print(f"  id={pid}, name={info['name']}, barcode={info['barcode']}")

        result = await db.execute(text("""
            SELECT COALESCE(
                (SELECT MAX(CAST(SUBSTRING(order_no FROM 'PO-\\d{8}-(\\d{4})') AS INTEGER))
                 FROM "order" WHERE order_no LIKE 'PO-20260626-%'),
            0)
        """))
        seq = result.scalar() + 1
        order_no = f"PO-20260626-{seq:04d}"
        print(f"\nNew order_no: {order_no}")

        now = datetime.now(UTC)
        first_product_id = TEST_SKUS[0]["product_id"]
        total_qty = sum(s["quantity"] for s in TEST_SKUS)

        order = Order(
            order_no=order_no,
            customer=TEST_CUSTOMER,
            order_date=now,
            product_id=first_product_id,
            quantity=total_qty,
            status="待备货",
            note=TEST_NOTE,
            order_type="regular",
            country=None,
            is_locked=False,
            is_deleted=False,
            updated_at=now,
        )

        db.add(order)
        await db.flush()
        print(f"Order created: id={order.id}")

        for sku in TEST_SKUS:
            pid = sku["product_id"]
            pinfo = product_map.get(pid, {})
            item = OrderItem(
                order_id=order.id,
                product_id=pid,
                product_name=pinfo.get("name"),
                product_barcode=pinfo.get("barcode"),
                quantity=sku["quantity"],
                order_type="regular",
                country=None,
                deduct_stock=False,
                deduct_quantity=0,
                note=None,
                created_at=now,
                updated_at=now,
            )
            db.add(item)
            print(f"  OrderItem: product_id={pid}, qty={sku['quantity']}, name={pinfo.get('name')}")

        await db.commit()
        print(f"\n✅ 多SKU订单创建成功! order_no={order_no}, id={order.id}, total_qty={total_qty}")

        await db.refresh(order)
        items_result = await db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
        )
        items = items_result.scalars().all()
        print(f"\n验证: 订单 {order.order_no} 包含 {len(items)} 个SKU:")
        for item in items:
            print(f"  - {item.product_name} (barcode={item.product_barcode}), qty={item.quantity}")


if __name__ == "__main__":
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('向生产库插入多 SKU 测试数据')
    asyncio.run(create_multi_sku_order())
