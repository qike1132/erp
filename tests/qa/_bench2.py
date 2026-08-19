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
    s = "OK" if ms < 200 else "SLOW"
    lines.append(f"{name},{ms},{s}")

c.close()
e.dispose()

outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perf_result.csv")
with open(outpath, "w", encoding="utf-8") as f:
    f.write("test_name,response_ms,status\n")
    for line in lines:
        f.write(line + "\n")
