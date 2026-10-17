"""
ERP系统分阶段压力测试
阶段1: 5分钟/20并发
阶段2: 10分钟/30并发
阶段3: 15分钟/50并发
"""
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from _prod_guard import require_non_production
import asyncio
import statistics
import time
from datetime import datetime

import aiohttp

BASE_URL = "http://127.0.0.1:5002"

# 阶段配置
PHASES = [
    {"name": "阶段1: 低负载", "users": 20, "duration": 300},  # 5分钟
    {"name": "阶段2: 中负载", "users": 30, "duration": 600},  # 10分钟
    {"name": "阶段3: 高负载", "users": 50, "duration": 900},  # 15分钟
]

all_results = {"phases": []}

async def get_token():
    """获取认证token"""
    for i in range(3):
        try:
            async with aiohttp.ClientSession() as session, session.post(
                f"{BASE_URL}/api/v1/auth/login",
                json={"username": "admin", "password": "admin123"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("access_token")
        except Exception as e:
            print(f"  登录尝试 {i+1} 失败: {e}")
            await asyncio.sleep(2)
    return None

async def make_request(session, token, endpoint):
    """执行单个请求"""
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    try:
        async with session.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            elapsed = (time.time() - start) * 1000
            success = 200 <= resp.status < 400
            return {"status": resp.status, "time": elapsed, "success": success, "endpoint": endpoint}
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return {"status": 0, "time": elapsed, "success": False, "error": str(e), "endpoint": endpoint}

async def worker(worker_id, token, stop_event, session, results):
    """Worker协程"""
    endpoints = ["/api/v1/orders/list", "/api/v1/products/list", "/api/v1/stock/inventory"]

    while not stop_event.is_set():
        for ep in endpoints:
            if stop_event.is_set():
                break
            try:
                r = await make_request(session, token, ep)
                results.append(r)
            except Exception:  # noqa: S110
                pass
            await asyncio.sleep(0.3)

async def run_phase(phase_config):
    """运行单个阶段"""
    name = phase_config["name"]
    users = phase_config["users"]
    duration = phase_config["duration"]

    print(f"\n{'='*60}")
    print(f"开始 {name}")
    print(f"并发: {users}, 时长: {duration/60:.0f}分钟")
    print(f"{'='*60}")

    # 获取token
    print("获取token...")
    token = await get_token()
    if not token:
        print("获取token失败，跳过此阶段")
        return {"name": name, "success": False, "results": []}
    print("Token获取成功")

    results = []
    stop_event = asyncio.Event()
    start_time = time.time()

    # 创建连接池和session
    connector = aiohttp.TCPConnector(limit=users * 2, ttl_dns_cache=300, keepalive_timeout=30)
    async with aiohttp.ClientSession(connector=connector) as session:
        # 创建workers
        tasks = []
        for i in range(users):
            task = asyncio.create_task(worker(i, token, stop_event, session, results))
            tasks.append(task)

        # 进度监控
        last_count = 0
        print("测试开始...")
        while time.time() - start_time < duration:
            await asyncio.sleep(30)
            elapsed = time.time() - start_time
            total = len(results)
            success = sum(1 for r in results if r.get("success"))
            rps = (total - last_count) / 30 if total > last_count else 0
            last_count = total
            print(f"  [{elapsed/60:.1f}min/{duration/60:.0f}min] 请求: {total}, 成功: {success}, 失败: {total-success}, RPS: {rps:.1f}")

        # 停止测试
        print("\n停止workers...")
        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    # 统计阶段结果
    total = len(results)
    success = sum(1 for r in results if r["success"])
    times = [r["time"] for r in results if r["time"] > 0]

    phase_result = {
        "name": name,
        "users": users,
        "duration_seconds": duration,
        "total_requests": total,
        "successful_requests": success,
        "failed_requests": total - success,
        "success_rate": success/total*100 if total > 0 else 0,
        "throughput": total/duration if duration > 0 else 0,
        "avg_response_time": statistics.mean(times) if times else 0,
        "p50_response_time": sorted(times)[len(times)//2] if times else 0,
        "p90_response_time": sorted(times)[int(len(times)*0.9)] if times else 0,
        "p95_response_time": sorted(times)[int(len(times)*0.95)] if times else 0,
        "results": results
    }

    print(f"\n{'='*60}")
    print(f"{name} 结果")
    print(f"{'='*60}")
    print(f"总请求: {total}")
    print(f"成功: {success} ({phase_result['success_rate']:.1f}%)")
    print(f"失败: {total - success}")
    print(f"吞吐量: {phase_result['throughput']:.1f} req/s")
    if times:
        print(f"平均响应: {phase_result['avg_response_time']:.0f}ms")
        print(f"P50: {phase_result['p50_response_time']:.0f}ms")
        print(f"P90: {phase_result['p90_response_time']:.0f}ms")
        print(f"P95: {phase_result['p95_response_time']:.0f}ms")
    print(f"{'='*60}")

    return phase_result

async def main():
    print("=" * 60)
    print("ERP系统分阶段压力测试")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 检查服务器
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/api/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    print(f"服务器状态异常: {resp.status}")
                    return
                print("服务器状态: 正常")
    except Exception as e:
        print(f"无法连接服务器: {e}")
        return

    # 运行各阶段
    for phase in PHASES:
        result = await run_phase(phase)
        all_results["phases"].append(result)

        # 阶段间休息
        if phase != PHASES[-1]:
            print("\n休息30秒后进入下一阶段...")
            await asyncio.sleep(30)

    # 生成总报告
    print(f"\n{'='*60}")
    print("总体测试结果")
    print(f"{'='*60}")

    total_all = sum(p["total_requests"] for p in all_results["phases"])
    success_all = sum(p["successful_requests"] for p in all_results["phases"])

    print(f"总请求数: {total_all}")
    print(f"总成功: {success_all} ({success_all/total_all*100:.1f}%)" if total_all > 0 else "总成功: 0")
    print(f"总失败: {total_all - success_all}")

    # 各阶段对比
    print("\n各阶段对比:")
    print(f"{'阶段':<20} {'并发':<6} {'请求数':<10} {'成功率':<10} {'平均响应':<10} {'吞吐量':<10}")
    print("-" * 70)
    for p in all_results["phases"]:
        print(f"{p['name']:<20} {p['users']:<6} {p['total_requests']:<10} {p['success_rate']:<9.1f}% {p['avg_response_time']:<9.0f}ms {p['throughput']:<9.1f}req/s")

    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")

if __name__ == "__main__":
    require_non_production(BASE_URL)  # fail-closed 守卫（F-TEST-BE-TOP-02）
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n测试被用户中断")
    except Exception as e:
        print(f"\n测试异常: {e}")
        import traceback
        traceback.print_exc()
