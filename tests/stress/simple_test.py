"""
ERP系统压力测试 - 极简版
"""
import asyncio
import aiohttp
import time
import statistics
from datetime import datetime

BASE_URL = "http://127.0.0.1:5002"
CONCURRENT_USERS = 50
DURATION_SECONDS = 60  # 1分钟测试

results = []

async def worker(worker_id, token, stop_event):
    endpoints = [
        ("GET", "/api/v1/orders/list"),
        ("GET", "/api/v1/products/list"),
        ("GET", "/api/v1/customers/list"),
        ("GET", "/api/v1/stock/inventory"),
    ]
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    connector = aiohttp.TCPConnector(limit=10)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        while not stop_event.is_set():
            for method, path in endpoints:
                if stop_event.is_set():
                    break
                try:
                    start = time.time()
                    async with session.get(f"{BASE_URL}{path}", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        elapsed = (time.time() - start) * 1000
                        success = 200 <= resp.status < 400
                        results.append({"status": resp.status, "time": elapsed, "success": success, "endpoint": path})
                except Exception as e:
                    elapsed = (time.time() - start) * 1000
                    results.append({"status": 0, "time": elapsed, "success": False, "error": str(e), "endpoint": path})
                await asyncio.sleep(0.2)

async def main():
    print("=" * 60)
    print("ERP压力测试")
    print(f"并发: {CONCURRENT_USERS}, 时长: {DURATION_SECONDS}秒")
    print("=" * 60)
    
    # 获取token
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{BASE_URL}/api/v1/auth/login", json={"username": "admin", "password": "admin123"}) as resp:
            if resp.status != 200:
                print(f"登录失败: {resp.status}")
                return
            token = (await resp.json())["access_token"]
            print(f"Token: {token[:30]}...")
    
    stop_event = asyncio.Event()
    start_time = time.time()
    
    # 创建workers
    tasks = [asyncio.create_task(worker(i, token, stop_event)) for i in range(CONCURRENT_USERS)]
    
    # 进度显示
    while not stop_event.is_set():
        elapsed = time.time() - start_time
        if elapsed >= DURATION_SECONDS:
            stop_event.set()
            break
        
        if results:
            total = len(results)
            success = sum(1 for r in results if r["success"])
            recent = results[-50:] if len(results) >= 50 else results
            avg_time = statistics.mean([r["time"] for r in recent])
            print(f"[{elapsed:.0f}/{DURATION_SECONDS}s] 请求: {total} | 成功: {success} | 失败: {total-success} | 平均: {avg_time:.0f}ms")
        
        await asyncio.sleep(5)
    
    # 等待完成
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # 统计
    print("\n" + "=" * 60)
    print("测试结果")
    print("=" * 60)
    
    if results:
        total = len(results)
        success = sum(1 for r in results if r["success"])
        response_times = [r["time"] for r in results]
        sorted_times = sorted(response_times)
        
        print(f"总请求: {total}")
        print(f"成功: {success} ({success/total*100:.1f}%)")
        print(f"失败: {total - success}")
        print(f"吞吐量: {total/DURATION_SECONDS:.1f} req/s")
        print(f"\n响应时间:")
        print(f"  平均: {statistics.mean(response_times):.0f}ms")
        print(f"  P50: {sorted_times[len(sorted_times)//2]:.0f}ms")
        print(f"  P90: {sorted_times[int(len(sorted_times)*0.9)]:.0f}ms")
        print(f"  P95: {sorted_times[int(len(sorted_times)*0.95)]:.0f}ms")
        print(f"  P99: {sorted_times[int(len(sorted_times)*0.99)]:.0f}ms")
        
        # 状态码统计
        status_counts = {}
        for r in results:
            s = r["status"]
            status_counts[s] = status_counts.get(s, 0) + 1
        print(f"\n状态码:")
        for s, c in sorted(status_counts.items()):
            print(f"  {s}: {c} ({c/total*100:.1f}%)")
        
        # 端点统计
        ep_stats = {}
        for r in results:
            ep = r["endpoint"]
            if ep not in ep_stats:
                ep_stats[ep] = {"total": 0, "success": 0, "times": []}
            ep_stats[ep]["total"] += 1
            if r["success"]:
                ep_stats[ep]["success"] += 1
            ep_stats[ep]["times"].append(r["time"])
        
        print(f"\n端点性能:")
        for ep, s in ep_stats.items():
            print(f"  {ep}: {s['success']}/{s['total']} 成功, 平均 {statistics.mean(s['times']):.0f}ms")
    else:
        print("无数据")

if __name__ == "__main__":
    asyncio.run(main())
