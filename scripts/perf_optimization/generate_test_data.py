#!/usr/bin/env python3
"""
20K+ 测试数据快速生成器
生成订单/入库/出库/采购明细等各20,000+条数据

运行: python scripts/perf_optimization/generate_test_data.py [--target 25000]
"""
import asyncio
import os
import random
import sys
from datetime import date, datetime, timedelta

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.shared_models import Customer, Order, Product, PurchasePlan, PurchasePlanDetail, StockIn, StockOut

TARGET = int(sys.argv[sys.argv.index("--target")+1]) if "--target" in sys.argv else 25000

def rnd_date(): return date(2025,1,1) + timedelta(days=random.randint(0,500))
_ts = datetime.now().strftime('%y%m%d%H%M%S')
def order_no(s): return f"OR{_ts}{s:07d}"
def si_no(s): return f"SI{_ts}{s:07d}"
def so_no(s): return f"SO{_ts}{s:07d}"
def pp_no(s): return f"PP{_ts}{s:07d}"
STATUSES = [None, "待备货", "已备货", "部分备货", "待出货", "已出货", "已完成", "已取消"]

async def ensure_base(db: AsyncSession):
    result = await db.execute(select(Customer.id, Customer.name))
    customers = result.all()
    if len(customers) < 30:
        for i in range(len(customers), 30):
            c = Customer(name=f"压测客户{i+1}", contact_person=f"联系人{i+1}", phone=f"138{random.randint(10000000,99999999)}", address=f"地址{i+1}", status="active")
            db.add(c)
        await db.commit()
        result = await db.execute(select(Customer.id, Customer.name))
        customers = result.all()

    result = await db.execute(select(Product.id, Product.name))
    products = result.all()
    if len(products) < 50:
        for i in range(len(products), 50):
            p = Product(name=f"压测产品{i+1}", barcode=f"69{random.randint(100000000000,999999999999)}", price=random.randint(10,500), current_stock=random.randint(100,10000))
            db.add(p)
        await db.commit()
        result = await db.execute(select(Product.id, Product.name))
        products = result.all()

    return [r.id for r in customers], [r.id for r in products]

async def gen_orders(db, cust_ids, prod_ids, target):
    print(f"[生成] 订单 {target} 条...")
    seq = 1
    for i in range(target):
        o = Order(order_no=order_no(seq), customer=f"压测客户{random.choice(cust_ids)}", order_date=rnd_date(), product_id=random.choice(prod_ids), quantity=random.randint(50,500), status=random.choice(STATUSES), order_type="regular", is_deleted=False)
        db.add(o); seq += 1
        if i % 500 == 0 and i > 0: await db.commit(); print(f"  {i}...")
    await db.commit(); print(f"[完成] 订单 {target} 条")

async def gen_stockins(db, cust_ids, prod_ids, target):
    print(f"[生成] 入库 {target} 条...")
    seq = 1
    for i in range(target):
        si = StockIn(stockin_no=si_no(seq), stockin_date=rnd_date(), product_id=random.choice(prod_ids), quantity=random.randint(50,500), customer=f"压测客户{random.choice(cust_ids)}", note="压测")
        db.add(si); seq += 1
        if i % 500 == 0 and i > 0: await db.commit(); print(f"  {i}...")
    await db.commit(); print(f"[完成] 入库 {target} 条")

async def gen_stockouts(db, cust_ids, prod_ids, target):
    print(f"[生成] 出库 {target} 条...")
    seq = 1
    for i in range(target):
        so = StockOut(stockout_no=so_no(seq), stockout_date=rnd_date(), product_id=random.choice(prod_ids), quantity=random.randint(10,200), customer=f"压测客户{random.choice(cust_ids)}", note="压测")
        db.add(so); seq += 1
        if i % 500 == 0 and i > 0: await db.commit(); print(f"  {i}...")
    await db.commit(); print(f"[完成] 出库 {target} 条")

async def gen_purchase_details(db, cust_ids, prod_ids, target):
    print(f"[生成] 采购明细 {target} 条...")
    result = await db.execute(select(Customer.id, Customer.name).where(Customer.id.in_(cust_ids[:20])))
    cmap = {r.id: r.name for r in result.all()}
    seq = 1; detail_count = 0
    for ci in cust_ids:
        plan = PurchasePlan(plan_no=pp_no(seq), plan_month="2026-05", customer_id=ci, customer_name=cmap.get(ci,""), status="pending", remark="压测")
        db.add(plan); await db.flush(); seq += 1
        for _ in range(random.randint(10,30)):
            if detail_count >= target: break
            pd = PurchasePlanDetail(plan_id=plan.id, product_id=random.choice(prod_ids), product_name="压测产品", barcode=f"69{random.randint(100000000000,999999999999)}", plan_date=rnd_date(), quantity=random.randint(50,500), shipped_qty=random.randint(0,50))
            db.add(pd); detail_count += 1
            if detail_count % 500 == 0: await db.commit(); print(f"  {detail_count}...")
        if detail_count >= target: break
    await db.commit(); print(f"[完成] 采购明细 {detail_count} 条")

async def main():
    print("="*60)
    print(f"  ERP 测试数据生成器 (目标: {TARGET} 条/表)")
    print("="*60)
    async with _AsyncSessionLocal() as db:
        cust_ids, prod_ids = await ensure_base(db)
        print(f"[基础] 客户{len(cust_ids)}个 产品{len(prod_ids)}个")
        await gen_orders(db, cust_ids, prod_ids, TARGET)
        await gen_stockins(db, cust_ids, prod_ids, TARGET)
        await gen_stockouts(db, cust_ids, prod_ids, TARGET)
        await gen_purchase_details(db, cust_ids, prod_ids, TARGET)
    print("="*60)
    print("  数据生成完成")
    print("="*60)

if __name__ == "__main__": asyncio.run(main())
