"""
ERP系统压力测试 - 稳定运行版
"""
import asyncio
import statistics
import time

import aiohttp

BASE_URL = "http://127.0.0.1:5002"

async def get_token():
    """获取认证token"""
    try:
        async with aiohttp.ClientSession() as session, session.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("access_token")
    except Exception as e:
        print(f"获取token失败: {e}")
    return None

async def run_stress_test(users, duration_seconds, phase_name):
    """运行压力测试"""
    print(f"\n{'='*60}")
    print(f"开始 {phase_name}")
    print(f"并发: {users}, 时长: {duration_seconds/60:.0f}分钟")
    print(f"{'='*60}")

    token = await get_token()
    if not token:
        print("获取token失败")
        return None

    results = []
    stop_event = asyncio.Event()
    start_time = time.time()

    async def worker(worker_id):
        endpoints = ["/api/v1/orders/list", "/api/v1/products/list", "/api/v1/stock/inventory"]
        headers = {"Authorization": f"Bearer {token}"}
        connector = aiohttp.TCPConnector(limit=5, ttl_dns_cache=300)

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                count = 0
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
                        except Exception:
                            results.append({"status": 0, "time": 0, "success": False})
                        await asyncio.sleep(0.3)
                return count
        except Exception as e:
            print(f"Worker {worker_id} 异常: {e}")
            return 0

    # 创建workers
    tasks = [asyncio.create_task(worker(i)) for i in range(users)]

    print("测试开始...")
    last_count = 0

    # 进度监控
    while time.time() - start_time < duration_seconds:
        await asyncio.sleep(30)
        elapsed = time.time() - start_time
        total = len(results)
        success = sum(1 for r in results if r.get("success"))
        rps = (total - last_count) / 30
        last_count = total
        print(f"  [{elapsed/60:.1f}min] 请求: {total}, 成功: {success}, 失败: {total-success}, RPS: {rps:.1f}")

    print("\n停止测试...")
    stop_event.set()

    # 等待workers完成
    await asyncio.gather(*tasks, return_exceptions=True)

    # 统计结果
    total = len(results)
    if total == 0:
        print("无结果")
        return None

    success = sum(1 for r in results if r["success"])
    times = [r["time"] for r in results if r["time"] > 0]
    sorted_times = sorted(times) if times else [0]

    print(f"\n{'='*60}")
    print(f"{phase_name} 结果")
    print(f"{'='*60}")
    print(f"总请求: {total}")
    print(f"成功: {success} ({success/total*100:.1f}%)")
    print(f"失败: {total - success}")
    print(f"吞吐量: {total/duration_seconds:.1f} req/s")
    if times:
        print(f"平均响应: {statistics.mean(times):.0f}ms")
        print(f"P50: {sorted_times[len(sorted_times)//2]:.0f}ms")
        print(f"P90: {sorted_times[int(len(sorted_times)*0.9)]:.0f}ms")
        print(f"P95: {sorted_times[int(len(sorted_times)*0.95)]:.0f}ms")
    print(f"{'='*60}")

    return {
        "name": phase_name,
        "users": users,
        "duration": duration_seconds,
        "total": total,
        "success": success,
        "failed": total - success,
        "success_rate": success/total*100,
        "throughput": total/duration_seconds,
        "avg_time": statistics.mean(times) if times else 0,
        "p50": sorted_times[len(sorted_times)//2] if times else 0,
        "p90": sorted_times[int(len(sorted_times)*0.9)] if times else 0,
        "p95": sorted_times[int(len(sorted_times)*0.95)] if times else 0,
    }

async def main():
    print("=" * 60)
    print("ERP系统分阶段压力测试")
    print("=" * 60)

    # 检查服务器
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/api/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    print(f"服务器异常: {resp.status}")
                    return
                print("服务器状态: 正常")
    except Exception as e:
        print(f"无法连接服务器: {e}")
        return

    phase_results = []

    # 阶段1: 5分钟/20并发
    result1 = await run_stress_test(20, 300, "阶段1: 低负载 (20并发/5分钟)")
    if result1:
        phase_results.append(result1)

    # 休息
    print("\n休息30秒...")
    await asyncio.sleep(30)

    # 阶段2: 10分钟/30并发
    result2 = await run_stress_test(30, 600, "阶段2: 中负载 (30并发/10分钟)")
    if result2:
        phase_results.append(result2)

    # 休息
    print("\n休息30秒...")
    await asyncio.sleep(30)

    # 阶段3: 15分钟/50并发
    result3 = await run_stress_test(50, 900, "阶段3: 高负载 (50并发/15分钟)")
    if result3:
        phase_results.append(result3)

    # 总报告
    print(f"\n{'='*60}")
    print("总体测试结果")
    print(f"{'='*60}")

    if phase_results:
        total_all = sum(p["total"] for p in phase_results)
        success_all = sum(p["success"] for p in phase_results)

        print(f"总请求数: {total_all}")
        print(f"总成功: {success_all} ({success_all/total_all*100:.1f}%)" if total_all > 0 else "总成功: 0")
        print(f"总失败: {total_all - success_all}")

        print("\n各阶段对比:")
        print(f"{'阶段':<30} {'并发':<6} {'请求':<8} {'成功率':<8} {'平均':<8} {'P95':<8}")
        print("-" * 70)
        for p in phase_results:
            print(f"{p['name']:<30} {p['users']:<6} {p['total']:<8} {p['success_rate']:<7.1f}% {p['avg_time']:<7.0f}ms {p['p95']:<7.0f}ms")

    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n测试被中断")
    except Exception as e:
        print(f"\n异常: {e}")
        import traceback
        traceback.print_exc()
