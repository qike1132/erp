"""
数据库层性能基准测试 - 直接测试 service 层，无需 HTTP

对比优化前后的关键查询性能。
目标：库存查询 < 200ms，其他列表 < 100ms

运行方式：
  python -m tests.performance.bench_db
"""
import asyncio
import os
import sys
import time
import statistics

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)


async def bench_inventory_service():
    """测试库存服务层性能"""
    from fastapi_app.core.database import async_session_factory
    from fastapi_app.services import stock_service

    results = {}

    async with async_session_factory() as db:
        # 1. 旧版 get_inventory (全量加载)
        print('测试 get_inventory (旧版 - 全量加载)...')
        latencies = []
        for i in range(5):
            start = time.perf_counter()
            result = await stock_service.get_inventory(db, search_customer='', search_product='')
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            print(f'  第{i+1}次: {elapsed:.1f}ms (共{len(result["inventory_data"])}条)')
        results['get_inventory_full'] = {
            'avg_ms': round(statistics.mean(latencies), 1),
            'p50_ms': round(statistics.median(latencies), 1),
            'max_ms': round(max(latencies), 1),
            'count': len(result.get('inventory_data', [])),
        }

        # 2. 新版 get_inventory_paginated (SQL CTE 分页)
        print('\n测试 get_inventory_paginated (新版 - SQL CTE)...')
        latencies = []
        for i in range(5):
            start = time.perf_counter()
            result = await stock_service.get_inventory_paginated(db, search_customer='', search_product='', page=1, per_page=50)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            print(f'  第{i+1}次: {elapsed:.1f}ms (返回{len(result["inventory_data"])}条/共{result["total_items"]}条)')
        results['get_inventory_paginated_page1'] = {
            'avg_ms': round(statistics.mean(latencies), 1),
            'p50_ms': round(statistics.median(latencies), 1),
            'max_ms': round(max(latencies), 1),
            'total_items': result.get('total_items', 0),
        }

        # 3. 带客户筛选
        print('\n测试 get_inventory_paginated (客户筛选)...')
        latencies = []
        # 先获取一个客户名
        if result.get('inventory_data'):
            sample_customer = result['inventory_data'][0].get('customer', '')
        else:
            sample_customer = ''
        if sample_customer:
            for i in range(5):
                start = time.perf_counter()
                result2 = await stock_service.get_inventory_paginated(db, search_customer=sample_customer, page=1, per_page=50)
                elapsed = (time.perf_counter() - start) * 1000
                latencies.append(elapsed)
                print(f'  第{i+1}次: {elapsed:.1f}ms')
            results['get_inventory_paginated_filtered'] = {
                'avg_ms': round(statistics.mean(latencies), 1),
                'p50_ms': round(statistics.median(latencies), 1),
                'max_ms': round(max(latencies), 1),
            }

        # 4. 翻页
        print('\n测试 get_inventory_paginated (翻页)...')
        latencies = []
        for i in range(5):
            start = time.perf_counter()
            result3 = await stock_service.get_inventory_paginated(db, page=5, per_page=50)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            print(f'  第{i+1}次: {elapsed:.1f}ms')
        results['get_inventory_paginated_page5'] = {
            'avg_ms': round(statistics.mean(latencies), 1),
            'p50_ms': round(statistics.median(latencies), 1),
            'max_ms': round(max(latencies), 1),
        }

    return results


async def bench_other_services():
    """测试其他服务层性能"""
    from fastapi_app.core.database import async_session_factory
    from fastapi_app.services import order_service, product_service, case_service

    results = {}

    async with async_session_factory() as db:
        # 订单列表
        print('测试 order_service.get_orders...')
        latencies = []
        for i in range(5):
            start = time.perf_counter()
            result = await order_service.get_orders(db, page=1, per_page=50)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
        results['orders_page1'] = {
            'avg_ms': round(statistics.mean(latencies), 1),
            'p50_ms': round(statistics.median(latencies), 1),
            'max_ms': round(max(latencies), 1),
            'total': result.get('total', 0),
        }
        print(f'  avg={results["orders_page1"]["avg_ms"]:.1f}ms, total={result.get("total", 0)}')

        # 产品列表
        print('测试 product_service.get_products_page...')
        latencies = []
        for i in range(5):
            start = time.perf_counter()
            result = await product_service.get_products_page(db, page=1, per_page=50)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
        results['products_page1'] = {
            'avg_ms': round(statistics.mean(latencies), 1),
            'p50_ms': round(statistics.median(latencies), 1),
            'max_ms': round(max(latencies), 1),
        }
        print(f'  avg={results["products_page1"]["avg_ms"]:.1f}ms')

        # 皮套库存汇总
        print('测试 case_service.get_case_inventory_summary...')
        latencies = []
        for i in range(5):
            start = time.perf_counter()
            result = await case_service.get_case_inventory_summary(db, page=1, per_page=50)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
        results['case_inventory_summary'] = {
            'avg_ms': round(statistics.mean(latencies), 1),
            'p50_ms': round(statistics.median(latencies), 1),
            'max_ms': round(max(latencies), 1),
        }
        print(f'  avg={results["case_inventory_summary"]["avg_ms"]:.1f}ms')

    return results


async def main():
    print('=' * 60)
    print('  数据库层性能基准测试')
    print('=' * 60)
    print()

    print('--- 库存服务 ---')
    inv_results = await bench_inventory_service()
    print()

    print('--- 其他服务 ---')
    other_results = await bench_other_services()
    print()

    # 汇总
    print('=' * 60)
    print('  结果汇总')
    print('=' * 60)
    all_results = {**inv_results, **other_results}
    for name, data in all_results.items():
        status = 'PASS' if data['p50_ms'] <= 200 else 'FAIL'
        print(f'  [{status}] {name}: avg={data["avg_ms"]:.1f}ms  p50={data["p50_ms"]:.1f}ms  max={data["max_ms"]:.1f}ms')

    # 计算库存优化效果
    if 'get_inventory_full' in inv_results and 'get_inventory_paginated_page1' in inv_results:
        full_avg = inv_results['get_inventory_full']['avg_ms']
        page_avg = inv_results['get_inventory_paginated_page1']['avg_ms']
        if full_avg > 0:
            improvement = round((1 - page_avg / full_avg) * 100, 1)
            print(f'\n  库存查询优化效果: 首页加载从 {full_avg:.1f}ms → {page_avg:.1f}ms (提升 {improvement}%)')


if __name__ == '__main__':
    asyncio.run(main())
