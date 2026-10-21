"""
ERP系统全板块测试数据生成器 v3 - 直接写入数据库
================================================
为每个可填写表单的板块各自生成 20,000 条测试数据，
直接通过 SQLAlchemy ORM 插入到 PostgreSQL 数据库。

插入顺序（遵循外键依赖）：
  1. products       产品清单
  2. customers      客户管理
  3. suppliers      供应商管理
  4. users          用户管理
  5. orders         客户订单（依赖 products, users）
  6. stock_in       入库管理（依赖 products）
  7. stock_out      出库管理（依赖 products, orders, stock_in）
  8. approval_request  审批管理（依赖 orders, users）
  9. purchase_orders    采购中心（依赖 suppliers, customers, users）
 10. purchase_order_items  采购明细（依赖 purchase_orders）
 11. material_registrations  来料登记（依赖 purchase_orders, suppliers, users）
 12. material_registration_items  来料明细（依赖 material_registrations, purchase_order_items）
 13. purchase_plans     采购计划（依赖 customers）
 14. purchase_plan_details  采购计划明细（依赖 purchase_plans, products）
 15. daily_production_records  生产报表
 16. production_plans   出货计划/排产计划
 17. cases              皮套管理（依赖 products）
"""
import os
import random
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from faker import Faker

fake = Faker("zh_CN")

PER_MODULE = 20000
BATCH_SIZE = 1000

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from fastapi_app.core.config import settings
from fastapi_app.core.float_utils import round_money
from fastapi_app.core.security import hash_password
from fastapi_app.shared_models import (
    ApprovalRequest,
    Case,
    Customer,
    DailyProductionRecord,
    MaterialRegistration,
    MaterialRegistrationItem,
    Order,
    Product,
    ProductionPlan,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchasePlan,
    PurchasePlanDetail,
    StockIn,
    StockOut,
    Supplier,
    User,
)

