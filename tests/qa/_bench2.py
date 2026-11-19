import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from sqlalchemy import create_engine, text

from fastapi_app.core.config import settings
from tests._prod_guard import require_non_production_database

# 一次性运维脚本守卫（2026-11-17 上线前审计 SUP-1）：
# 下面的模块级代码会 create_engine(settings.DATABASE_URL).connect() —— 在本机就是生产库。
# 只允许直接运行，禁止被 import（pytest 收集/工具批量 import 都会踩到）。
if __name__ != "__main__":
    raise RuntimeError(
        "tests/qa/_bench2.py 是一次性运维脚本：只允许 `python tests/qa/_bench2.py` 直接运行，"
        "禁止 import（模块级会连生产库；见 2026-11-17 审计 SUP-1）"
    )

# 2026-11-17 OCR 复审：上面的守卫只管「被 import」，**直接运行**时下面这行照样连生产库
# （本机 .env 的 DATABASE_URL 即生产库）。与 tests/qa/_bench.py:12、
# performance_benchmark.py:17 同款：在 create_engine **之前**过库名守卫——
# 目标库不是 *_test 且未显式设 PERF_TEST_ALLOW_PROD_DB=1 就 SystemExit（fail-closed）。
require_non_production_database(settings.DATABASE_URL)

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

# 4.4（2026-10-17 审计 P2）：不要把结果写进仓库 —— 原先落 tests/qa/perf_result.csv，
# 跑一次就在工作区留一个未跟踪的脏文件（且 .gitignore 没覆盖它）。默认落系统临时目录，
# 需要留档时用 PERF_OUTPUT_DIR 显式指定。
_out_dir = os.getenv("PERF_OUTPUT_DIR") or tempfile.gettempdir()
outpath = os.path.join(_out_dir, "perf_result.csv")
with open(outpath, "w", encoding="utf-8") as f:
    f.write("test_name,response_ms,status\n")
    for line in lines:
        f.write(line + "\n")
