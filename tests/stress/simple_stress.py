"""
ERP系统压力测试 - 简化版
测试API端点是否正常工作
"""

import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
import asyncio
import statistics
import time

import aiohttp
from _prod_guard import require_non_production

BASE_URL = "http://127.0.0.1:5002"
CONCURRENT_USERS = 100
DURATION_SECONDS = 3600  # 60分钟

results = []
errors = []

async def get_token(session):
    try:
        async with session.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("access_token")
            else:
                errors.append(f"登录失败: {resp.status}")
    except Exception as e:
        errors.append(f"登录异常: {e}")
    return None

async def _call_api(session, token, method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    start = time.time()
    try:
        if method == "GET":
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return {"status": resp.status, "time": elapsed, "success": 200 <= resp.status < 400, "endpoint": path}
        elif method == "POST":
            async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return {"status": resp.status, "time": elapsed, "success": 200 <= resp.status < 400, "endpoint": path}
        elif method == "PUT":
            async with session.put(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return {"status": resp.status, "time": elapsed, "success": 200 <= resp.status < 400, "endpoint": path}
        elif method == "DELETE":
            async with session.delete(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return {"status": resp.status, "time": elapsed, "success": 200 <= resp.status < 400, "endpoint": path}
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {"status": 0, "time": elapsed, "success": False, "error": str(e), "endpoint": path}
    return {"status": 0, "time": 0, "success": False, "endpoint": path}

async def worker(worker_id, stop_event):
    async with aiohttp.ClientSession() as session:
        token = await get_token(session)
        if not token:
            print(f"Worker {worker_id}: 认证失败")
            return

        print(f"Worker {worker_id}: 认证成功")

        endpoints = [
            ("GET", "/api/v1/orders/list", None),
            ("GET", "/api/v1/products/list", None),
            ("GET", "/api/v1/customers/list", None),
            ("GET", "/api/v1/stock/inventory", None),
            ("POST", "/api/v1/orders/create", {"order_no": f"STRESS-{worker_id}-{int(time.time())}", "customer_id": 1, "product_id": 1, "quantity": 10, "price": 100}),
            ("POST", "/api/v1/products/create", {"name": f"测试产品-{worker_id}", "barcode": f"TEST{worker_id}{int(time.time())}", "price": 50}),
        ]

        count = 0
        while not stop_event.is_set():
            for method, path, data in endpoints:
                if stop_event.is_set():
                    break
                result = await _call_api(session, token, method, path, data)
                results.append(result)
                count += 1
                await asyncio.sleep(0.1)

async def print_progress(start_time, stop_event):
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        progress = min(100, (elapsed / DURATION_SECONDS) * 100)

        if results:
            total = len(results)
            success = sum(1 for r in results if r.get("success"))
            recent = results[-100:] if len(results) >= 100 else results
            avg_time = statistics.mean([r.get("time", 0) for r in recent])

            print(f"[{elapsed/60:.1f}/{DURATION_SECONDS/60:.0f}min] 进度: {progress:.1f}% | 请求: {total} | 成功: {success} | 失败: {total-success} | 近100次平均: {avg_time:.0f}ms")
        else:
            print(f"[{elapsed/60:.1f}/{DURATION_SECONDS/60:.0f}min] 进度: {progress:.1f}% | 请求: 0")

        await asyncio.sleep(10)

async def main():
    print("=" * 80)
    print("ERP系统压力测试")
    print("=" * 80)
    print(f"并发用户: {CONCURRENT_USERS}")
    print(f"测试时长: {DURATION_SECONDS/60:.0f} 分钟")
    print(f"目标服务器: {BASE_URL}")
    print("=" * 80)

    stop_event = asyncio.Event()
    start_time = time.time()

    # 创建worker任务
    workers = [asyncio.create_task(worker(i, stop_event)) for i in range(CONCURRENT_USERS)]

    # 创建进度打印任务
    progress_task = asyncio.create_task(print_progress(start_time, stop_event))

    # 运行指定时间
    await asyncio.sleep(DURATION_SECONDS)

    # 停止所有worker
    stop_event.set()

    # 等待所有任务完成
    for w in workers:
        w.cancel()
    progress_task.cancel()

    await asyncio.gather(*workers, return_exceptions=True)
    await asyncio.gather(progress_task, return_exceptions=True)

    # 统计分析
    print("\n" + "=" * 80)
    print("测试结果")
    print("=" * 80)

    if results:
        total = len(results)
        success = sum(1 for r in results if r.get("success"))
        failures = total - success

        response_times = [r.get("time", 0) for r in results]
        sorted_times = sorted(response_times)

        print(f"总请求数: {total}")
        print(f"成功: {success} ({success/total*100:.1f}%)")
        print(f"失败: {failures} ({failures/total*100:.1f}%)")
        print(f"吞吐量: {total/DURATION_SECONDS:.2f} req/s")
        print("\n响应时间:")
        print(f"  平均: {statistics.mean(response_times):.1f}ms")
        print(f"  最小: {min(response_times):.1f}ms")
        print(f"  最大: {max(response_times):.1f}ms")
        print(f"  P50: {sorted_times[len(sorted_times)//2]:.1f}ms")
        print(f"  P90: {sorted_times[int(len(sorted_times)*0.9)]:.1f}ms")
        print(f"  P95: {sorted_times[int(len(sorted_times)*0.95)]:.1f}ms")
        print(f"  P99: {sorted_times[int(len(sorted_times)*0.99)]:.1f}ms")

        # 按状态码统计
        status_counts = {}
        for r in results:
            s = r.get("status", 0)
            status_counts[s] = status_counts.get(s, 0) + 1
        print("\n状态码分布:")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count} ({count/total*100:.1f}%)")

        # 按端点统计
        endpoint_stats = {}
        for r in results:
            ep = r.get("endpoint", "unknown")
            if ep not in endpoint_stats:
                endpoint_stats[ep] = {"total": 0, "success": 0, "times": []}
            endpoint_stats[ep]["total"] += 1
            if r.get("success"):
                endpoint_stats[ep]["success"] += 1
            endpoint_stats[ep]["times"].append(r.get("time", 0))

        print("\n端点性能:")
        for ep, stats in endpoint_stats.items():
            avg = statistics.mean(stats["times"])
            print(f"  {ep}: {stats['success']}/{stats['total']} 成功, 平均 {avg:.1f}ms")
    else:
        print("没有收集到结果")

    if errors:
        print("\n错误信息 (前10个):")
        for err in errors[:10]:
            print(f"  - {err}")

    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

if __name__ == "__main__":
    require_non_production(BASE_URL)  # fail-closed 守卫（F-TEST-BE-TOP-02）
    asyncio.run(main())