engine = create_engine(settings.DATABASE_URL, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

_PRECOMPUTED_PASSWORD_HASH = None


def _get_password_hash():
    global _PRECOMPUTED_PASSWORD_HASH
    if _PRECOMPUTED_PASSWORD_HASH is None:
        _PRECOMPUTED_PASSWORD_HASH = hash_password("Test@123456")
    return _PRECOMPUTED_PASSWORD_HASH


def _rand_datetime(days_back=730):
    dt = datetime.now() - timedelta(days=random.randint(0, days_back),
                                    hours=random.randint(0, 23),
                                    minutes=random.randint(0, 59))
    return dt


def _rand_date(days_back=730):
    d = date.today() - timedelta(days=random.randint(0, days_back))
    return d


def _rand_future_date(days_ahead=90):
    d = date.today() + timedelta(days=random.randint(0, days_ahead))
    return d


def insert_products(session, count):
    print(f"  生成 {count} 条产品...")
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            name = f"测试产品-{fake.word().title()}-{idx:06d}"
            objs.append(Product(
                name=name,
                barcode=f"{fake.ean(length=13)}",
                price=Decimal(str(round(random.uniform(1, 9999), 2))),
                image=f"/static/uploads/product_{idx:06d}.jpg",
                initial_stock=random.randint(0, 100000),
                current_stock=random.randint(0, 80000),
                version=0,
                create_time=_rand_datetime(),
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    产品批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_customers(session, count):
    print(f"  生成 {count} 条客户...")
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            objs.append(Customer(
                customer_code=f"CUS{idx:06d}",
                name=f"测试客户-{fake.company()[:20]}-{idx:06d}",
                contact=fake.name(),
                phone=fake.phone_number(),
                address=fake.address()[:200],
                note=fake.sentence()[:200] if random.random() < 0.4 else None,
                status=True,
                create_time=_rand_datetime(),
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    客户批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_suppliers(session, count):
    print(f"  生成 {count} 条供应商...")
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            objs.append(Supplier(
                name=f"测试供应商-{fake.company()[:20]}-{idx:06d}",
                contact_person=fake.name(),
                phone=fake.phone_number(),
                address=fake.address()[:200],
                bank_name=fake.company()[:50] + "银行" if random.random() < 0.5 else None,
                bank_account=fake.bban()[:50] if random.random() < 0.5 else None,
                remark=fake.sentence()[:200] if random.random() < 0.4 else None,
                status=True,
                created_at=_rand_datetime(),
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    供应商批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_users(session, count):
    print(f"  生成 {count} 条用户（含密码哈希）...")
    pw_hash = _get_password_hash()
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            objs.append(User(
                username=f"testuser_{idx:06d}",
                phone=fake.phone_number(),
                password=pw_hash,
                is_super=False,
                status=True,
                create_time=_rand_datetime(),
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    用户批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_orders(session, count, product_ids, user_ids):
    print(f"  生成 {count} 条订单...")
    # 状态必须落在 order_status_check 的白名单内（见迁移 063）：
    # 待备货/部分备货/已备货/待出货/已出货/已取消/批次已完成。
    # 旧值 '已完成' 不在白名单里 ⇒ 整批 INSERT 撞 CHECK 约束报错。
    statuses = [None, "待备货", "已备货", "部分备货", "待出货", "已出货", "批次已完成"]
    order_types = ["regular", "custom"]
    countries = ["中国", "美国", "日本", "德国", "英国", "巴西", "韩国", "印度", "法国", "澳大利亚"]
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            otype = random.choice(order_types)
            objs.append(Order(
                order_no=f"ORD{datetime.now().strftime('%Y%m%d')}{idx:06d}",
                customer=fake.company()[:100],
                order_date=_rand_datetime(),
                product_id=random.choice(product_ids),
                quantity=random.randint(10, 50000),
                status=random.choice(statuses),
                note=fake.sentence()[:200] if random.random() < 0.5 else None,
                order_type=otype,
                country=random.choice(countries) if otype == "custom" else None,
                is_locked=False,
                is_deleted=False,
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    订单批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_stock_in(session, count, product_ids):
    print(f"  生成 {count} 条入库记录...")
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            objs.append(StockIn(
                stockin_no=f"IN{datetime.now().strftime('%Y%m%d')}{idx:06d}",
                stockin_date=_rand_datetime(),
                customer=fake.company()[:100],
                product_id=random.choice(product_ids),
                quantity=random.randint(1, 20000),
                note=fake.sentence()[:200] if random.random() < 0.3 else None,
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    入库批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_stock_out(session, count, product_ids, order_ids, stockin_ids):
    print(f"  生成 {count} 条出库记录...")
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            has_order = random.random() < 0.7
            has_stockin = random.random() < 0.5
            objs.append(StockOut(
                stockout_no=f"OUT{datetime.now().strftime('%Y%m%d')}{idx:06d}",
                stockout_date=_rand_datetime(),
                product_id=random.choice(product_ids),
                quantity=random.randint(1, 15000),
                customer=fake.company()[:100] if random.random() < 0.8 else None,
                order_id=random.choice(order_ids) if has_order else None,
                stockin_id=random.choice(stockin_ids) if has_stockin else None,
                note=fake.sentence()[:200] if random.random() < 0.3 else None,
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    出库批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_approvals(session, count, order_ids, user_ids):
    print(f"  生成 {count} 条审批请求...")
    statuses = ["pending", "approved", "rejected", "cancelled"]
    operations = ["edit", "delete"]
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            batch_start + i
            status = random.choice(statuses)
            objs.append(ApprovalRequest(
                order_id=random.choice(order_ids),
                requester_id=random.choice(user_ids),
                operation_type=random.choice(operations),
                operation_data=None,
                status=status,
                request_time=_rand_datetime(365),
                approver_id=random.choice(user_ids) if status != "pending" else None,
                approval_time=_rand_datetime(365) if status in ("approved", "rejected") else None,
                rejection_reason=fake.sentence()[:200] if status == "rejected" else None,
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    审批批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_purchase_orders(session, count, supplier_ids, customer_ids, user_ids):
    print(f"  生成 {count} 条采购订单...")
    # purchase_order_status_check 只允许 pending/confirmed/completed
    # （见 fastapi_app/shared_models/purchase_order.py 的 CheckConstraint）。
    statuses = ["pending", "confirmed", "completed"]
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            sid = random.choice(supplier_ids) if random.random() < 0.7 else None
            cid = random.choice(customer_ids) if random.random() < 0.7 else None
            objs.append(PurchaseOrder(
                order_no=f"PO{datetime.now().strftime('%Y%m%d')}{idx:06d}",
                supplier_id=sid,
                supplier_name=fake.company()[:100] if sid else None,
                supplier_contact_person=fake.name()[:50] if sid else None,
                supplier_phone=fake.phone_number()[:20] if sid else None,
                supplier_address=fake.address()[:200] if sid else None,
                customer_id=cid,
                customer_name=fake.company()[:100] if cid else None,
                customer_code=f"CUS{random.randint(0, 9999):06d}" if cid else None,
                order_date=_rand_date(),
                status=random.choice(statuses),
                remark=fake.sentence()[:200] if random.random() < 0.4 else None,
                product_name=f"产品-{fake.word().title()}",
                product_quantity=Decimal(str(random.randint(100, 100000))),
                total_amount=Decimal(str(round(random.uniform(1000, 500000), 2))),
                create_time=_rand_datetime(),
                created_by=random.choice(user_ids) if random.random() < 0.5 else None,
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    采购订单批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_purchase_order_items(session, count, po_ids):
    print(f"  生成 {count} 条采购订单明细...")
    materials = ["PU皮", "真皮料", "硅胶片", "TPU片", "PC板", "凯夫拉布",
                 "钢板", "磁铁", "胶水", "线材", "拉链", "扣具", "海绵", "纸板"]
    categories = ["填充物", "面料", "辅料", "包装", "化工", "五金"]
    units = ["kg", "m", "张", "卷", "片", "个", "箱", "套"]
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            qty = Decimal(str(random.randint(100, 50000)))
            up = Decimal(str(round(random.uniform(0.5, 500), 2)))
            objs.append(PurchaseOrderItem(
                order_id=random.choice(po_ids),
                product_name=f"产品-{fake.word().title()}",
                barcode=f"{fake.ean(length=13)}",
                customer_name=fake.company()[:100],
                material_code=f"MAT{idx:06d}",
                material_name=random.choice(materials),
                specification=f"{random.randint(10, 300)}x{random.randint(10, 300)}x{random.randint(1, 50)}mm",
                unit=random.choice(units),
                quantity=qty,
                unit_usage=Decimal(str(round(random.uniform(0.001, 5), 4))),
                unit_price=up,
                total_price=Decimal(str(round_money(float(qty) * float(up)))),
                material_category=random.choice(categories),
                remark=fake.sentence()[:200] if random.random() < 0.3 else None,
                supplier_name=fake.company()[:100] if random.random() < 0.5 else None,
            ))
        session.add_all(objs)
        session.flush()
        print(f"    采购明细批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")


def insert_material_registrations(session, count, po_ids, supplier_ids, user_ids):
    print(f"  生成 {count} 条来料登记...")
    statuses = ["pending", "partial", "completed"]
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            batch_start + i
            sid = random.choice(supplier_ids) if random.random() < 0.7 else None
            objs.append(MaterialRegistration(
                purchase_order_id=random.choice(po_ids),
                purchase_order_no=f"PO{datetime.now().strftime('%Y%m%d')}{random.randint(0, count - 1):06d}",
                supplier_id=sid,
                supplier_name=fake.company()[:100] if sid else None,
                registration_date=_rand_date(365),
                remark=fake.sentence()[:200] if random.random() < 0.3 else None,
                status=random.choice(statuses),
                create_time=_rand_datetime(),
                created_by=random.choice(user_ids) if random.random() < 0.5 else None,
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    来料登记批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_material_registration_items(session, count, reg_ids, po_item_ids):
    print(f"  生成 {count} 条来料登记明细...")
    materials = ["PU皮", "真皮料", "硅胶片", "TPU片", "PC板", "凯夫拉布",
                 "钢板", "磁铁", "胶水", "线材", "拉链", "扣具", "海绵", "纸板"]
    categories = ["填充物", "面料", "辅料", "包装", "化工", "五金"]
    units = ["kg", "m", "张", "卷", "片", "个", "箱", "套"]
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            ordered = Decimal(str(random.randint(100, 50000)))
            received = Decimal(str(random.randint(0, int(ordered))))
            objs.append(MaterialRegistrationItem(
                registration_id=random.choice(reg_ids),
                order_item_id=random.choice(po_item_ids) if po_item_ids and random.random() < 0.5 else None,
                material_code=f"MAT{idx:06d}",
                material_name=random.choice(materials),
                specification=f"{random.randint(10, 300)}x{random.randint(10, 300)}x{random.randint(1, 50)}mm",
                unit=random.choice(units),
                ordered_quantity=ordered,
                received_quantity=received,
                material_category=random.choice(categories),
                remark=fake.sentence()[:200] if random.random() < 0.3 else None,
            ))
        session.add_all(objs)
        session.flush()
        print(f"    来料明细批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")


def insert_purchase_plans(session, count, customer_ids):
    print(f"  生成 {count} 条采购计划...")
    statuses = ["pending", "confirmed", "completed", "cancelled"]
    ids = []
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            objs.append(PurchasePlan(
                plan_no=f"PP{datetime.now().strftime('%Y%m%d')}{idx:06d}",
                plan_month=fake.date_between(start_date="-6m", end_date="+3m").strftime("%Y-%m"),
                customer_id=random.choice(customer_ids),
                customer_name=fake.company()[:100],
                status=random.choice(statuses),
                remark=fake.sentence()[:200] if random.random() < 0.3 else None,
                created_by=fake.name()[:50] if random.random() < 0.5 else None,
                create_time=_rand_datetime(),
            ))
        session.add_all(objs)
        session.flush()
        ids.extend([o.id for o in objs])
        print(f"    采购计划批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")
    return ids


def insert_purchase_plan_details(session, count, plan_ids, product_ids):
    print(f"  生成 {count} 条采购计划明细...")
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            batch_start + i
            objs.append(PurchasePlanDetail(
                plan_id=random.choice(plan_ids),
                product_id=random.choice(product_ids),
                product_name=f"产品-{fake.word().title()}",
                barcode=f"{fake.ean(length=13)}",
                plan_date=_rand_future_date(90),
                quantity=random.randint(10, 50000),
                shipped_qty=random.randint(0, 5000),
                remark=fake.sentence()[:200] if random.random() < 0.2 else None,
            ))
        session.add_all(objs)
        session.flush()
        print(f"    计划明细批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")


def insert_daily_production_records(session, count, product_ids):
    print(f"  生成 {count} 条生产报表...")
    departments = ["filling", "handcraft", "packaging"]
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            batch_start + i
            objs.append(DailyProductionRecord(
                department=random.choice(departments),
                product_id=random.choice(product_ids) if random.random() < 0.8 else None,
                product_name=f"产品-{fake.word().title()}",
                barcode=f"{fake.ean(length=13)}",
                unit_price=Decimal(str(round(random.uniform(0.5, 500), 2))),
                quantity=random.randint(10, 50000),
                production_date=_rand_date(365),
                remark=fake.sentence()[:200] if random.random() < 0.3 else None,
                created_by=fake.name()[:50] if random.random() < 0.5 else None,
            ))
        session.add_all(objs)
        session.flush()
        print(f"    生产报表批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")


def insert_production_plans(session, count):
    print(f"  生成 {count} 条排产计划...")
    statuses = ["pending", "confirmed", "completed"]
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            batch_start + i
            qty = random.randint(100, 50000)
            objs.append(ProductionPlan(
                customer_name=fake.company()[:100],
                product_name=f"产品-{fake.word().title()}",
                barcode=f"{fake.ean(length=13)}",
                quantity=qty,
                plan_date=_rand_future_date(90),
                status=random.choice(statuses),
                shipped_qty=random.randint(0, qty // 2),
                remark=fake.sentence()[:200] if random.random() < 0.3 else None,
                created_by=fake.name()[:50] if random.random() < 0.5 else None,
            ))
        session.add_all(objs)
        session.flush()
        print(f"    排产计划批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")


def insert_cases(session, count, product_ids):
    print(f"  生成 {count} 条皮套记录...")
    materials = ["PU", "真皮", "硅胶", "TPU", "PC", "凯夫拉", "尼龙", "帆布"]
    colors = ["黑色", "白色", "红色", "蓝色", "绿色", "紫色", "粉色", "灰色", "棕色", "透明"]
    for batch_start in range(0, count, BATCH_SIZE):
        batch_count = min(BATCH_SIZE, count - batch_start)
        objs = []
        for i in range(batch_count):
            idx = batch_start + i
            objs.append(Case(
                product_id=random.choice(product_ids) if random.random() < 0.7 else None,
                name=f"{random.choice(materials)}{random.choice(colors)}{random.choice(['皮套', '手机壳', '保护套'])}-{idx:06d}",
                barcode=f"{fake.ean(length=13)}",
                image=f"/static/uploads/case_{idx:06d}.jpg" if random.random() < 0.3 else None,
                initial_stock=random.randint(0, 50000),
                current_stock=random.randint(0, 40000),
                version=0,
                create_time=_rand_datetime(),
            ))
        session.add_all(objs)
        session.flush()
        print(f"    皮套批次 {batch_start // BATCH_SIZE + 1}/{(count - 1) // BATCH_SIZE + 1} 完成")


def main():
    # ---- fail-closed 守卫（2026-10-03 第五轮审计）----
    # 本脚本直连 settings.DATABASE_URL 并向各板块批量插入数万行**测试数据**；
    # 本机 DATABASE_URL 即生产库。默认拒绝，需显式声明（沿用 _prod_write_guard 约定）。
    if os.getenv("ERP_ALLOW_PROD_WRITE") != "1":
        raise SystemExit(
            "拒绝运行：本脚本会向 settings.DATABASE_URL（本机=生产库）批量插入测试数据。"
            " 确认要写入时请显式设置 ERP_ALLOW_PROD_WRITE=1。"
        )
    total_start = time.time()
    session = SessionLocal()

    try:
        print("=" * 70)
        print("  ERP系统全板块测试数据生成器 v3 - 数据库直写模式")
        print(f"  每板块: {PER_MODULE:,} 条 | 共 14 个板块")
        print("=" * 70)

        print("\n[1/17] 插入产品清单...")
        t0 = time.time()
        product_ids = insert_products(session, PER_MODULE)
        session.commit()
        print(f"  完成: {len(product_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[2/17] 插入客户管理...")
        t0 = time.time()
        customer_ids = insert_customers(session, PER_MODULE)
        session.commit()
        print(f"  完成: {len(customer_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[3/17] 插入供应商管理...")
        t0 = time.time()
        supplier_ids = insert_suppliers(session, PER_MODULE)
        session.commit()
        print(f"  完成: {len(supplier_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[4/17] 插入用户管理（含密码哈希）...")
        t0 = time.time()
        user_ids = insert_users(session, PER_MODULE)
        session.commit()
        print(f"  完成: {len(user_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[5/17] 插入客户订单...")
        t0 = time.time()
        order_ids = insert_orders(session, PER_MODULE, product_ids, user_ids)
        session.commit()
        print(f"  完成: {len(order_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[6/17] 插入入库管理...")
        t0 = time.time()
        stockin_ids = insert_stock_in(session, PER_MODULE, product_ids)
        session.commit()
        print(f"  完成: {len(stockin_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[7/17] 插入出库管理...")
        t0 = time.time()
        stockout_ids = insert_stock_out(session, PER_MODULE, product_ids, order_ids, stockin_ids)
        session.commit()
        print(f"  完成: {len(stockout_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[8/17] 插入审批管理...")
        t0 = time.time()
        approval_ids = insert_approvals(session, PER_MODULE, order_ids, user_ids)
        session.commit()
        print(f"  完成: {len(approval_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[9/17] 插入采购订单...")
        t0 = time.time()
        po_ids = insert_purchase_orders(session, PER_MODULE, supplier_ids, customer_ids, user_ids)
        session.commit()
        print(f"  完成: {len(po_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[10/17] 插入采购订单明细...")
        t0 = time.time()
        insert_purchase_order_items(session, PER_MODULE, po_ids)
        session.commit()
        print(f"  完成: {PER_MODULE:,} 条, 耗时 {time.time() - t0:.1f}s")

        po_item_ids = [row[0] for row in session.execute(text("SELECT id FROM purchase_order_item LIMIT 20000")).fetchall()]

        print("\n[11/17] 插入来料登记...")
        t0 = time.time()
        reg_ids = insert_material_registrations(session, PER_MODULE, po_ids, supplier_ids, user_ids)
        session.commit()
        print(f"  完成: {len(reg_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[12/17] 插入来料登记明细...")
        t0 = time.time()
        insert_material_registration_items(session, PER_MODULE, reg_ids, po_item_ids)
        session.commit()
        print(f"  完成: {PER_MODULE:,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[13/17] 插入采购计划...")
        t0 = time.time()
        plan_ids = insert_purchase_plans(session, PER_MODULE, customer_ids)
        session.commit()
        print(f"  完成: {len(plan_ids):,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[14/17] 插入采购计划明细...")
        t0 = time.time()
        insert_purchase_plan_details(session, PER_MODULE, plan_ids, product_ids)
        session.commit()
        print(f"  完成: {PER_MODULE:,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[15/17] 插入生产报表...")
        t0 = time.time()
        insert_daily_production_records(session, PER_MODULE, product_ids)
        session.commit()
        print(f"  完成: {PER_MODULE:,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[16/17] 插入排产计划（出货计划）...")
        t0 = time.time()
        insert_production_plans(session, PER_MODULE)
        session.commit()
        print(f"  完成: {PER_MODULE:,} 条, 耗时 {time.time() - t0:.1f}s")

        print("\n[17/17] 插入皮套管理...")
        t0 = time.time()
        insert_cases(session, PER_MODULE, product_ids)
        session.commit()
        print(f"  完成: {PER_MODULE:,} 条, 耗时 {time.time() - t0:.1f}s")

        total_elapsed = time.time() - total_start
        print("\n" + "=" * 70)
        print(f"  全部完成！总耗时: {total_elapsed:.1f}s")
        print(f"  总计: 17 张表 × {PER_MODULE:,} 条 = {17 * PER_MODULE:,} 条记录")
        print("=" * 70)

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    main()
