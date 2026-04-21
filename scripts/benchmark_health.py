"""
FastAPI 性能基准测试脚本 - 无速率限制版
针对 /api/v1/health 端点进行纯性能测试
"""
import asyncio
import time
import statistics
import psutil
import os
import json
from datetime import datetime
from typing import List, Dict
import httpx

BASE_URL = "http://127.0.0.1:5002"
TEST_DURATION = 30
CONCURRENT_USERS = 100
TARGET_ENDPOINT = "/api/v1/health"

class PerformanceMetrics:
    def __init__(self):
        self.response_times: List[float] = []
        self.error_count = 0
        self.success_count = 0
        self.status_codes: Dict[int, int] = {}
        self.start_memory = 0
        self.peak_memory = 0
        self.requests_completed = 0

    def record_request(self, duration: float, status_code: int):
        self.response_times.append(duration)
        self.requests_completed += 1
        self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
        if status_code == 200:
            self.success_count += 1
        else:
            self.error_count += 1

async def single_user_benchmark(user_id: int, duration: float, metrics: PerformanceMetrics):
    async with httpx.AsyncClient(timeout=30.0) as client:
        end_time = time.time() + duration
        request_count = 0

        while time.time() < end_time:
            try:
                start = time.perf_counter()
                response = await client.get(f"{BASE_URL}{TARGET_ENDPOINT}")
                duration_ms = (time.perf_counter() - start) * 1000
                metrics.record_request(duration_ms, response.status_code)
                request_count += 1
            except Exception as e:
                metrics.record_request(999999, 0)

            await asyncio.sleep(0.05)

    return request_count

async def run_benchmark():
    print("=" * 60)
    print("FastAPI 性能基准测试")
    print("=" * 60)
    print(f"目标 URL: {BASE_URL}{TARGET_ENDPOINT}")
    print(f"并发用户: {CONCURRENT_USERS}")
    print(f"测试时长: {TEST_DURATION} 秒")
    print("=" * 60)

    process = psutil.Process(os.getpid())
    metrics = PerformanceMetrics()
    metrics.start_memory = process.memory_info().rss / 1024 / 1024

    print(f"\n初始内存: {metrics.start_memory:.2f} MB")
    print("开始测试...\n")

    start_time = time.time()

    tasks = [
        single_user_benchmark(i, TEST_DURATION, metrics)
        for i in range(CONCURRENT_USERS)
    ]

    results = await asyncio.gather(*tasks)

    elapsed = time.time() - start_time

    peak_mem = process.memory_info().rss / 1024 / 1024
    metrics.peak_memory = peak_mem

    total_requests = sum(results)
    rps = total_requests / elapsed if elapsed > 0 else 0

    if metrics.response_times:
        avg_rt = statistics.mean(metrics.response_times)
        min_rt = min(metrics.response_times)
        max_rt = max(metrics.response_times)
        sorted_times = sorted(metrics.response_times)
        p50_idx = int(len(sorted_times) * 0.50)
        p95_idx = int(len(sorted_times) * 0.95)
        p99_idx = int(len(sorted_times) * 0.99)
        p50 = sorted_times[p50_idx] if p50_idx < len(sorted_times) else avg_rt
        p95 = sorted_times[p95_idx] if p95_idx < len(sorted_times) else avg_rt
        p99 = sorted_times[p99_idx] if p99_idx < len(sorted_times) else avg_rt
    else:
        avg_rt = min_rt = max_rt = p50 = p95 = p99 = 0

    success_rate = (metrics.success_count / total_requests * 100) if total_requests > 0 else 0
    error_rate = (metrics.error_count / total_requests * 100) if total_requests > 0 else 0

    print("\n" + "=" * 60)
    print("测试结果")
    print("=" * 60)
    print(f"总请求数:     {total_requests}")
    print(f"成功请求:     {metrics.success_count} ({success_rate:.2f}%)")
    print(f"失败请求:     {metrics.error_count} ({error_rate:.2f}%)")
    print(f"总耗时:       {elapsed:.2f} 秒")
    print(f"RPS:         {rps:.2f} 请求/秒")
    print("-" * 60)
    print("响应时间 (ms):")
    print(f"  平均:       {avg_rt:.2f}")
    print(f"  最小:       {min_rt:.2f}")
    print(f"  最大:       {max_rt:.2f}")
    print(f"  P50:        {p50:.2f}")
    print(f"  P95:        {p95:.2f}")
    print(f"  P99:        {p99:.2f}")
    print("-" * 60)
    print("资源使用:")
    print(f"  初始内存:   {metrics.start_memory:.2f} MB")
    print(f" 峰值内存:   {metrics.peak_memory:.2f} MB")
    print(f"  内存增长:   {metrics.peak_memory - metrics.start_memory:.2f} MB")
    print("-" * 60)
    print("HTTP 状态码分布:")
    for code, count in sorted(metrics.status_codes.items()):
        print(f"  {code}: {count}")
    print("=" * 60)

    report = {
        "test_time": datetime.now().isoformat(),
        "configuration": {
            "base_url": BASE_URL,
            "endpoint": TARGET_ENDPOINT,
            "concurrent_users": CONCURRENT_USERS,
            "duration_seconds": TEST_DURATION
        },
        "results": {
            "total_requests": total_requests,
            "successful_requests": metrics.success_count,
            "failed_requests": metrics.error_count,
            "success_rate_percent": round(success_rate, 2),
            "error_rate_percent": round(error_rate, 2),
            "duration_seconds": round(elapsed, 2),
            "rps": round(rps, 2),
            "response_time_ms": {
                "average": round(avg_rt, 2),
                "min": round(min_rt, 2),
                "max": round(max_rt, 2),
                "p50": round(p50, 2),
                "p95": round(p95, 2),
                "p99": round(p99, 2)
            },
            "memory_mb": {
                "initial": round(metrics.start_memory, 2),
                "peak": round(metrics.peak_memory, 2),
                "growth": round(metrics.peak_memory - metrics.start_memory, 2)
            },
            "status_codes": metrics.status_codes
        }
    }

    report_path = os.path.join(os.path.dirname(__file__), "performance_report.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n报告已保存: {report_path}")

    return report

if __name__ == "__main__":
    asyncio.run(run_benchmark())
