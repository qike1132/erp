#!/usr/bin/env python3
"""
ERP 系统性能测试数据生成器
为性能基准测试生成 30K+ 条测试数据
"""

import asyncio
import os
import random
import sys
from datetime import date, datetime, timedelta

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models import (
    Customer,
    Order,
    Product,
    PurchasePlan,
    PurchasePlanDetail,
    StockIn,
    StockOut,
)

# ============= 配置 =============
TARGET_CUSTOMERS = 30
TARGET_PRODUCTS = 50
TARGET_PLAN_DETAILS = 30000
TARGET_ORDERS = 30000
TARGET_STOCKINS = 15000
TARGET_STOCKOUTS = 15000


# ============= 辅助函数 =============
def random_date(start: date, end: date) -> date:
    delta = end - start
    return start + timedelta(days=random.randint(0, delta.days))


def generate_order_no(seq: int) -> str:
    return f"OR{datetime.now().strftime('%y%m%d')}{seq:07d}"


def generate_stockin_no(seq: int) -> str:
    return f"SI{datetime.now().strftime('%y%m%d')}{seq:07d}"


def generate_stockout_no(seq: int) -> str:
    return f"SO{datetime.now().strftime('%y%m%d')}{seq:07d}"


def generate_plan_no(seq: int) -> str:
    return f"PP{datetime.now().strftime('%y%m%d')}{seq:07d}"


async def ensure_customers(db: AsyncSession, count: int) -> list[int]:
    """确保有足够客户数据"""
    result = await db.execute(select(Customer.id, Customer.name))
    existing = result.all()
    if len(existing) >= count:
        return [r.id for r in existing[:count]]

    need = count - len(existing)
    start = len(existing)
    ids = [r.id for r in existing]
    for i in range(need):
        idx = start + i + 1
        c = Customer(
            name=f"性能测试客户{idx}",
            contact_person=f"联系人{idx}",
            phone=f"138{random.randint(10000000, 99999999)}",
            address=f"测试地址{idx}",
            status="active",
        )
        db.add(c)
        await db.flush()
        ids.append(c.id)
    await db.commit()
    return ids


async def ensure_products(db: AsyncSession, count: int) -> list[int]:
    """确保有足够产品数据"""
    result = await db.execute(select(Product.id, Product.name))
    existing = result.all()
    if len(existing) >= count:
        return [r.id for r in existing[:count]]

    need = count - len(existing)
    start = len(existing)
    ids = [r.id for r in existing]
    for i in range(need):
        idx = start + i + 1
        p = Product(
            name=f"性能测试产品{idx}",
            barcode=f"69{random.randint(100000000000, 999999999999)}",
            price=random.randint(10, 500),
            current_stock=random.randint(100, 10000),
        )
        db.add(p)
        await db.flush()
        ids.append(p.id)
    await db.commit()
    return ids


async def generate_purchase_plans(db: AsyncSession, customer_ids: list[int], product_ids: list[int], target_details: int):
    """生成采购计划主单+明细"""
    print(f"[生成] 采购计划明细: 目标 {target_details} 条...")

    # 获取客户名称映射
    result = await db.execute(select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids[:20])))
    customer_map = {r.id: r.name for r in result.all()}

    # 获取产品名称映射
    result = await db.execute(select(Product.id, Product.name, Product.barcode).where(Product.id.in_(product_ids[:40])))
    product_map = {r.id: (r.name, r.barcode) for r in result.all()}

    # 生成 6 个月的计划数据
    today = date.today()
    months = [(today.year, today.month)]
    for _ in range(5):
        prev = months[-1]
        if prev[1] == 1:
            months.append((prev[0] - 1, 12))
        else:
            months.append((prev[0], prev[1] - 1))

    detail_count = 0
    seq = 1
    batch_size = 500

    for year, month in months:
        plan_month = f"{year}-{month:02d}"
        days_in_month = 31 if month in [1, 3, 5, 7, 8, 10, 12] else 30 if month != 2 else 28

        for cust_id in customer_ids:
            cust_name = customer_map.get(cust_id, f"客户{cust_id}")
            plan = PurchasePlan(
                plan_no=generate_plan_no(seq),
                plan_month=plan_month,
                customer_id=cust_id,
                customer_name=cust_name,
                status="pending",
                remark="性能测试数据",
            )
            db.add(plan)
            await db.flush()
            seq += 1

            # 每个 plan 生成多个明细
            details_per_plan = random.randint(10, 30)
            for _ in range(details_per_plan):
                if detail_count >= target_details:
                    break
                pid = random.choice(product_ids)
                pname, pbarcode = product_map.get(pid, (f"产品{pid}", ""))
                plan_day = random.randint(1, days_in_month)
                pd = PurchasePlanDetail(
                    plan_id=plan.id,
                    product_id=pid,
                    product_name=pname,
                    barcode=pbarcode or f"69{random.randint(100000000000, 999999999999)}",
                    plan_date=date(year, month, plan_day),
                    quantity=random.randint(50, 500),
                    shipped_qty=random.randint(0, 50),
                )
                db.add(pd)
                detail_count += 1

                if detail_count % batch_size == 0:
                    await db.commit()
                    print(f"  已生成 {detail_count} 条明细...")

        if detail_count >= target_details:
            break

    await db.commit()
    print(f"[完成] 采购计划明细: {detail_count} 条")
    return detail_count


