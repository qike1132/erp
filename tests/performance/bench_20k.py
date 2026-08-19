"""
ERP系统性能基准测试 - 20K+ 数据量场景

测试核心操作的响应时间，验证优化效果。
目标：所有操作响应时间 < 200ms

运行方式：
  python -m tests.performance.bench_20k

环境要求：
  - PostgreSQL 数据库已启动
  - 数据库中已有 20K+ 条测试数据（或运行 python -m tests.qa.data_generator_v3_db 生成）
"""
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# ---- 配置 ----
API_BASE = os.getenv('API_BASE', 'http://127.0.0.1:5002/api/v1')
TARGET_LATENCY_MS = 200
ROUNDS = 5  # 每个测试运行的轮次


@dataclass
class BenchResult:
    name: str
    latencies_ms: list[float] = field(default_factory=list)
    success: bool = True
    error: str = ''

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0

    @property
    def p50_ms(self) -> float:
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0

    @property
    def p95_ms(self) -> float:
        if len(self.latencies_ms) < 2:
            return self.latencies_ms[0] if self.latencies_ms else 0
        sorted_l = sorted(self.latencies_ms)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]

    @property
    def max_ms(self) -> float:
        return max(self.latencies_ms) if self.latencies_ms else 0

    @property
    def min_ms(self) -> float:
        return min(self.latencies_ms) if self.latencies_ms else 0

    @property
    def passed(self) -> bool:
        return self.success and self.p95_ms <= TARGET_LATENCY_MS


async def _request(session, method: str, path: str, **kwargs):
    """发起 HTTP 请求并返回 (status_code, json_body, elapsed_ms)"""
    url = f'{API_BASE}{path}'
    start = time.perf_counter()
    async with session.request(method, url, **kwargs) as resp:
        body = await resp.json()
        elapsed = (time.perf_counter() - start) * 1000
    return resp.status, body, elapsed


async def bench_inventory_paginated(session, token: str) -> list[BenchResult]:
    """测试库存分页查询（核心优化点）"""
    results = []
    headers = {'Authorization': f'Bearer {token}'}

    # 1. 首页加载（缓存冷启动）
    r = BenchResult('库存首页(冷启动)')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/stock/inventory?page=1&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    # 2. 翻页（缓存命中）
    r = BenchResult('库存翻页(第5页)')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/stock/inventory?page=5&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    # 3. 客户筛选
    r = BenchResult('库存客户筛选')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/stock/inventory?customer=测试客户&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    # 4. 国家筛选（之前在Python层过滤，现在SQL层）
    r = BenchResult('库存国家筛选')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/stock/inventory?country=日本&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    return results


async def bench_order_list(session, token: str) -> list[BenchResult]:
    """测试订单列表"""
    results = []
    headers = {'Authorization': f'Bearer {token}'}

    r = BenchResult('订单首页')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/orders/list?page=1&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    r = BenchResult('订单翻页(第10页)')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/orders/list?page=10&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    return results


async def bench_stock_in_out(session, token: str) -> list[BenchResult]:
    """测试入库/出库列表"""
    results = []
    headers = {'Authorization': f'Bearer {token}'}

    r = BenchResult('入库列表首页')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/stock/in/list?page=1&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    r = BenchResult('出库列表首页')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/stock/out/list?page=1&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    return results


async def bench_case_endpoints(session, token: str) -> list[BenchResult]:
    """测试皮套相关接口"""
    results = []
    headers = {'Authorization': f'Bearer {token}'}

    r = BenchResult('皮套库存汇总')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/cases/inventory-summary?page=1&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    r = BenchResult('皮套产品列表(分页)')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/cases/products?page=1&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    r = BenchResult('皮套入库列表')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/cases/in/list?page=1&per_page=20', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    return results


async def bench_product_list(session, token: str) -> list[BenchResult]:
    """测试产品列表"""
    results = []
    headers = {'Authorization': f'Bearer {token}'}

    r = BenchResult('产品列表首页')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/products/list?page=1&per_page=50', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    r = BenchResult('产品搜索')
    for _ in range(ROUNDS):
        _status, _, ms = await _request(session, 'GET', '/products/list?page=1&per_page=50&search=测试', headers=headers)
        r.latencies_ms.append(ms)
    results.append(r)

    return results


async def get_auth_token(session) -> str:
    """获取认证 token"""
    # 尝试用测试账号登录
    login_data = {'username': os.getenv('TEST_USER', 'admin'), 'password': os.getenv('TEST_PASS', 'admin123')}
    async with session.post(f'{API_BASE}/auth/login', json=login_data) as resp:
        body = await resp.json()
        if 'token' in body:
            return body['token']
        if 'access_token' in body:
            return body['access_token']
        raise RuntimeError(f'登录失败: {body}')


async def run_all_benchmarks():
    """运行所有基准测试"""
    import aiohttp

    print('=' * 70)
    print('  ERP 系统性能基准测试 - 20K+ 数据量场景')
    print(f'  API: {API_BASE}')
    print(f'  目标延迟: {TARGET_LATENCY_MS}ms (P95)')
    print(f'  每测试轮次: {ROUNDS}')
    print('=' * 70)
    print()

    all_results: list[BenchResult] = []

    async with aiohttp.ClientSession() as session:
        try:
            token = await get_auth_token(session)
            print('[认证] 登录成功\n')
        except Exception as e:
            print(f'[认证] 登录失败: {e}')
            print('请确认 API 服务已启动且测试账号正确')
            return

        bench_funcs = [
            ('库存模块', bench_inventory_paginated),
            ('订单模块', bench_order_list),
            ('入库出库', bench_stock_in_out),
            ('皮套模块', bench_case_endpoints),
            ('产品模块', bench_product_list),
        ]

        for name, func in bench_funcs:
            print(f'--- {name} ---')
            try:
                results = await func(session, token)
                all_results.extend(results)
            except Exception as e:
                print(f'  [错误] {e}')
            print()

    # 生成报告
    print('=' * 70)
    print('  性能测试报告')
    print('=' * 70)
    print()

    passed = 0
    failed = 0
    for r in all_results:
        status = 'PASS' if r.passed else 'FAIL'
        if r.passed:
            passed += 1
        else:
            failed += 1
        print(f'  [{status}] {r.name}')
        print(f'         avg={r.avg_ms:.1f}ms  p50={r.p50_ms:.1f}ms  p95={r.p95_ms:.1f}ms  max={r.max_ms:.1f}ms')

    print()
    print(f'  通过: {passed}/{passed + failed}  失败: {failed}/{passed + failed}')
    print(f'  目标: P95 <= {TARGET_LATENCY_MS}ms')

    # 保存 JSON 报告
    report_path = os.path.join(os.path.dirname(__file__), 'reports', f'bench_20k_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    report = {
        'timestamp': datetime.now().isoformat(),
        'api_base': API_BASE,
        'target_latency_ms': TARGET_LATENCY_MS,
        'rounds': ROUNDS,
        'results': [
            {
                'name': r.name,
                'avg_ms': round(r.avg_ms, 2),
                'p50_ms': round(r.p50_ms, 2),
                'p95_ms': round(r.p95_ms, 2),
                'max_ms': round(r.max_ms, 2),
                'min_ms': round(r.min_ms, 2),
                'passed': r.passed,
                'latencies': [round(x, 2) for x in r.latencies_ms],
            }
            for r in all_results
        ],
        'summary': {'passed': passed, 'failed': failed, 'total': passed + failed},
    }
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'\n  报告已保存: {report_path}')


if __name__ == '__main__':
    asyncio.run(run_all_benchmarks())
