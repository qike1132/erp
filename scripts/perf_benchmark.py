"""
性能基准测试 - 对所有核心操作进行性能基准测试

用法:
  python scripts/perf_benchmark.py --count 20000
  python scripts/perf_benchmark.py --count 20000 --iterations 5
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import _AsyncSessionLocal, _init_async_engine


results: dict[str, dict] = {}


async def bench(label: str, fn, iterations: int = 3):
    times = []
    for i in range(iterations):
        t0 = time.perf_counter()
        result = await fn()
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)
    avg = statistics.mean(times)
    med = statistics.median(times)
    p95 = sorted(times)[int(len(times) * 0.95)] if len(times) > 1 else times[0]
    results[label] = {"avg_ms": round(avg, 2), "median_ms": round(med, 2), "p95_ms": round(p95, 2), "iterations": iterations}
    status = "✓" if med < 200 else "✗"
    print(f"  {status} {label}: avg={avg:.1f}ms  median={med:.1f}ms  p95={p95:.1f}ms")
    return result


async def bench_product_list(session: AsyncSession, count: int, iterations: int):
    from fastapi_app.shared_models import Product
    from fastapi_app.services.product_service import get_products_page, get_products

    print("\n=== 产品列表查询 ===")

    await bench("products:page_1_50", lambda: get_products_page(session, page=1, per_page=50), iterations)
    await bench("products:page_1_200", lambda: get_products_page(session, page=1, per_page=200), iterations)
    if count > 1000:
        deep_page = count // 50
        await bench(f"products:deep_page_{deep_page}", lambda: get_products_page(session, page=deep_page, per_page=50), iterations)
    await bench("products:all_cached", lambda: get_products(session), iterations)
    await bench("products:search", lambda: get_products_page(session, page=1, per_page=50, search="产品_0001"), iterations)


async def bench_order_list(session: AsyncSession, count: int, iterations: int):
    from fastapi_app.services.order_service import get_orders

    print("\n=== 订单列表查询 ===")

    await bench("orders:page_1_50", lambda: get_orders(session, page=1, per_page=50), iterations)
    await bench("orders:page_1_200", lambda: get_orders(session, page=1, per_page=200), iterations)
    if count > 1000:
        deep_page = count // 50
        await bench(f"orders:deep_page_{deep_page}", lambda: get_orders(session, page=deep_page, per_page=50), iterations)


async def bench_stock_list(session: AsyncSession, count: int, iterations: int):
    from fastapi_app.services.stock_service import get_stockins

    print("\n=== 库存列表查询 ===")

    await bench("stockins:page_1_50", lambda: get_stockins(session, page=1, per_page=50), iterations)
    await bench("stockins:page_1_200", lambda: get_stockins(session, page=1, per_page=200), iterations)


async def bench_purchase_orders(session: AsyncSession, count: int, iterations: int):
    from fastapi_app.services.purchase_order_service import get_purchase_orders

    print("\n=== 采购订单查询（N+1验证） ===")

    await bench("purchase_orders:page_1_50", lambda: get_purchase_orders(session, page=1, per_page=50), iterations)
    await bench("purchase_orders:page_1_100", lambda: get_purchase_orders(session, page=1, per_page=100), iterations)


async def bench_count_queries(session: AsyncSession, iterations: int):
    from fastapi_app.shared_models import Order, Product, StockIn

    print("\n=== COUNT 查询 ===")

    await bench("count:orders", lambda: session.execute(select(func.count(Order.id))), iterations)
    await bench("count:products", lambda: session.execute(select(func.count(Product.id))), iterations)
    await bench("count:stockins", lambda: session.execute(select(func.count(StockIn.id))), iterations)


async def bench_optimized_count(session: AsyncSession, iterations: int):
    from fastapi_app.services.enhanced_pagination import optimized_count
    from fastapi_app.shared_models import Order

    print("\n=== 优化 COUNT (pg_class近似) ===")

    await bench("optimized_count:orders", lambda: optimized_count(session, select(func.count(Order.id)), "orders"), iterations)


async def bench_raw_queries(session: AsyncSession, iterations: int):
    print("\n=== 数据库延迟 ===")

    await bench("db:select_1", lambda: session.execute(text("SELECT 1")), iterations)
    await bench("db:pg_class", lambda: session.execute(text("SELECT reltuples::bigint FROM pg_class WHERE relname = 'orders'")), iterations)


async def main():
    parser = argparse.ArgumentParser(description="性能基准测试")
    parser.add_argument("--count", type=int, default=20000, help="预期数据量")
    parser.add_argument("--iterations", type=int, default=3, help="每个测试重复次数")
    parser.add_argument("--output", type=str, default="scripts/perf_benchmark_results.json", help="结果输出文件")
    args = parser.parse_args()

    _init_async_engine()
    print(f"性能基准测试 - 数据量阈值: {args.count}, 迭代: {args.iterations}")

    async with _AsyncSessionLocal() as session:
        await bench_raw_queries(session, args.iterations)
        await bench_count_queries(session, args.iterations)
        await bench_optimized_count(session, args.iterations)
        await bench_product_list(session, args.count, args.iterations)
        await bench_order_list(session, args.count, args.iterations)
        await bench_stock_list(session, args.count, args.iterations)
        await bench_purchase_orders(session, args.count, args.iterations)

    passed = sum(1 for v in results.values() if v["median_ms"] < 200)
    total = len(results)
    print(f"\n=== 结果汇总 ===")
    print(f"通过: {passed}/{total} (目标: median < 200ms)")
    if passed < total:
        print("未通过:")
        for k, v in results.items():
            if v["median_ms"] >= 200:
                print(f"  ✗ {k}: {v['median_ms']:.1f}ms")

    output_path = Path(args.output)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n结果已保存: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
