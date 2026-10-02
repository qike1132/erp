"""
为 beile-order 页面创建 50 条测试数据（支持分页验证）

生成规则：
- 30 条单 SKU 订单
- 15 条双 SKU 订单（验证多 SKU 汇总 + 详情弹窗）
- 5 条三 SKU 订单
- 客户随机分配：MINISO国际 / MINISO国内 / 名创优品海外 / 名创优品
- 日期分散在 2026-08-01 ~ 2026-08-09 之间
- 随机带备注字段
"""
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# 让 `python scripts/create_beile_test_data.py` 能直接跑（原先缺这段，会 ModuleNotFoundError）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.database import async_engine
from fastapi_app.shared_models.order import Order
from fastapi_app.shared_models.order_item import OrderItem
from fastapi_app.shared_models.product import Product

async_session = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

CUSTOMERS = ["MINISO国际", "MINISO国内", "名创优品海外", "名创优品"]
NOTES = [
    "急单，请优先处理",
    "这是急单 你安排一下",
    "正常排期",
    "",
    "注意包装质量",
    "需要贴防伪标签",
    "发往上海仓",
    "发往广州仓",
    "新品首批，请关注",
    "补货订单",
    "",
    "",
]
RECORD_TYPES = ["regular"] * 8 + ["custom"] * 2  # 80% regular, 20% custom
COUNTRIES = [None, None, None, None, "日本", "泰国", "越南", "新加坡"]

# 下单日期范围
BASE_DATE = datetime(2026, 8, 1, tzinfo=UTC)


async def get_hubei_products(db: AsyncSession):
    """获取 factory=湖北 的产品列表"""
    result = await db.execute(
        select(Product.id, Product.name, Product.barcode)
        .where(Product.factory == "湖北")
        .limit(60)
    )
    rows = list(result)
    products = [{"id": r[0], "name": r[1], "barcode": r[2]} for r in rows]
    print(f"获取到 {len(products)} 个湖北工厂产品")
    if not products:
        print("❌ 没有找到 factory=湖北 的产品！请先导入产品数据。")
        raise SystemExit(1)
    return products


def generate_order_no(db_seq: int) -> str:
    """生成订单号 PO-20260809-0001 格式"""
    date_str = datetime.now().strftime("%Y%m%d")
    return f"PO-{date_str}-{db_seq:04d}"


def random_date() -> datetime:
    """随机生成 8/1 ~ 8/9 之间的日期时间"""
    days_offset = random.randint(0, 8)
    hours_offset = random.randint(0, 23)
    minutes_offset = random.randint(0, 59)
    return BASE_DATE + timedelta(days=days_offset, hours=hours_offset, minutes=minutes_offset)


def pick_skus(products, count: int):
    """随机选取 count 个不同的产品作为 SKU"""
    chosen = random.sample(products, min(count, len(products)))
    return [{"product_id": p["id"], "name": p["name"], "barcode": p["barcode"],
             "quantity": random.randint(100, 50000)} for p in chosen]


async def create_orders():
    async with async_session() as db:
        products = await get_hubei_products(db)

        # 用时间戳毫秒生成唯一序号，避免复杂SQL
        now_utc = datetime.now(UTC)
        base_seq = int(now_utc.timestamp() * 1000) % 100000

        # 50 条订单：30 单 SKU + 15 双 SKU + 5 三 SKU
        order_specs = []
        for i in range(30):
            order_specs.append({"sku_count": 1, "desc": f"单SKU #{i+1}"})
        for i in range(15):
            order_specs.append({"sku_count": 2, "desc": f"双SKU #{i+1}"})
        for i in range(5):
            order_specs.append({"sku_count": 3, "desc": f"三SKU #{i+1}"})

        random.shuffle(order_specs)

        created = 0
        seq = base_seq

        for spec in order_specs:
            sku_count = spec["sku_count"]
            skus = pick_skus(products, sku_count)
            total_qty = sum(s["quantity"] for s in skus)
            customer = random.choice(CUSTOMERS)
            order_type = random.choice(RECORD_TYPES)
            country = random.choice(COUNTRIES) if order_type == "custom" else None
            note = random.choice(NOTES)
            order_date = random_date()

            order = Order(
                order_no=generate_order_no(seq),
                customer=customer,
                order_date=order_date,
                product_id=skus[0]["product_id"],
                quantity=total_qty,
                status="待备货",
                note=note,
                order_type=order_type,
                country=country,
                is_locked=False,
                is_deleted=False,
                updated_at=now_utc,
            )
            db.add(order)
            await db.flush()

            for sku in skus:
                item = OrderItem(
                    order_id=order.id,
                    product_id=sku["product_id"],
                    product_name=sku["name"],
                    product_barcode=sku["barcode"],
                    quantity=sku["quantity"],
                    order_type=order_type,
                    country=country,
                    deduct_stock=False,
                    deduct_quantity=0,
                    note=note if sku == skus[0] else "",
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                db.add(item)

            seq += 1
            created += 1
            print(f"  [{created:2d}/50] {order.order_no} | {customer} | "
                  f"{sku_count} SKU | qty={total_qty} | {order_date.strftime('%m-%d %H:%M')} | note={note[:20] if note else '-'}")

        await db.commit()
        print(f"\n✅ 成功创建 {created} 条测试订单，共计 {created} 条")


if __name__ == "__main__":
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent('向生产库插入贝乐测试数据')
    asyncio.run(create_orders())
