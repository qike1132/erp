"""
20000条测试数据生成器
生成覆盖所有核心数据库表的批量测试数据，用于数据库完整性测试。
"""
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "fastapi_app"))

from faker import Faker

fake = Faker("zh_CN")

TOTAL_RECORDS = 20000

# 数据分配: 各表按比例分配
DISTRIBUTION = {
    "products": 3000,
    "customers": 2000,
    "suppliers": 1000,
    "orders": 4000,
    "stock_in": 3000,
    "stock_out": 2500,
    "approvals": 1000,
    "users": 500,
    "cases": 2000,
    "material_registration": 1000,
}


def generate_products(count):
    rows = []
    for i in range(count):
        rows.append({
            "product_code": f"P{100000 + i:06d}",
            "product_name": fake.word().title() + " " + fake.random_element(["L型", "U型", "直板", "折叠", "Pro", "Mini"]),
            "unit": random.choice(["个", "箱", "套", "件"]),
            "price": round(random.uniform(10, 5000), 2),
            "spec": f"{random.randint(10, 200)}x{random.randint(10, 200)}x{random.randint(1, 50)}mm",
        })
    return rows


def generate_customers(count):
    rows = []
    for _i in range(count):
        rows.append({
            "customer_name": fake.company(),
            "contact_person": fake.name(),
            "phone": fake.phone_number(),
            "email": fake.email(),
            "address": fake.address(),
        })
    return rows


def generate_suppliers(count):
    rows = []
    for _i in range(count):
        rows.append({
            "supplier_name": fake.company(),
            "contact_person": fake.name(),
            "phone": fake.phone_number(),
            "email": fake.email(),
            "address": fake.address(),
            "supplier_type": random.choice(["原材料", "辅料", "包装", "物流", "其他"]),
        })
    return rows


def generate_orders(count):
    rows = []
    statuses = ["待备货", "备货中", "待出货", "已完成", "已取消"]
    for i in range(count):
        rows.append({
            "order_no": f"ORD{datetime.now().strftime('%Y%m%d')}{1000 + i:06d}",
            "customer_name": fake.company(),
            "status": random.choice(statuses),
            "quantity": random.randint(10, 10000),
            "total_amount": round(random.uniform(100, 100000), 2),
            "order_date": fake.date_between(start_date="-2y", end_date="today"),
        })
    return rows


def generate_stock_in(count):
    rows = []
    types = ["采购入库", "退货入库", "调拨入库", "生产入库"]
    for i in range(count):
        rows.append({
            "bill_no": f"IN{datetime.now().strftime('%Y%m%d')}{1000 + i:06d}",
            "stock_in_type": random.choice(types),
            "quantity": random.randint(1, 5000),
            "price": round(random.uniform(1, 5000), 2),
            "date": fake.date_between(start_date="-2y", end_date="today"),
        })
    return rows


def generate_stock_out(count):
    rows = []
    types = ["销售出库", "退货出库", "调拨出库", "损耗出库"]
    for i in range(count):
        rows.append({
            "bill_no": f"OUT{datetime.now().strftime('%Y%m%d')}{1000 + i:06d}",
            "stock_out_type": random.choice(types),
            "quantity": random.randint(1, 5000),
            "price": round(random.uniform(1, 5000), 2),
            "date": fake.date_between(start_date="-2y", end_date="today"),
        })
    return rows


def generate_approvals(count):
    rows = []
    types = ["订单审批", "入库审批", "出库审批", "采购审批", "退款审批"]
    statuses = ["待审批", "已通过", "已驳回"]
    for _i in range(count):
        rows.append({
            "approval_type": random.choice(types),
            "status": random.choice(statuses),
            "applicant": fake.name(),
            "apply_date": fake.date_between(start_date="-1y", end_date="today"),
        })
    return rows


def generate_users(count):
    rows = []
    roles = ["admin", "manager", "operator", "viewer"]
    for i in range(count):
        rows.append({
            "username": f"user_{1000 + i:05d}",
            "display_name": fake.name(),
            "role": random.choice(roles),
            "status": random.choice(["active", "active", "active", "inactive"]),
            "email": fake.email(),
            "phone": fake.phone_number(),
        })
    return rows


def generate_cases(count):
    rows = []
    materials = ["PU", "真皮", "硅胶", "TPU", "PC", "凯夫拉"]
    colors = ["黑色", "白色", "红色", "蓝色", "绿色", "紫色", "粉色", "灰色", "棕色", "透明"]
    for i in range(count):
        rows.append({
            "case_code": f"C{200000 + i:06d}",
            "case_name": f"{random.choice(materials)}{random.choice(colors)}皮套",
            "material": random.choice(materials),
            "color": random.choice(colors),
            "model": random.choice(["iPhone 15", "iPhone 15 Pro", "iPhone 15 Pro Max", "iPhone 16", "Samsung S24", "华为 Mate 60"]),
            "unit_price": round(random.uniform(5, 200), 2),
        })
    return rows


def generate_material_registration(count):
    rows = []
    materials = ["PU皮", "真皮料", "硅胶片", "TPU片", "PC板", "凯夫拉布", "钢板", "磁铁", "胶水", "线材"]
    for i in range(count):
        rows.append({
            "batch_no": f"MAT{datetime.now().strftime('%Y%m')}{1000 + i:05d}",
            "material_name": random.choice(materials),
            "supplier_name": fake.company(),
            "quantity": random.randint(100, 50000),
            "unit": random.choice(["kg", "m", "张", "卷", "片"]),
            "register_date": fake.date_between(start_date="-1y", end_date="today"),
            "inspector": fake.name(),
            "quality_result": random.choice(["合格", "合格", "合格", "让步接收", "不合格退货"]),
        })
    return rows


def print_summary(all_data):
    print("\n" + "=" * 60)
    print(f"{'测试数据生成完毕':^50}")
    print("=" * 60)
    total = 0
    for table, data in all_data.items():
        count = len(data)
        total += count
        print(f"  {table:<30s}: {count:>6d} 条")
    print(f"  {'─' * 60}")
    print(f"  {'总计':<30s}: {total:>6d} 条")
    print("=" * 60)


if __name__ == "__main__":
    all_data = {
        "products": generate_products(DISTRIBUTION["products"]),
        "customers": generate_customers(DISTRIBUTION["customers"]),
        "suppliers": generate_suppliers(DISTRIBUTION["suppliers"]),
        "orders": generate_orders(DISTRIBUTION["orders"]),
        "stock_in": generate_stock_in(DISTRIBUTION["stock_in"]),
        "stock_out": generate_stock_out(DISTRIBUTION["stock_out"]),
        "approvals": generate_approvals(DISTRIBUTION["approvals"]),
        "users": generate_users(DISTRIBUTION["users"]),
        "cases": generate_cases(DISTRIBUTION["cases"]),
        "material_registration": generate_material_registration(DISTRIBUTION["material_registration"]),
    }
    print_summary(all_data)
