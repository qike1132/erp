"""
性能基准测试脚本 - 验证20000+条数据下的系统性能
测试目标：所有核心操作响应时间 < 200ms
"""
import asyncio
import json
import logging
import statistics
import time
from datetime import datetime

import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:8000/api/v1"
RESULTS: dict[str, list[float]] = {}
TOKEN = ""


async def login(client: httpx.AsyncClient) -> str:
    """登录获取token"""
    resp = await client.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "admin123"})
    if resp.status_code == 200:
        data = resp.json()
        return data.get("access_token", data.get("token", ""))
    raise RuntimeError(f"Login failed: {resp.status_code} {resp.text}")


async def measure(client: httpx.AsyncClient, name: str, method: str, url: str,
                  params: dict | None = None, json_data: dict | None = None,
                  iterations: int = 5) -> dict:
    """测量API响应时间"""
    times = []
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

    for _ in range(iterations):
        start = time.perf_counter()
        if method == "GET":
            resp = await client.get(url, params=params, headers=headers)
        elif method == "POST":
            resp = await client.post(url, json=json_data, headers=headers)
        else:
            resp = await client.get(url, params=params, headers=headers)
        elapsed = (time.perf_counter() - start) * 1000  # ms

        if resp.status_code in (200, 201):
            times.append(elapsed)
        else:
            logger.warning(f"  {name}: HTTP {resp.status_code} (skipped)")

    if not times:
        return {"name": name, "status": "FAILED", "times": []}

    RESULTS[name] = times
    avg = statistics.mean(times)
    p95 = sorted(times)[int(len(times) * 0.95)] if len(times) >= 2 else max(times)
    status = "PASS" if avg < 200 else "WARN" if avg < 500 else "FAIL"

    return {
        "name": name,
        "status": status,
        "avg_ms": round(avg, 1),
        "p95_ms": round(p95, 1),
        "min_ms": round(min(times), 1),
        "max_ms": round(max(times), 1),
        "iterations": len(times),
    }


async def run_benchmarks():
    """执行所有性能基准测试"""
    global TOKEN
    results = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Login
        try:
            TOKEN = await login(client)
            logger.info("Login successful")
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return []

        # === 来料登记模块 (MaterialRegistration) ===
        logger.info("=== 来料登记模块性能测试 ===")

        results.append(await measure(client, "来料列表-第1页", "GET",
            f"{BASE_URL}/material/registrations", {"page": 1, "per_page": 20}))

        results.append(await measure(client, "来料列表-深翻页", "GET",
            f"{BASE_URL}/material/registrations", {"page": 50, "per_page": 20}))

        results.append(await measure(client, "来料列表-按供应商筛选", "GET",
            f"{BASE_URL}/material/registrations", {"page": 1, "per_page": 20, "supplier": "测试"}))

        results.append(await measure(client, "来料统计概览", "GET",
            f"{BASE_URL}/material/stats/overview"))

        results.append(await measure(client, "来料趋势数据", "GET",
            f"{BASE_URL}/material/stats/trend", {"days": 30}))

        results.append(await measure(client, "来料状态分布", "GET",
            f"{BASE_URL}/material/stats/distribution"))

        results.append(await measure(client, "来料历史-第1页", "GET",
            f"{BASE_URL}/material/history", {"page": 1, "per_page": 20}))

        # === 产品模块 (Product) ===
        logger.info("=== 产品模块性能测试 ===")

        results.append(await measure(client, "产品列表-第1页", "GET",
            f"{BASE_URL}/products/list", {"page": 1, "per_page": 20}))

        results.append(await measure(client, "产品列表-搜索", "GET",
            f"{BASE_URL}/products/list", {"page": 1, "per_page": 20, "search": "测试"}))

        results.append(await measure(client, "产品列表-排序", "GET",
            f"{BASE_URL}/products/list", {"page": 1, "per_page": 20, "sort_by": "name", "sort_order": "asc"}))

        # === 订单模块 (Order) ===
        logger.info("=== 订单模块性能测试 ===")

        results.append(await measure(client, "订单列表-第1页", "GET",
            f"{BASE_URL}/orders", {"page": 1, "per_page": 20}))

        results.append(await measure(client, "订单列表-深翻页", "GET",
            f"{BASE_URL}/orders", {"page": 100, "per_page": 20}))

        results.append(await measure(client, "订单列表-按客户筛选", "GET",
            f"{BASE_URL}/orders", {"page": 1, "per_page": 20, "customer": "测试"}))

        # === 库存模块 (Stock) ===
        logger.info("=== 库存模块性能测试 ===")

        results.append(await measure(client, "库存查询-第1页", "GET",
            f"{BASE_URL}/stock/inventory", {"page": 1, "per_page": 20}))

        results.append(await measure(client, "入库列表-第1页", "GET",
            f"{BASE_URL}/stock/stockins", {"page": 1, "per_page": 20}))

        results.append(await measure(client, "出库列表-第1页", "GET",
            f"{BASE_URL}/stock/stockouts", {"page": 1, "per_page": 20}))

        # === 客户模块 (Customer) ===
        logger.info("=== 客户模块性能测试 ===")

        results.append(await measure(client, "客户列表-第1页", "GET",
            f"{BASE_URL}/customers", {"page": 1, "per_page": 15}))

        results.append(await measure(client, "客户列表-搜索", "GET",
            f"{BASE_URL}/customers", {"page": 1, "per_page": 15, "search": "测试"}))

    return results


