"""
ERP系统全板块测试数据生成器 v2
================================
为每个可填写表单的板块各自生成 20,000 条独立测试数据。
数据设计严格匹配各模块 Pydantic Schema 定义。

板块覆盖（14个板块 × 20,000条 = 280,000条）：
  1. 客户订单       orders              20,000
  2. 产品清单       products            20,000
  3. 客户管理       customers           20,000
  4. 供应商管理     suppliers           20,000
  5. 用户管理       users               20,000
  6. 审批管理       approvals           20,000
  7. 入库管理       stock_in            20,000
  8. 出库管理       stock_out           20,000
  9. 采购中心       purchase_orders     20,000
 10. 来料登记       material_registration 20,000
 11. 采购计划       purchase_plans      20,000
 12. 生产报表       daily_productions   20,000
 13. 出货计划       production_summaries 20,000
 14. 皮套管理       cases               20,000
"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from faker import Faker

fake = Faker("zh_CN")

PER_MODULE = 20000
OUTPUT_DIR = Path(__file__).parent / "test_data"
OUTPUT_DIR.mkdir(exist_ok=True)


def _rand_date(days_back: int = 730) -> str:
    return fake.date_between(start_date=f"-{days_back}d", end_date="today").isoformat()


def _rand_future_date(days_ahead: int = 90) -> str:
    return fake.date_between(start_date="today", end_date=f"+{days_ahead}d").isoformat()


def generate_orders(count: int) -> list[dict[str, Any]]:
    """客户订单 - OrderCreate schema
    required: product_id(int), quantity(int), customer_name(str)
    optional: remark(str), order_type(str), country(str)
    """
    statuses = ["待备货", "备货中", "待出货", "已完成"]
    countries = ["中国", "美国", "日本", "德国", "英国", "巴西", "韩国", "印度", "法国", "澳大利亚"]
    types = ["常规订单", "加急订单", "样品订单", "补货订单"]

    rows = []
    for i in range(count):
        rows.append({
            "product_id": fake.random_int(min=1, max=9999),
            "quantity": fake.random_int(min=10, max=50000),
            "customer_name": fake.company(),
            "remark": fake.sentence()[:200] if fake.boolean(70) else "",
            "order_type": fake.random_element(types),
            "country": fake.random_element(countries),
            "status": fake.random_element(statuses),
            "order_date": _rand_date(),
            "order_no": f"ORD{datetime.now().strftime('%Y%m%d')}{20000 + i:06d}",
        })
    return rows


def generate_products(count: int) -> list[dict[str, Any]]:
    """产品清单 - ProductCreate schema
    required: product_name(str)
    optional: barcode(str), price(float), image_url(str), initial_stock(int)
    """
    units = ["个", "箱", "套", "件", "包", "卷"]
    rows = []
    for i in range(count):
        rows.append({
            "product_name": fake.word().title() + fake.random_element([" Pro", " Mini", " Lite", " Plus", ""]),
            "barcode": f"{fake.ean(length=13)}",
            "price": round(fake.random.uniform(1, 9999), 2),
            "image_url": f"/static/uploads/product_{20000 + i:06d}.jpg",
            "initial_stock": fake.random_int(min=0, max=100000),
            "unit": fake.random_element(units),
            "spec": f"{fake.random_int(10,300)}x{fake.random_int(10,300)}x{fake.random_int(1,50)}mm",
            "product_code": f"P{30000 + i:06d}",
        })
    return rows


def generate_customers(count: int) -> list[dict[str, Any]]:
    """客户管理 - CustomerCreate schema
    required: customer_name(str)
    optional: contact(str), phone(str), address(str), remark(str)
    """
    rows = []
    for i in range(count):
        rows.append({
            "customer_name": fake.company(),
            "contact": fake.name(),
            "phone": fake.phone_number(),
            "address": fake.address(),
            "remark": fake.sentence()[:200] if fake.boolean(40) else "",
            "email": fake.email(),
            "customer_code": f"CUS{40000 + i:06d}",
        })
    return rows


def generate_suppliers(count: int) -> list[dict[str, Any]]:
    """供应商管理 - SupplierCreate schema
    required: supplier_name(str)
    optional: contact(str), phone(str), address(str), remark(str)
    """
    types = ["原材料", "辅料", "包装", "物流", "化工", "五金", "电子", "纺织"]
    rows = []
    for i in range(count):
        rows.append({
            "supplier_name": fake.company(),
            "contact": fake.name(),
            "phone": fake.phone_number(),
            "address": fake.address(),
            "remark": fake.sentence()[:200] if fake.boolean(40) else "",
            "supplier_type": fake.random_element(types),
            "email": fake.email(),
            "supplier_code": f"SUP{50000 + i:06d}",
        })
    return rows


def generate_users(count: int) -> list[dict[str, Any]]:
    """用户管理 - UserCreate schema
    required: username(str), password(str)
    optional: is_superuser(bool)
    """
    roles = ["admin", "manager", "operator", "viewer", "warehouse", "sales"]
    rows = []
    for i in range(count):
        rows.append({
            "username": f"user_{70000 + i:06d}",
            "password": fake.password(length=12, special_chars=True),
            "is_superuser": fake.boolean(chance_of_getting_true=5),
            "display_name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "role": fake.random_element(roles),
            "status": fake.random_element(["active", "active", "active", "inactive"]),
        })
    return rows


def generate_approvals(count: int) -> list[dict[str, Any]]:
    """审批管理 - Approval schema
    审批单据关联各类业务
    """
    types = ["订单审批", "采购审批", "入库审批", "出库审批", "退款审批", "调拨审批"]
    statuses = ["待审批", "已通过", "已驳回", "已撤回"]
    rows = []
    for i in range(count):
        rows.append({
            "approval_type": fake.random_element(types),
            "status": fake.random_element(statuses),
            "applicant": fake.name(),
            "approver": fake.name() if fake.boolean(70) else None,
            "comment": fake.sentence()[:300] if fake.boolean(60) else "",
            "apply_date": _rand_date(365),
            "approval_no": f"APR{datetime.now().strftime('%Y%m')}{80000 + i:06d}",
            "reference_id": fake.random_int(min=1, max=99999),
        })
    return rows


def generate_stock_in(count: int) -> list[dict[str, Any]]:
    """入库管理 - StockIn create schema
    产品入库记录
    """
    types = ["采购入库", "退货入库", "调拨入库", "生产入库", "其他入库"]
    rows = []
    for i in range(count):
        rows.append({
            "product_id": fake.random_int(min=1, max=9999),
            "product_name": f"产品{fake.word().title()}",
            "quantity": fake.random_int(min=1, max=20000),
            "supplier_name": fake.company(),
            "unit_price": round(fake.random.uniform(0.1, 9999), 2),
            "in_date": _rand_date(),
            "remark": fake.sentence()[:200] if fake.boolean(30) else "",
            "stock_in_type": fake.random_element(types),
            "bill_no": f"IN{datetime.now().strftime('%Y%m%d')}{90000 + i:06d}",
        })
    return rows


def generate_stock_out(count: int) -> list[dict[str, Any]]:
    """出库管理 - StockOut create schema
    产品出库记录
    """
    types = ["销售出库", "退货出库", "调拨出库", "损耗出库", "赠送出库"]
    rows = []
    for i in range(count):
        rows.append({
            "order_id": fake.random_int(min=1, max=99999),
            "product_id": fake.random_int(min=1, max=9999),
            "product_name": f"产品{fake.word().title()}",
            "quantity": fake.random_int(min=1, max=15000),
            "customer_name": fake.company(),
            "out_date": _rand_date(),
            "remark": fake.sentence()[:200] if fake.boolean(30) else "",
            "stock_out_type": fake.random_element(types),
            "bill_no": f"OUT{datetime.now().strftime('%Y%m%d')}{100000 + i:06d}",
        })
    return rows


def generate_purchase_orders(count: int) -> list[dict[str, Any]]:
    """采购中心 - PurchaseOrderCreate schema
    required: product_id(int), quantity(int)
    optional: supplier_id(int)
    """
    statuses = ["待审核", "已审核", "采购中", "已入库", "已取消"]
    rows = []
    for i in range(count):
        rows.append({
            "product_id": fake.random_int(min=1, max=9999),
            "quantity": fake.random_int(min=100, max=100000),
            "supplier_id": fake.random_int(min=1, max=9999),
            "supplier_name": fake.company(),
            "order_date": _rand_date(),
            "expected_date": _rand_future_date(60),
            "status": fake.random_element(statuses),
            "purchase_no": f"PO{datetime.now().strftime('%Y%m%d')}{110000 + i:06d}",
            "remark": fake.sentence()[:200] if fake.boolean(40) else "",
        })
    return rows


def generate_material_registrations(count: int) -> list[dict[str, Any]]:
    """来料登记 - MaterialRegistrationCreate schema
    material_code, material_name, supplier_name, quantity
    """
    materials = ["PU皮", "真皮料", "硅胶片", "TPU片", "PC板", "凯夫拉布",
                  "钢板", "磁铁", "胶水", "线材", "拉链", "扣具", "海绵", "纸板"]
    qualities = ["合格", "合格", "合格", "让步接收", "不合格退货"]
    rows = []
    for i in range(count):
        rows.append({
            "material_code": f"MAT{datetime.now().strftime('%Y%m')}{120000 + i:06d}",
            "material_name": fake.random_element(materials),
            "supplier_name": fake.company(),
            "quantity": fake.random_int(min=100, max=100000),
            "unit": fake.random_element(["kg", "m", "张", "卷", "片", "个"]),
            "register_date": _rand_date(365),
            "inspector": fake.name(),
            "quality_result": fake.random_element(qualities),
            "remark": fake.sentence()[:200] if fake.boolean(30) else "",
        })
    return rows


def generate_purchase_plans(count: int) -> list[dict[str, Any]]:
    """采购计划 - PurchasePlanCreate schema
    customer_id, customer_name, plan_month, details[], remark
    """
    statuses = ["pending", "confirmed", "completed", "cancelled"]
    rows = []
    for i in range(count):
        details_count = fake.random_int(min=1, max=8)
        details = []
        total_qty = 0
        for _d in range(details_count):
            qty = fake.random_int(min=10, max=50000)
            total_qty += qty
            details.append({
                "product_id": fake.random_int(min=1, max=9999),
                "product_name": f"产品-{fake.word().title()}",
                "barcode": f"{fake.ean(length=13)}",
                "quantity": qty,
                "plan_date": _rand_future_date(90),
                "remark": "",
            })
        rows.append({
            "customer_id": fake.random_int(min=1, max=9999),
            "customer_name": fake.company(),
            "plan_month": fake.date_between(start_date="-6m", end_date="+3m").strftime("%Y-%m"),
            "details": details,
            "detail_count": details_count,
            "total_quantity": total_qty,
            "status": fake.random_element(statuses),
            "remark": fake.sentence()[:200] if fake.boolean(30) else "",
            "plan_no": f"PLN{datetime.now().strftime('%Y%m')}{130000 + i:06d}",
        })
    return rows


def generate_daily_productions(count: int) -> list[dict[str, Any]]:
    """生产报表 - ProductionRecordCreate schema
    required: department, product_name, quantity, production_date
    optional: product_id, barcode, unit_price, remark
    """
    departments = ["filling", "handcraft", "packaging"]
    dept_names = {"filling": "充棉部", "handcraft": "手工部", "packaging": "包装部"}
    rows = []
    for i in range(count):
        dept = fake.random_element(departments)
        rows.append({
            "department": dept,
            "department_name": dept_names[dept],
            "product_id": fake.random_int(min=1, max=9999) if fake.boolean(80) else None,
            "product_name": f"产品-{fake.word().title()}",
            "barcode": f"{fake.ean(length=13)}" if fake.boolean(70) else "",
            "unit_price": round(fake.random.uniform(0.5, 500), 2),
            "quantity": fake.random_int(min=10, max=50000),
            "production_date": _rand_date(365),
            "remark": fake.sentence()[:200] if fake.boolean(30) else "",
            "record_no": f"DPR{datetime.now().strftime('%Y%m%d')}{140000 + i:06d}",
        })
    return rows


def generate_production_summaries(count: int) -> list[dict[str, Any]]:
    """出货计划 - CraftWorkCreate schema（手工部/包装部录入）
    required: worker_name, quantity, work_date
    optional: remark
    """
    types = ["craft", "packaging"]
    rows = []
    for i in range(count):
        rows.append({
            "work_type": fake.random_element(types),
            "worker_name": fake.name(),
            "quantity": fake.random_int(min=1, max=5000),
            "work_date": _rand_date(365),
            "remark": fake.sentence()[:200] if fake.boolean(30) else "",
            "record_no": f"PSM{datetime.now().strftime('%Y%m%d')}{150000 + i:06d}",
        })
    return rows


def generate_cases(count: int) -> list[dict[str, Any]]:
    """皮套管理 - Case 表单数据
    皮套产品信息
    """
    materials = ["PU", "真皮", "硅胶", "TPU", "PC", "凯夫拉", "尼龙", "帆布"]
    colors = ["黑色", "白色", "红色", "蓝色", "绿色", "紫色", "粉色", "灰色", "棕色", "透明", "橙色", "黄色"]
    models = ["iPhone 15", "iPhone 15 Pro", "iPhone 15 Pro Max", "iPhone 16",
              "iPhone 16 Pro", "iPhone 16 Pro Max", "Samsung S24", "Samsung S24 Ultra",
              "华为 Mate 60", "华为 P70", "小米 14", "OPPO Find X7"]
    rows = []
    for i in range(count):
        rows.append({
            "case_code": f"C{300000 + i:06d}",
            "case_name": f"{fake.random_element(materials)}{fake.random_element(colors)}{fake.random_element(['皮套', '手机壳', '保护套'])}",
            "material": fake.random_element(materials),
            "color": fake.random_element(colors),
            "model": fake.random_element(models),
            "unit_price": round(fake.random.uniform(3, 299), 2),
            "quantity": fake.random_int(min=0, max=50000),
            "remark": fake.sentence()[:200] if fake.boolean(30) else "",
        })
    return rows


def save_json(data: list[dict], name: str) -> str:
    path = OUTPUT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(path)


def save_jsonl(data: list[dict], name: str) -> str:
    path = OUTPUT_DIR / f"{name}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return str(path)


def print_table(rows: list[tuple]):
    widths = [max(len(str(c)) for c in col) for col in zip(*rows, strict=False)]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    lines = [sep]
    for i, row in enumerate(rows):
        cells = "| " + " | ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=False)) + " |"
        lines.append(cells)
        if i == 0:
            lines.append(sep)
    lines.append(sep)
    return "\n".join(lines)


# ==================== MAIN ====================

if __name__ == "__main__":
    log_path = OUTPUT_DIR / "_run_log.txt"
    total_start = time.time()

    log_lines = []
    def log(msg):
        print(msg)
        log_lines.append(msg)

    modules = [
        ("客户订单", "orders", generate_orders),
        ("产品清单", "products", generate_products),
        ("客户管理", "customers", generate_customers),
        ("供应商管理", "suppliers", generate_suppliers),
        ("用户管理", "users", generate_users),
        ("审批管理", "approvals", generate_approvals),
        ("入库管理", "stock_in", generate_stock_in),
        ("出库管理", "stock_out", generate_stock_out),
        ("采购中心", "purchase_orders", generate_purchase_orders),
        ("来料登记", "material_registration", generate_material_registrations),
        ("采购计划", "purchase_plans", generate_purchase_plans),
        ("生产报表", "daily_productions", generate_daily_productions),
        ("出货计划", "production_summaries", generate_production_summaries),
        ("皮套管理", "cases", generate_cases),
    ]

    table_rows = [("板块", "输出文件", "记录数", "耗时(s)", "速度(条/s)")]

    grand_total = 0
    for name, file_tag, gen_func in modules:
        start = time.time()
        data = gen_func(PER_MODULE)
        elapsed = time.time() - start

        jsonl_path = save_jsonl(data, file_tag)
        grand_total += len(data)

        row = (name, f"{file_tag}.jsonl", f"{len(data):,}", f"{elapsed:.2f}", f"{PER_MODULE / elapsed:.0f}")
        table_rows.append(row)

    total_elapsed = time.time() - total_start

    log("=" * 70)
    log("  ERP系统全板块测试数据生成器 v2")
    log(f"  每板块: {PER_MODULE:,} 条 | 共 {len(modules)} 个板块")
    log("=" * 70)
    log(print_table(table_rows))
    log(f"  总计: {grand_total:,} 条记录")
    log(f"  总耗时: {total_elapsed:.1f}s")
    log(f"  输出目录: {OUTPUT_DIR}")
    log("=" * 70)

    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    log(f"\n日志已写入: {log_path}")
