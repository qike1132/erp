#!/usr/bin/env python3
"""
ERP 系统性能基准测试（同步 psycopg3 版本）
绕过 SQLAlchemy async/greenlet 兼容性问题，直接测试核心 SQL 查询性能
"""

import os
import statistics
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import psycopg

from fastapi_app.core.config import settings


def get_sync_conn():
    """从 ASYNC_DATABASE_URL 构建同步连接字符串"""
    url = settings.ASYNC_DATABASE_URL
    # postgresql+asyncpg://user:pass@host:port/dbname -> postgresql://user:pass@host:port/dbname
    sync_url = url.replace("+asyncpg", "")
    return psycopg.connect(sync_url)


# ============= 配置 =============
WARMUP_RUNS = 3
BENCHMARK_RUNS = 10


class BenchmarkResult:
    def __init__(self, name: str):
        self.name = name
        self.times: list[float] = []

    def add(self, t: float):
        self.times.append(t)

    @property
    def min_ms(self) -> float:
        return min(self.times) * 1000

    @property
    def max_ms(self) -> float:
        return max(self.times) * 1000

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.times) * 1000

    @property
    def median_ms(self) -> float:
        return statistics.median(self.times) * 1000

    @property
    def p95_ms(self) -> float:
        sorted_times = sorted(self.times)
        idx = int(len(sorted_times) * 0.95)
        return sorted_times[idx] * 1000

    def __str__(self) -> str:
        return (
            f"{self.name:40s} | "
            f"min={self.min_ms:7.1f}ms | "
            f"avg={self.avg_ms:7.1f}ms | "
            f"med={self.median_ms:7.1f}ms | "
            f"p95={self.p95_ms:7.1f}ms | "
            f"max={self.max_ms:7.1f}ms"
        )


def benchmark_monthly_calendar(conn: psycopg.Connection) -> BenchmarkResult:
    result = BenchmarkResult("plans/monthly (calendar)")
    today = date.today()
    plan_month = f"{today.year}-{today.month:02d}"

    # 获取 plans + details 并聚合（模拟优化后的 get_monthly_calendar）
    sql = """
        SELECT
            pp.customer_name,
            pp.id AS plan_id,
            pd.id AS detail_id,
            pd.product_name,
            pd.barcode,
            pd.quantity,
            pd.plan_date
        FROM purchase_plans pp
        JOIN purchase_plan_details pd ON pp.id = pd.plan_id
        WHERE pp.plan_month = %s
        ORDER BY pd.plan_date
    """

    for _ in range(WARMUP_RUNS):
        with conn.cursor() as cur:
            cur.execute(sql, (plan_month,))
            cur.fetchall()

    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql, (plan_month,))
            cur.fetchall()
        t1 = time.perf_counter()
        result.add(t1 - t0)

    return result


def benchmark_customer_summary(conn: psycopg.Connection) -> BenchmarkResult:
    result = BenchmarkResult("plans/customer-summary")
    today = date.today()
    plan_month = f"{today.year}-{today.month:02d}"

    sql = """
        SELECT
            pp.customer_id,
            pp.customer_name,
            pd.product_name,
            SUM(pd.quantity) AS plan_qty
        FROM purchase_plans pp
        JOIN purchase_plan_details pd ON pp.id = pd.plan_id
        WHERE pp.plan_month = %s
        GROUP BY pp.customer_id, pp.customer_name, pd.product_name
    """

    for _ in range(WARMUP_RUNS):
        with conn.cursor() as cur:
            cur.execute(sql, (plan_month,))
            cur.fetchall()

    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql, (plan_month,))
            cur.fetchall()
        t1 = time.perf_counter()
        result.add(t1 - t0)

    return result


def benchmark_inventory(conn: psycopg.Connection) -> BenchmarkResult:
    result = BenchmarkResult("stock/inventory")

    # 模拟库存汇总查询（简化版 CTE）
    sql = """
        WITH stockin_agg AS (
            SELECT si.product_id, si.customer,
                   SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty
            FROM stock_in si
            LEFT JOIN (
                SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed
                FROM stock_out WHERE stockin_id IS NOT NULL GROUP BY stockin_id
            ) sub ON sub.stockin_id = si.id
            GROUP BY si.product_id, si.customer
        ),
        stockout_agg AS (
            SELECT product_id, customer,
                SUM(CASE WHEN order_id IS NULL THEN quantity - returned_quantity ELSE 0 END) AS direct_stockout_qty
            FROM stock_out
            WHERE stockin_id IS NULL
            GROUP BY product_id, customer
        ),
        order_agg AS (
            SELECT product_id, customer,
                SUM(quantity) AS regular_order_qty
            FROM "order"
            GROUP BY product_id, customer
        )
        SELECT
            COALESCE(sa.customer, soa.customer, oa.customer) AS customer,
            p.name AS product_name,
            COALESCE(sa.stockin_qty, 0) AS stockin_qty,
            COALESCE(soa.direct_stockout_qty, 0) AS direct_stockout_qty,
            COALESCE(oa.regular_order_qty, 0) AS regular_order_qty
        FROM stockin_agg sa
        FULL OUTER JOIN stockout_agg soa ON sa.product_id = soa.product_id AND sa.customer = soa.customer
        FULL OUTER JOIN order_agg oa ON COALESCE(sa.product_id, soa.product_id) = oa.product_id
            AND COALESCE(sa.customer, soa.customer) = oa.customer
        JOIN product p ON p.id = COALESCE(sa.product_id, soa.product_id, oa.product_id)
        LIMIT 50
    """

    for _ in range(WARMUP_RUNS):
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()

    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()
        t1 = time.perf_counter()
        result.add(t1 - t0)

    return result