def print_report(results: list[dict]):
    """打印性能测试报告"""
    print("\n" + "=" * 80)
    print("  性能基准测试报告")
    print(f"  测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("  目标: 所有操作平均响应时间 < 200ms")
    print("=" * 80)

    passed = sum(1 for r in results if r.get("status") == "PASS")
    warned = sum(1 for r in results if r.get("status") == "WARN")
    failed = sum(1 for r in results if r.get("status") in ("FAIL", "FAILED"))

    print(f"\n  总计: {len(results)} 项 | PASS: {passed} | WARN: {warned} | FAIL: {failed}")
    print("-" * 80)
    print(f"  {'测试项':<25} {'状态':<6} {'平均(ms)':<10} {'P95(ms)':<10} {'最小':<8} {'最大':<8}")
    print("-" * 80)

    for r in results:
        status_icon = {"PASS": "[OK]", "WARN": "[!!]", "FAIL": "[XX]", "FAILED": "[--]"}.get(r["status"], "???")
        if r["status"] == "FAILED":
            print(f"  {r['name']:<25} {status_icon:<6} {'N/A':<10} {'N/A':<10} {'N/A':<8} {'N/A':<8}")
        else:
            print(f"  {r['name']:<25} {status_icon:<6} {r['avg_ms']:<10} {r['p95_ms']:<10} {r['min_ms']:<8} {r['max_ms']:<8}")

    print("-" * 80)

    # Summary
    valid_results = [r for r in results if r.get("status") != "FAILED"]
    if valid_results:
        all_avgs = [r["avg_ms"] for r in valid_results]
        print(f"\n  整体平均响应时间: {statistics.mean(all_avgs):.1f}ms")
        print(f"  最慢接口: {max(valid_results, key=lambda x: x['avg_ms'])['name']} ({max(all_avgs):.1f}ms)")
        print(f"  最快接口: {min(valid_results, key=lambda x: x['avg_ms'])['name']} ({min(all_avgs):.1f}ms)")

    verdict = "PASS" if failed == 0 and warned == 0 else ("PARTIAL" if failed == 0 else "FAIL")
    print(f"\n  最终结论: {verdict}")
    print("=" * 80)

    return {"results": results, "summary": {"total": len(results), "passed": passed, "warned": warned, "failed": failed, "verdict": verdict}}


async def main():
    results = await run_benchmarks()
    report = print_report(results)

    # Save report
    with open("tests/performance_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info("Report saved to tests/performance_report.json")


if __name__ == "__main__":
    asyncio.run(main())
