"""
ERP系统压力测试 - 简化版
测试API端点是否正常工作
"""

import asyncio
import aiohttp
import time
import os

BASE_URL = "http://127.0.0.1:5002"
CONCURRENT_USERS = 10
DURATION_SECONDS = 60

results = []

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
                print(f"登录失败: {resp.status}")
    except Exception as e:
        print(f"登录异常: {e}")
    return None

async def test_api(session, token, method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    start = time.time()
    try:
        if method == "GET":
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return {"status": resp.status, "time": elapsed, "success": 200 <= resp.status < 400}
        elif method == "POST":
            async with session.post(url, headers=headers, json=data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return {"status": resp.status, "time": elapsed, "success": 200 <= resp.status < 400}
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {"status": 0, "time": elapsed, "success": False, "error": str(e)}
    return {"status": 0, "time": 0, "success": False}

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
            ("POST", "/api/v1/orders/create", {"order_no": f"TEST-{int(time.time())}", "customer_id": 1, "product_id": 1, "quantity": 10, "price": 100}),
        ]
        
        count = 0
        while not stop_event.is_set() and count < 100:
            for method, path, data in endpoints:
                result = await test_api(session, token, method, path, data)
                results.append(result)
                count += 1
                await asyncio.sleep(0.1)

async def main():
    print("=" * 60)
    print(f"压力测试开始: {CONCURRENT_USERS} 并发用户, {DURATION_SECONDS} 秒")
    print("=" * 60)
    
    stop_event = asyncio.Event()
    
    workers = [asyncio.create_task(worker(i, stop_event)) for i in range(CONCURRENT_USERS)]
    
    await asyncio.sleep(DURATION_SECONDS)
    stop_event.set()
    
    for w in workers:
        w.cancel()
    
    await asyncio.gather(*workers, return_exceptions=True)
    
    if results:
        total = len(results)
        success = sum(1 for r in results if r.get("success"))
        avg_time = sum(r.get("time", 0) for r in results) / total
        
        print("\n" + "=" * 60)
        print("测试结果")
        print("=" * 60)
        print(f"总请求: {total}")
        print(f"成功: {success} ({success/total*100:.1f}%)")
        print(f"失败: {total - success}")
        print(f"平均响应时间: {avg_time:.1f}ms")
        
        status_counts = {}
        for r in results:
            s = r.get("status", 0)
            status_counts[s] = status_counts.get(s, 0) + 1
        print(f"状态码分布: {status_counts}")
    else:
        print("没有收集到结果")

if __name__ == "__main__":
    asyncio.run(main())
