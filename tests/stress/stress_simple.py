"""
ERP系统压力测试 - 可靠版
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
CONCURRENT_USERS = 50
DURATION_SECONDS = 1800  # 30分钟

results = []

async def get_token():
    async with aiohttp.ClientSession() as session, session.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"}
    ) as resp:
        data = await resp.json()
        return data.get("access_token")

async def make_request(session, token, endpoint):
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    try:
        async with session.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            elapsed = (time.time() - start) * 1000
            return {"status": resp.status, "time": elapsed, "success": 200 <= resp.status < 400, "endpoint": endpoint}
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {"status": 0, "time": elapsed, "success": False, "error": str(e), "endpoint": endpoint}

async def worker(worker_id, token, stop_event):
    endpoints = ["/api/v1/orders/list", "/api/v1/products/list", "/api/v1/stock/inventory"]
    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(connector=connector) as session:
        while not stop_event.is_set():
            for ep in endpoints:
                if stop_event.is_set():
                    break
                r = await make_request(session, token, ep)
                results.append(r)
                await asyncio.sleep(0.1)

async def main():
    print("获取token...")
    token = await get_token()
    print(f"Token: {token[:30]}...")

    stop_event = asyncio.Event()
    start_time = time.time()

    workers = [asyncio.create_task(worker(i, token, stop_event)) for i in range(CONCURRENT_USERS)]

    while time.time() - start_time < DURATION_SECONDS:
        elapsed = time.time() - start_time
        total = len(results)
        success = sum(1 for r in results if r.get("success"))
        print(f"[{elapsed:.0f}s] 请求: {total}, 成功: {success}, 失败: {total-success}")
        await asyncio.sleep(5)

    stop_event.set()
    await asyncio.gather(*workers, return_exceptions=True)

    # 结果
    total = len(results)
    if total == 0:
        print("无结果")
        return

    success = sum(1 for r in results if r["success"])
    times = [r["time"] for r in results]
    sorted_times = sorted(times)

    print("\n===== 测试结果 =====")
    print(f"总请求: {total}")
    print(f"成功率: {success/total*100:.1f}%")
    print(f"平均响应: {statistics.mean(times):.0f}ms")
    print(f"P50: {sorted_times[len(sorted_times)//2]:.0f}ms")
    print(f"P90: {sorted_times[int(len(sorted_times)*0.9)]:.0f}ms")
    print(f"P95: {sorted_times[int(len(sorted_times)*0.95)]:.0f}ms")

    # 状态码
    status = {}
    for r in results:
        s = r["status"]
        status[s] = status.get(s, 0) + 1
    print(f"状态码: {status}")

    # 端点
    ep = {}
    for r in results:
        e = r["endpoint"]
        if e not in ep:
            ep[e] = {"total": 0, "success": 0}
        ep[e]["total"] += 1
        if r["success"]:
            ep[e]["success"] += 1
    print("\n端点结果:")
    for e, s in ep.items():
        print(f"  {e}: {s['success']}/{s['total']}")

if __name__ == "__main__":
    require_non_production(BASE_URL)  # fail-closed 守卫（F-TEST-BE-TOP-02）
    asyncio.run(main())
