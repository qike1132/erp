"""
ERP系统压力测试 - 真实运行版
"""
import asyncio
import aiohttp
import time
import statistics
import sys

BASE_URL = "http://127.0.0.1:5002"
USERS = 20
DURATION = 60  # 1分钟

results = []

async def main():
    print(f"测试: {USERS}并发, {DURATION}秒")
    
    # 获取token
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{BASE_URL}/api/v1/auth/login", 
                               json={"username": "admin", "password": "admin123"}) as resp:
            token = (await resp.json())["access_token"]
    
    stop = asyncio.Event()
    start = time.time()
    
    async def worker():
        headers = {"Authorization": f"Bearer {token}"}
        connector = aiohttp.TCPConnector(limit=5)
        async with aiohttp.ClientSession(connector=connector) as session:
            while not stop.is_set():
                for ep in ["/api/v1/orders/list", "/api/v1/products/list"]:
                    try:
                        s = time.time()
                        async with session.get(f"{BASE_URL}{ep}", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as r:
                            results.append({"s": r.status, "t": (time.time()-s)*1000, "ok": 200<=r.status<400})
                    except Exception as e:
                        results.append({"s": 0, "t": 0, "ok": False, "e": str(e)})
                    await asyncio.sleep(0.5)
    
    tasks = [asyncio.create_task(worker()) for _ in range(USERS)]
    
    # 进度
    while time.time() - start < DURATION:
        await asyncio.sleep(10)
        total = len(results)
        ok = sum(1 for r in results if r["ok"])
        print(f"[{(time.time()-start):.0f}s] 请求:{total} 成功:{ok} 失败:{total-ok}")
    
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
    
    # 结果
    total = len(results)
    ok = sum(1 for r in results if r["ok"])
    times = [r["t"] for r in results if r["t"]>0]
    
    print(f"\n结果: 总{total} 成功{ok}({ok/total*100:.1f}%) 失败{total-ok}")
    if times:
        print(f"响应: 平均{statistics.mean(times):.0f}ms P95{sorted(times)[int(len(times)*0.95)]:.0f}ms")

if __name__ == "__main__":
    asyncio.run(main())