async def generate_orders(db: AsyncSession, customer_ids: list[int], product_ids: list[int], target: int):
    """生成订单数据"""
    print(f"[生成] 订单: 目标 {target} 条...")

    result = await db.execute(select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids[:20])))
    customer_map = {r.id: r.name for r in result.all()}

    seq = 1
    batch_size = 500

    for i in range(target):
        cust_id = random.choice(customer_ids)
        pid = random.choice(product_ids)
        o = Order(
            order_no=generate_order_no(seq),
            customer=customer_map.get(cust_id, f"客户{cust_id}"),
            order_date=random_date(date(2025, 1, 1), date.today()),
            product_id=pid,
            quantity=random.randint(50, 500),
            status=random.choice([None, "待备货", "已备货", "待出货", "已出货", "已完成"]),
            order_type="regular",
            is_deleted=False,
        )
        db.add(o)
        seq += 1

        if i % batch_size == 0 and i > 0:
            await db.commit()
            print(f"  已生成 {i} 条订单...")

    await db.commit()
    print(f"[完成] 订单: {target} 条")


async def generate_stock_records(db: AsyncSession, customer_ids: list[int], product_ids: list[int], target_in: int, target_out: int):
    """生成入库/出库记录"""
    print(f"[生成] 入库 {target_in} 条 / 出库 {target_out} 条...")

    result = await db.execute(select(Customer.id, Customer.name).where(Customer.id.in_(customer_ids[:20])))
    customer_map = {r.id: r.name for r in result.all()}

    seq = 1
    # 生成入库
    for i in range(target_in):
        pid = random.choice(product_ids)
        cust_id = random.choice(customer_ids)
        si = StockIn(
            stockin_no=generate_stockin_no(seq),
            stockin_date=random_date(date(2025, 1, 1), date.today()),
            product_id=pid,
            quantity=random.randint(50, 500),
            customer=customer_map.get(cust_id, f"客户{cust_id}"),
            note="性能测试",
        )
        db.add(si)
        seq += 1
        if i % 500 == 0 and i > 0:
            await db.commit()
            print(f"  已生成 {i} 条入库...")

    await db.commit()

    # 生成出库
    for i in range(target_out):
        pid = random.choice(product_ids)
        cust_id = random.choice(customer_ids)
        so = StockOut(
            stockout_no=generate_stockout_no(seq),
            stockout_date=random_date(date(2025, 1, 1), date.today()),
            product_id=pid,
            quantity=random.randint(10, 200),
            customer=customer_map.get(cust_id, f"客户{cust_id}"),
            note="性能测试",
        )
        db.add(so)
        seq += 1
        if i % 500 == 0 and i > 0:
            await db.commit()
            print(f"  已生成 {i} 条出库...")

    await db.commit()
    print(f"[完成] 入库 {target_in} 条 / 出库 {target_out} 条")


async def main():
    print("=" * 60)
    print("ERP 性能测试数据生成器")
    print("=" * 60)

    async with _AsyncSessionLocal() as db:
        # 确保基础数据
        customer_ids = await ensure_customers(db, TARGET_CUSTOMERS)
        product_ids = await ensure_products(db, TARGET_PRODUCTS)
        print(f"[基础] 客户 {len(customer_ids)} 个, 产品 {len(product_ids)} 个")

        # 生成测试数据
        await generate_purchase_plans(db, customer_ids, product_ids, TARGET_PLAN_DETAILS)
        await generate_orders(db, customer_ids, product_ids, TARGET_ORDERS)
        await generate_stock_records(db, customer_ids, product_ids, TARGET_STOCKINS, TARGET_STOCKOUTS)

    print("=" * 60)
    print("测试数据生成完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
