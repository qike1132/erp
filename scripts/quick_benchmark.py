"""
FastAPI 性能基准测试脚本
"""
import asyncio
import json
import statistics
import time
from datetime import datetime

import httpx
import psutil

BASE_URL = "http://127.0.0.1:5002"
TEST_DURATION = 20
CONCURRENT_USERS = 100
TARGET_ENDPOINT = "/api/v1/aux/health"

async def single_user(user_id: int, duration: float, results: list):
    async with httpx.AsyncClient(timeout=10.0) as client:
        end_time = time.time() + duration
        while time.time() < end_time:
            try:
                start = time.perf_counter()
                resp = await client.get(f"{BASE_URL}{TARGET_ENDPOINT}")
                elapsed_ms = (time.perf_counter() - start) * 1000
                results.append((elapsed_ms, resp.status_code))
            except Exception:
                results.append((999999, 0))

async def main():
    print(f"FastAPI 性能测试 | {CONCURRENT_USERS} 并发 | {TEST_DURATION}秒 | {TARGET_ENDPOINT}")
    print("=" * 50)

    results = []
    start_mem = psutil.Process().memory_info().rss / 1024 / 1024

    start = time.time()
    tasks = [single_user(i, TEST_DURATION, results) for i in range(CONCURRENT_USERS)]
    await asyncio.gather(*tasks, return_exceptions=True)
    elapsed = time.time() - start

    total = len(results)
    success = sum(1 for _, code in results if code == 200)
    rps = total / elapsed if elapsed > 0 else 0

    times = sorted([t for t, _ in results])
    n = len(times)

    print(f"\n总请求: {total}")
    print(f"成功: {success} ({(success/total*100) if total > 0 else 0:.1f}%)")
    print(f"RPS: {rps:.2f}")
    print("\n响应时间 (ms):")
    print(f"  平均: {statistics.mean(times):.2f}")
    print(f"  最小: {min(times):.2f}")
    print(f"  最大: {max(times):.2f}")
    print(f"  P50:  {times[n//2]:.2f}")
    print(f"  P95:  {times[int(n*0.95)]:.2f}")
    print(f"  P99:  {times[int(n*0.99)]:.2f}")

    end_mem = psutil.Process().memory_info().rss / 1024 / 1024
    print(f"\n内存: {start_mem:.1f}MB -> {end_mem:.1f}MB (增长 {end_mem-start_mem:.1f}MB)")

    report = {
        "test_time": datetime.now().isoformat(),
        "configuration": {
            "base_url": BASE_URL,
            "endpoint": TARGET_ENDPOINT,
            "concurrent_users": CONCURRENT_USERS,
            "duration_seconds": TEST_DURATION
        },
        "results": {
            "total_requests": total,
            "successful_requests": success,
            "failed_requests": total - success,
            "success_rate_percent": round((success/total*100) if total > 0 else 0, 2),
            "rps": round(rps, 2),
            "response_time_ms": {
                "average": round(statistics.mean(times), 2),
                "min": round(min(times), 2),
                "max": round(max(times), 2),
                "p50": round(times[n//2], 2),
                "p95": round(times[int(n*0.95)], 2),
                "p99": round(times[int(n*0.99)], 2)
            },
            "memory_mb": {
                "initial": round(start_mem, 2),
                "peak": round(end_mem, 2),
                "growth": round(end_mem - start_mem, 2)
            }
        }
    }

    with open("d:/erp_system/scripts/performance_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n报告已保存: d:/erp_system/scripts/performance_report.json")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
