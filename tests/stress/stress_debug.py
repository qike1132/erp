"""
ERP系统压力测试 - 调试版
"""
import asyncio
import aiohttp
import time
import sys

BASE_URL = "http://127.0.0.1:5002"
CONCURRENT_USERS = 10  # 减少到10个测试
DURATION_SECONDS = 120  # 2分钟

results = []

async def get_token():
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"}
        ) as resp:
            data = await resp.json()
            return data.get("access_token")

async def worker(worker_id, token, stop_event, session):
    endpoints = ["/api/v1/orders/list", "/api/v1/products/list"]
    headers = {"Authorization": f"Bearer {token}"}
    
    print(f"Worker {worker_id} 启动")
    count = 0
    try:
        while not stop_event.is_set():
            for ep in endpoints:
                if stop_event.is_set():
                    break
                try:
                    start = time.time()
                    async with session.get(f"{BASE_URL}{ep}", headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        elapsed = (time.time() - start) * 1000
                        success = 200 <= resp.status < 400
                        results.append({"status": resp.status, "time": elapsed, "success": success})
                        count += 1
                except Exception as e:
                    print(f"Worker {worker_id} 错误: {e}")
                    results.append({"status": 0, "time": 0, "success": False})
                await asyncio.sleep(0.5)
    except Exception as e:
        print(f"Worker {worker_id} 异常: {e}")
    print(f"Worker {worker_id} 完成，执行 {count} 次请求")

async def main():
    print("=" * 60)
    print(f"测试: {CONCURRENT_USERS} 并发, {DURATION_SECONDS} 秒")
    print("=" * 60)
    
    print("获取token...")
    token = await get_token()
    print(f"Token: {token[:30]}...")
    
    stop_event = asyncio.Event()
    start_time = time.time()
    
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(connector=connector) as session:
        workers = []
        for i in range(CONCURRENT_USERS):
            task = asyncio.create_task(worker(i, token, stop_event, session))
            workers.append(task)
        
        print(f"测试开始...")
        
        # 每5秒打印进度
        while time.time() - start_time < DURATION_SECONDS:
            await asyncio.sleep(5)
            elapsed = time.time() - start_time
            total = len(results)
            success = sum(1 for r in results if r.get("success"))
            print(f"[{elapsed:.0f}s] 请求: {total}, 成功: {success}")
        
        print(f"\n时间到，停止测试...")
        stop_event.set()
        
        # 等待workers完成
        await asyncio.gather(*workers, return_exceptions=True)
    
    # 结果
    print(f"\n{'='*60}")
    print(f"测试结果")
    print(f"{'='*60}")
    total = len(results)
    success = sum(1 for r in results if r["success"])
    times = [r["time"] for r in results if r["time"] > 0]
    
    print(f"总请求: {total}")
    print(f"成功: {success} ({success/total*100:.1f}%)")
    print(f"失败: {total - success}")
    if times:
        print(f"平均响应: {sum(times)/len(times):.0f}ms")
    print(f"测试时长: {total/DURATION_SECONDS:.1f} req/s")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n用户中断")
    except Exception as e:
        print(f"\n异常: {e}")
        import traceback
        traceback.print_exc()
