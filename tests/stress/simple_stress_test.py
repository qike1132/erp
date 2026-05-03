"""
ERP系统简化压力测试 - 直接测试API可用性
"""

import asyncio
import statistics
import time
from dataclasses import dataclass

import aiohttp

BASE_URL = "http://127.0.0.1:5002"
CONCURRENT_USERS = 10  # 减少到10个并发
DURATION_SECONDS = 30   # 30秒快速测试

@dataclass
class Metric:
    status: int
    response_time: float
    success: bool
    error: str = ""


async def get_token(session: aiohttp.ClientSession) -> str | None:
    """获取认证token"""
    try:
        async with session.post(
            f"{BASE_URL}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("access_token")
    except Exception as e:
        print(f"认证错误: {e}")
    return None


async def test_endpoint(session: aiohttp.ClientSession, token: str, method: str, path: str, json_data: dict | None = None) -> Metric:
    """测试单个端点"""
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    start = time.time()
    try:
        if method == "GET":
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return Metric(status=resp.status, response_time=elapsed, success=200 <= resp.status < 400)
        elif method == "POST":
            async with session.post(url, headers=headers, json=json_data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return Metric(status=resp.status, response_time=elapsed, success=200 <= resp.status < 400)
        elif method == "PUT":
            async with session.put(url, headers=headers, json=json_data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                elapsed = (time.time() - start) * 1000
                return Metric(status=resp.status, response_time=elapsed, success=200 <= resp.status < 400)
    except Exception as e:
        elapsed = (time.time() - start) * 1000
        return Metric(status=0, response_time=elapsed, success=False, error=str(e))

    return Metric(status=0, response_time=0, success=False, error="Unknown method")


async def user_worker(worker_id: int, results: list[Metric], stop_event: asyncio.Event):
    """用户工作协程"""
    async with aiohttp.ClientSession() as session:
        token = await get_token(session)
        if not token:
            print(f"Worker {worker_id}: 认证失败，跳过")
            return

        print(f"Worker {worker_id}: 认证成功，开始测试")

        endpoints = [
            ("GET", "/api/v1/orders", None),
            ("GET", "/api/v1/products", None),
            ("GET", "/api/v1/customers", None),
            ("GET", "/api/v1/stock/inventory", None),
            ("POST", "/api/v1/orders", {"order_no": "TEST-001", "customer_id": 1, "product_id": 1, "quantity": 10, "price": 100}),
            ("POST", "/api/v1/products", {"name": "测试产品", "barcode": "TEST123", "price": 50}),
        ]

        while not stop_event.is_set():
            for method, path, data in endpoints:
                metric = await test_endpoint(session, token, method, path, data)
                results.append(metric)
                await asyncio.sleep(0.1)  # 短暂延迟


async def main():
    print("=" * 60)
    print("ERP压力测试开始")
    print("=" * 60)

    results: list[Metric] = []
    stop_event = asyncio.Event()

    # 创建worker任务
    tasks = [asyncio.create_task(user_worker(i, results, stop_event)) for i in range(CONCURRENT_USERS)]

    # 运行指定时间
    print(f"运行 {DURATION_SECONDS} 秒...")
    await asyncio.sleep(DURATION_SECONDS)

    # 停止所有worker
    stop_event.set()
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    # 统计分析
    print("\n" + "=" * 60)
    print("测试结果")
    print("=" * 60)

    if not results:
        print("没有收集到任何结果!")
        return

    total = len(results)
    successes = sum(1 for r in results if r.success)
    failures = total - successes

    response_times = [r.response_time for r in results]
    sorted_times = sorted(response_times)

    print(f"总请求数: {total}")
    print(f"成功: {successes} ({successes/total*100:.1f}%)")
    print(f"失败: {failures} ({failures/total*100:.1f}%)")
    print("\n响应时间:")
    print(f"  平均: {statistics.mean(response_times):.1f}ms")
    print(f"  最小: {min(response_times):.1f}ms")
    print(f"  最大: {max(response_times):.1f}ms")
    print(f"  P50: {sorted_times[len(sorted_times)//2]:.1f}ms")
    print(f"  P90: {sorted_times[int(len(sorted_times)*0.9)]:.1f}ms")

    # 按状态码统计
    status_counts: dict[int, int] = {}
    for r in results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1

    print("\n状态码分布:")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")

    # 错误信息
    errors = [r.error for r in results if r.error]
    if errors:
        print("\n错误信息 (前5个):")
        for err in errors[:5]:
            print(f"  - {err[:100]}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
