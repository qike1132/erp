"""
ERP系统压力测试 - 稳定版（50并发/30分钟）
"""
import asyncio
import statistics
import sys
import time

import aiohttp

BASE_URL = "http://127.0.0.1:5002"
CONCURRENT_USERS = 50
DURATION_SECONDS = 1800  # 30分钟

results = []

async def get_token():
    for i in range(3):
        try:
            async with aiohttp.ClientSession() as session, session.post(
                f"{BASE_URL}/api/v1/auth/login",
                json={"username": "admin", "password": "admin123"}
            ) as resp:
                data = await resp.json()
                return data.get("access_token")
        except Exception as e:
            print(f"登录尝试 {i+1} 失败: {e}")
            await asyncio.sleep(2)
    return None

async def make_request(session, token, endpoint):
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    try:
        async with session.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            elapsed = (time.time() - start) * 1000
            success = 200 <= resp.status < 400
            results.append({"status": resp.status, "time": elapsed, "success": success, "endpoint": endpoint})
            return success
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        results.append({"status": 0, "time": elapsed, "success": False, "error": str(e), "endpoint": endpoint})
        return False

async def worker(worker_id, token, stop_event):
    endpoints = ["/api/v1/orders/list", "/api/v1/products/list", "/api/v1/stock/inventory"]

    try:
        connector = aiohttp.TCPConnector(limit=5, ttl_dns_cache=300, keepalive_timeout=30)
        async with aiohttp.ClientSession(connector=connector) as session:
            while not stop_event.is_set():
                for ep in endpoints:
                    if stop_event.is_set():
                        break
                    try:
                        success = await make_request(session, token, ep)
                        if not success:
                            # 如果认证失败，尝试重新获取token
                            await asyncio.sleep(1)
                    except Exception as e:
                        print(f"Worker {worker_id} 请求异常: {e}")
                        await asyncio.sleep(1)
                    await asyncio.sleep(0.3)
    except Exception as e:
        print(f"Worker {worker_id} 会话异常: {e}")

async def print_progress(start_time, stop_event):
    last_count = 0
    try:
        while not stop_event.is_set():
            await asyncio.sleep(30)
            total = len(results)
            success = sum(1 for r in results if r.get("success"))
            elapsed = time.time() - start_time
            rps = (total - last_count) / 30 if total > last_count else 0
            last_count = total
            print(f"[{elapsed/60:.1f}min/{DURATION_SECONDS/60:.0f}min] 请求: {total}, 成功: {success}, 失败: {total-success}, RPS: {rps:.1f}")
    except asyncio.CancelledError:
        pass

async def main():
    print("=" * 60)
    print("ERP系统压力测试 - 30分钟")
    print(f"并发: {CONCURRENT_USERS}, 时长: {DURATION_SECONDS/60:.0f}分钟")
    print("=" * 60)

    print("获取token...")
    token = await get_token()
    if not token:
        print("获取token失败，退出")
        return
    print("Token获取成功")

    stop_event = asyncio.Event()
    start_time = time.time()

    # 创建workers
    workers = []
    for i in range(CONCURRENT_USERS):
        task = asyncio.create_task(worker(i, token, stop_event))
        workers.append(task)

    progress = asyncio.create_task(print_progress(start_time, stop_event))

    print(f"测试开始，运行 {DURATION_SECONDS/60:.0f} 分钟...")

    try:
        # 等待指定时间
        await asyncio.sleep(DURATION_SECONDS)
    except KeyboardInterrupt:
        print("\n用户中断测试")

    print("\n测试时间到，停止workers...")
    stop_event.set()

    # 等待所有workers完成
    await asyncio.gather(*workers, return_exceptions=True)
    progress.cancel()

    # 统计结果
    total = len(results)
    if total == 0:
        print("无结果")
        return

    success = sum(1 for r in results if r["success"])
    times = [r["time"] for r in results]
    sorted_times = sorted(times)

    print("\n" + "=" * 60)
    print("测试结果")
    print("=" * 60)
    print(f"总请求: {total}")
    print(f"成功: {success} ({success/total*100:.1f}%)")
    print(f"失败: {total - success} ({(total-success)/total*100:.1f}%)")
    print(f"吞吐量: {total/DURATION_SECONDS:.1f} req/s")
    print("\n响应时间:")
    print(f"  平均: {statistics.mean(times):.0f}ms")
    print(f"  中位数: {statistics.median(times):.0f}ms")
    if sorted_times:
        print(f"  P50: {sorted_times[len(sorted_times)//2]:.0f}ms")
        print(f"  P90: {sorted_times[int(len(sorted_times)*0.9)]:.0f}ms")
        print(f"  P95: {sorted_times[int(len(sorted_times)*0.95)]:.0f}ms")
        print(f"  P99: {sorted_times[min(int(len(sorted_times)*0.99), len(sorted_times)-1)]:.0f}ms")

    # 状态码
    status = {}
    for r in results:
        s = r["status"]
        status[s] = status.get(s, 0) + 1
    print("\n状态码分布:")
    for s, c in sorted(status.items()):
        print(f"  {s}: {c} ({c/total*100:.1f}%)")

    # 端点
    ep = {}
    for r in results:
        e = r["endpoint"]
        if e not in ep:
            ep[e] = {"total": 0, "success": 0, "times": []}
        ep[e]["total"] += 1
        if r["success"]:
            ep[e]["success"] += 1
        ep[e]["times"].append(r["time"])

    print("\n端点性能:")
    for e, s in ep.items():
        avg = statistics.mean(s["times"]) if s["times"] else 0
        print(f"  {e}: {s['success']}/{s['total']} 成功, 平均 {avg:.0f}ms")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试异常: {e}")
        sys.exit(1)
