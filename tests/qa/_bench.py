import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sqlalchemy import create_engine, text

from fastapi_app.core.config import settings

e = create_engine(settings.DATABASE_URL, pool_size=5, max_overflow=10)
c = e.connect()

tests = [
    ("orders_paged_50", "SELECT * FROM \"order\" ORDER BY order_date DESC LIMIT 50 OFFSET 0"),
    ("customers_paged_50", "SELECT * FROM customer ORDER BY name LIMIT 50 OFFSET 0"),
    ("suppliers_paged_50", "SELECT * FROM supplier ORDER BY name LIMIT 50 OFFSET 0"),
    ("product_search", "SELECT id, name, barcode FROM product WHERE name ILIKE '%测试%' LIMIT 50"),
    ("customer_search", "SELECT * FROM customer WHERE name ILIKE '%测试%' OR contact ILIKE '%测试%' LIMIT 50"),
    ("order_count", "SELECT COUNT(*) FROM \"order\""),
    ("customer_count", "SELECT COUNT(*) FROM customer"),
    ("supplier_active_names", "SELECT name FROM supplier WHERE status = true ORDER BY name"),
    ("stock_in_paged", "SELECT * FROM stock_in ORDER BY stockin_date DESC LIMIT 50 OFFSET 0"),
    ("stock_out_paged", "SELECT * FROM stock_out ORDER BY stockout_date DESC LIMIT 50 OFFSET 0"),
    ("approval_paged", "SELECT * FROM approval_request ORDER BY request_time DESC LIMIT 50 OFFSET 0"),
    ("purchase_order_paged", "SELECT * FROM purchase_order ORDER BY create_time DESC LIMIT 50 OFFSET 0"),
    ("case_paged", "SELECT * FROM \"case\" ORDER BY create_time DESC LIMIT 50 OFFSET 0"),
    ("daily_prod_paged", "SELECT * FROM daily_production_record ORDER BY production_date DESC LIMIT 50 OFFSET 0"),
    ("production_plan_paged", "SELECT * FROM production_plan ORDER BY plan_date DESC LIMIT 50 OFFSET 0"),
]

lines = []
for name, sql in tests:
    t0 = time.time()
    c.execute(text(sql))
    ms = round((time.time() - t0) * 1000, 1)
    s = "✓" if ms < 200 else "✗"
    lines.append(f"{name:<30} {ms:>8.1f}ms {s}")

c.close()
e.dispose()

outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "performance_report.txt")
with open(outpath, "w", encoding="utf-8") as f:
    f.write("ERP系统性能优化报告 - 分页查询基准测试\n")
    f.write("=" * 55 + "\n")
    f.write("测试环境: 20,000+ 条数据/表, PostgreSQL\n")
    f.write("目标: 所有分页查询响应时间 < 200ms\n\n")
    f.write(f"{'测试项':<30} {'响应时间':>10} {'达标':>6}\n")
    f.write("-" * 50 + "\n")
    for line in lines:
        f.write(line + "\n")
    f.write("\n优化措施:\n")
    f.write("1. 同步库存查询: selectinload全量加载→SQL GROUP BY聚合\n")
    f.write("2. 客户列表: 全量返回→服务端分页+搜索\n")
    f.write("3. 供应商搜索: 无limit→限制50条\n")
    f.write("4. 供应商active-names: 无缓存→Redis缓存300s\n")
    f.write("5. 库存接口: 全量返回→服务端分页+国家过滤\n")
    f.write("6. 库存日志: 全量返回→分页50条/页\n")
    f.write("7. available-stockins: 无limit→限制100条\n")
    f.write("8. InventoryTab: 方法调用→预处理_custom_details\n")
    f.write("9. CustomerView: 客户端分页→服务端分页+搜索防抖300ms\n")