def benchmark_stockins(conn: psycopg.Connection) -> BenchmarkResult:
    result = BenchmarkResult("stock/in/list")

    sql = """
        SELECT si.id, si.stockin_no, si.stockin_date, si.customer,
               p.id AS product_id, p.name AS product_name, p.barcode, p.image,
               si.quantity, COALESCE(d.deducted, 0) AS deducted, si.note
        FROM stock_in si
        LEFT JOIN product p ON si.product_id = p.id
        LEFT JOIN (
            SELECT stockin_id, SUM(quantity - returned_quantity) AS deducted
            FROM stock_out WHERE stockin_id IS NOT NULL GROUP BY stockin_id
        ) d ON d.stockin_id = si.id
        ORDER BY si.stockin_date DESC
        LIMIT 50
    """

    for _ in range(WARMUP_RUNS):
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()

    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()
        t1 = time.perf_counter()
        result.add(t1 - t0)

    return result


def benchmark_stockouts(conn: psycopg.Connection) -> BenchmarkResult:
    result = BenchmarkResult("stock/out/list")

    sql = """
        SELECT so.id, so.stockout_no, so.stockout_date, so.customer,
               p.id AS product_id, p.name AS product_name, p.barcode, p.image,
               so.quantity, so.returned_quantity, so.note,
               o.order_type, o.country
        FROM stock_out so
        LEFT JOIN product p ON so.product_id = p.id
        LEFT JOIN "order" o ON so.order_id = o.id
        WHERE so.stockin_id IS NULL
        ORDER BY so.stockout_date DESC
        LIMIT 50
    """

    for _ in range(WARMUP_RUNS):
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()

    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()
        t1 = time.perf_counter()
        result.add(t1 - t0)

    return result


def benchmark_orders(conn: psycopg.Connection) -> BenchmarkResult:
    result = BenchmarkResult("orders/list")

    sql = """
        SELECT o.id, o.order_no, o.customer, o.order_date,
               p.name AS product_name, o.quantity, o.status
        FROM "order" o
        LEFT JOIN product p ON o.product_id = p.id
        ORDER BY o.order_date DESC
        LIMIT 50
    """

    for _ in range(WARMUP_RUNS):
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()

    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.fetchall()
        t1 = time.perf_counter()
        result.add(t1 - t0)

    return result


def main():
    print("=" * 100)
    print("ERP 系统性能基准测试 (同步 psycopg3 直连)")
    print("=" * 100)
    print(f"配置: warmup={WARMUP_RUNS}, runs={BENCHMARK_RUNS}")
    print("-" * 100)

    with get_sync_conn() as conn:
        # 先确认数据量
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM purchase_plan_details")
            plan_details_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM stock_in")
            stockin_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM stock_out")
            stockout_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM \"order\"")
            order_count = cur.fetchone()[0]
            print("\n当前数据库数据量:")
            print(f"  - 采购计划明细: {plan_details_count:,} 条")
            print(f"  - 入库记录:     {stockin_count:,} 条")
            print(f"  - 出库记录:     {stockout_count:,} 条")
            print(f"  - 订单:         {order_count:,} 条")

        results = []
        print("\n[测试 1/6] 采购计划月度日历...")
        results.append(benchmark_monthly_calendar(conn))

        print("[测试 2/6] 客户汇总统计...")
        results.append(benchmark_customer_summary(conn))

        print("[测试 3/6] 库存汇总 (CTE)...")
        results.append(benchmark_inventory(conn))

        print("[测试 4/6] 入库列表分页...")
        results.append(benchmark_stockins(conn))

        print("[测试 5/6] 出库列表分页...")
        results.append(benchmark_stockouts(conn))

        print("[测试 6/6] 订单列表分页...")
        results.append(benchmark_orders(conn))

        print("\n" + "=" * 100)
        print("基准测试结果")
        print("=" * 100)
        print(f"{'API':40s} | {'min':>10s} | {'avg':>10s} | {'median':>10s} | {'p95':>10s} | {'max':>10s}")
        print("-" * 100)
        for r in results:
            print(r)

        print("-" * 100)
        slow = [r for r in results if r.avg_ms > 200]
        if slow:
            print(f"[!] 警告: {len(slow)} 个端点平均响应时间超过 200ms 目标")
            for r in slow:
                print(f"   - {r.name}: avg={r.avg_ms:.1f}ms")
        else:
            print("[OK] 所有端点平均响应时间均在 200ms 以内")
        print("=" * 100)


if __name__ == "__main__":
    main()
