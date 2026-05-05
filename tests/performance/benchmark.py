#!/usr/bin/env python3
"""
ERP 系统性能基准测试
直接测试 Service 层核心函数的执行时间
"""

import asyncio
import os
import statistics
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import _AsyncSessionLocal
from fastapi_app.services import (
    purchase_plan_service as pps,
    stock_service,
)


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


async def benchmark_monthly_calendar(db: AsyncSession) -> BenchmarkResult:
    result = BenchmarkResult("plans/monthly (calendar)")
    today = date.today()
    # warmup
    for _ in range(WARMUP_RUNS):
        await pps.get_monthly_calendar(db, today.year, today.month)
    # benchmark
    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        await pps.get_monthly_calendar(db, today.year, today.month)
        t1 = time.perf_counter()
        result.add(t1 - t0)
    return result


async def benchmark_customer_summary(db: AsyncSession) -> BenchmarkResult:
    result = BenchmarkResult("plans/customer-summary")
    today = date.today()
    for _ in range(WARMUP_RUNS):
        await pps.get_customer_summary(db, today.year, today.month)
    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        await pps.get_customer_summary(db, today.year, today.month)
        t1 = time.perf_counter()
        result.add(t1 - t0)
    return result


async def benchmark_inventory(db: AsyncSession) -> BenchmarkResult:
    result = BenchmarkResult("stock/inventory")
    for _ in range(WARMUP_RUNS):
        await stock_service.get_inventory(db)
    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        await stock_service.get_inventory(db)
        t1 = time.perf_counter()
        result.add(t1 - t0)
    return result


async def benchmark_inventory_paginated(db: AsyncSession) -> BenchmarkResult:
    result = BenchmarkResult("stock/inventory_paginated")
    for _ in range(WARMUP_RUNS):
        await stock_service.get_inventory_paginated(db, page=1, per_page=50)
    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        await stock_service.get_inventory_paginated(db, page=1, per_page=50)
        t1 = time.perf_counter()
        result.add(t1 - t0)
    return result


async def benchmark_stockins(db: AsyncSession) -> BenchmarkResult:
    result = BenchmarkResult("stock/in/list")
    for _ in range(WARMUP_RUNS):
        await stock_service.get_stockins(db, page=1, per_page=50)
    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        await stock_service.get_stockins(db, page=1, per_page=50)
        t1 = time.perf_counter()
        result.add(t1 - t0)
    return result


async def benchmark_stockouts(db: AsyncSession) -> BenchmarkResult:
    result = BenchmarkResult("stock/out/list")
    for _ in range(WARMUP_RUNS):
        await stock_service.get_stockouts(db, page=1, per_page=50)
    for _ in range(BENCHMARK_RUNS):
        t0 = time.perf_counter()
        await stock_service.get_stockouts(db, page=1, per_page=50)
        t1 = time.perf_counter()
        result.add(t1 - t0)
    return result


async def main():
    print("=" * 100)
    print("ERP 系统性能基准测试")
    print("=" * 100)
    print(f"配置: warmup={WARMUP_RUNS}, runs={BENCHMARK_RUNS}")
    print("-" * 100)

    async with _AsyncSessionLocal() as db:
        results = []

        print("\n[测试 1/6] 采购计划月度日历...")
        results.append(await benchmark_monthly_calendar(db))

        print("[测试 2/6] 客户汇总统计...")
        results.append(await benchmark_customer_summary(db))

        print("[测试 3/6] 库存汇总 (全量)...")
        results.append(await benchmark_inventory(db))

        print("[测试 4/6] 库存分页...")
        results.append(await benchmark_inventory_paginated(db))

        print("[测试 5/6] 入库列表分页...")
        results.append(await benchmark_stockins(db))

        print("[测试 6/6] 出库列表分页...")
        results.append(await benchmark_stockouts(db))

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
            print(f"⚠️  警告: {len(slow)} 个端点平均响应时间超过 200ms 目标")
            for r in slow:
                print(f"   - {r.name}: avg={r.avg_ms:.1f}ms")
        else:
            print("✅ 所有端点平均响应时间均在 200ms 以内")
        print("=" * 100)


if __name__ == "__main__":
    # Windows Python 3.13+ 默认 ProactorEventLoop 与 SQLAlchemy async/greenlet 存在兼容性 issues
    # 强制使用 SelectorEventLoopPolicy 可避免 MissingGreenlet 异常
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
