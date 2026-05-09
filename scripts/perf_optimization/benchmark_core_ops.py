#!/usr/bin/env python3
"""
核心操作性能基准测试
测试: 加载/筛选/排序/编辑/删除，目标 P95 < 200ms

运行: python scripts/perf_optimization/benchmark_core_ops.py
"""
import asyncio, json, os, sys, time, statistics
from dataclasses import dataclass, field
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:5002/api/v1")
TARGET_MS = 200
ROUNDS = 15

@dataclass
class BenchResult:
    name: str; category: str
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    @property
    def avg(self): return statistics.mean(self.latencies) if self.latencies else 0
    @property
    def p50(self): return statistics.median(self.latencies) if self.latencies else 0
    @property
    def p95(self):
        s = sorted(self.latencies); return s[int(len(s)*0.95)] if len(s)>=2 else (s[0] if s else 0)
    @property
    def p99(self):
        s = sorted(self.latencies); return s[int(len(s)*0.99)] if len(s)>=100 else (s[-1] if s else 0)
    @property
    def max(self): return max(self.latencies) if self.latencies else 0
    @property
    def passed(self): return self.p95 <= TARGET_MS and len(self.errors) == 0

async def get_token(session):
    data = {"username": os.getenv("TEST_USER","admin"), "password": os.getenv("TEST_PASS","admin123")}
    async with session.post(f"{API_BASE}/auth/login", json=data) as r:
        b = await r.json()
        token = b.get("access_token") or b.get("token")
        if not token:
            raise RuntimeError(f"登录失败: {b}")
        return token

async def bench(session, method, path, token, body=None, rounds=ROUNDS):
    import aiohttp
    headers = {"Authorization": f"Bearer {token}"}
    if body: headers["Content-Type"] = "application/json"
    result = BenchResult(name=path, category="")
    for _ in range(rounds):
        start = time.perf_counter()
        try:
            if method == "GET":
                async with session.get(f"{API_BASE}{path}", headers=headers) as r:
                    await r.json()
            elif method == "POST":
                async with session.post(f"{API_BASE}{path}", json=body, headers=headers) as r:
                    await r.json()
            elif method == "PUT":
                async with session.put(f"{API_BASE}{path}", json=body, headers=headers) as r:
                    await r.json()
            elif method == "DELETE":
                async with session.delete(f"{API_BASE}{path}", headers=headers) as r:
                    await r.json()
            result.latencies.append((time.perf_counter()-start)*1000)
        except Exception as e:
            result.errors.append(str(e)[:80])
    return result

async def run():
    import aiohttp
    print("="*80)
    print("  ERP 核心操作性能基准测试")
    print(f"  API: {API_BASE}  轮次: {ROUNDS}  目标: P95<={TARGET_MS}ms")
    print("="*80)

    async with aiohttp.ClientSession() as session:
        try: token = await get_token(session)
        except Exception as e: print(f"登录失败: {e}"); return

        all_results: list[BenchResult] = []

        # === 加载 ===
        print("\n--- 加载操作 ---")
        ops = [
            ("库存首页", "GET", "/stock/inventory?page=1&per_page=50"),
            ("库存翻页(5)", "GET", "/stock/inventory?page=5&per_page=50"),
            ("库存翻页(100)", "GET", "/stock/inventory?page=100&per_page=50"),
            ("订单首页", "GET", "/orders/list?page=1&per_page=50"),
            ("订单翻页(10)", "GET", "/orders/list?page=10&per_page=50"),
            ("入库首页", "GET", "/stock/in/list?page=1&per_page=50"),
            ("出库首页", "GET", "/stock/out/list?page=1&per_page=50"),
            ("产品列表", "GET", "/products/list?page=1&per_page=50"),
            ("客户列表", "GET", "/customers/list?page=1&per_page=50"),
        ]
        for name, method, path in ops:
            r = await bench(session, method, path, token)
            r.name = name; r.category = "加载"
            all_results.append(r)
            print(f"  [{'PASS' if r.passed else 'FAIL'}] {name}: avg={r.avg:.1f}ms p50={r.p50:.1f}ms p95={r.p95:.1f}ms p99={r.p99:.1f}ms")

        # === 筛选 ===
        print("\n--- 筛选操作 ---")
        ops = [
            ("订单按状态", "GET", "/orders/list?status=待备货&per_page=50"),
            ("订单按客户", "GET", "/orders/list?customer=压测&per_page=50"),
            ("库存按客户", "GET", "/stock/inventory?customer=压测客户&per_page=50"),
        ]
        for name, method, path in ops:
            r = await bench(session, method, path, token)
            r.name = name; r.category = "筛选"
            all_results.append(r)
            print(f"  [{'PASS' if r.passed else 'FAIL'}] {name}: avg={r.avg:.1f}ms p95={r.p95:.1f}ms")

        # === 排序 ===
        print("\n--- 排序操作 ---")
        ops = [
            ("订单按日期排序", "GET", "/orders/list?sort_by=order_date&sort_order=desc&per_page=50"),
            ("订单按数量排序", "GET", "/orders/list?sort_by=quantity&sort_order=desc&per_page=50"),
        ]
        for name, method, path in ops:
            r = await bench(session, method, path, token)
            r.name = name; r.category = "排序"
            all_results.append(r)
            print(f"  [{'PASS' if r.passed else 'FAIL'}] {name}: avg={r.avg:.1f}ms p95={r.p95:.1f}ms")

        # === 编辑 ===
        print("\n--- 编辑操作 ---")
        r = BenchResult(name="创建订单", category="编辑")
        for i in range(min(ROUNDS, 5)):
            body = {"product_id": 1, "quantity": 100, "customer": f"压测编辑{i}", "note": "bench", "order_type": "regular"}
            start = time.perf_counter()
            try:
                async with session.post(f"{API_BASE}/orders/create", json=body, headers={"Authorization":f"Bearer {token}"}) as resp:
                    await resp.json()
                r.latencies.append((time.perf_counter()-start)*1000)
            except Exception as e:
                r.errors.append(str(e)[:80])
        all_results.append(r)
        print(f"  [{'PASS' if r.passed else 'FAIL'}] 创建订单: avg={r.avg:.1f}ms p95={r.p95:.1f}ms")

        # === 搜索 ===
        print("\n--- 搜索操作 ---")
        r = await bench(session, "GET", "/products/list?search=压测&per_page=50", token)
        r.name = "产品搜索"; r.category = "搜索"
        all_results.append(r)
        print(f"  [{'PASS' if r.passed else 'FAIL'}] 产品搜索: avg={r.avg:.1f}ms p95={r.p95:.1f}ms")

        # === 删除 ===
        print("\n--- 删除操作 ---")
        r = BenchResult(name="删除订单(最新)", category="删除")
        for i in range(min(ROUNDS, 3)):
            start = time.perf_counter()
            try:
                async with session.get(f"{API_BASE}/orders/list?page=1&per_page=1", headers={"Authorization":f"Bearer {token}"}) as resp:
                    d = await resp.json()
                order_id = d.get("orders", d.get("data", [{}]))[0].get("id") if (d.get("orders") or d.get("data")) else None
                if order_id:
                    async with session.delete(f"{API_BASE}/orders/delete/{order_id}", headers={"Authorization":f"Bearer {token}"}) as resp:
                        await resp.json()
                    r.latencies.append((time.perf_counter()-start)*1000)
                else:
                    r.errors.append("无订单可删")
            except Exception as e:
                r.errors.append(str(e)[:80])
        all_results.append(r)
        print(f"  [{'PASS' if r.passed else 'FAIL'}] 删除订单: avg={r.avg:.1f}ms p95={r.p95:.1f}ms")

    # 报告
    print("\n" + "="*80)
    print("  测试结果汇总")
    print("="*80)
    for cat in ["加载","筛选","排序","编辑","搜索","删除"]:
        cat_results = [r for r in all_results if r.category == cat]
        if cat_results:
            print(f"\n  [{cat}]")
            for r in cat_results:
                print(f"    {'PASS' if r.passed else 'FAIL'} {r.name}: p95={r.p95:.1f}ms")
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    print(f"\n  通过: {passed}/{passed+failed}  失败: {failed}/{passed+failed}")

    report = {
        "timestamp": datetime.now().isoformat(),
        "target_ms": TARGET_MS, "rounds": ROUNDS,
        "results": [{"name":r.name,"category":r.category,"avg_ms":round(r.avg,2),"p50_ms":round(r.p50,2),"p95_ms":round(r.p95,2),"p99_ms":round(r.p99,2),"passed":r.passed} for r in all_results],
        "summary": {"passed": passed, "failed": failed}
    }
    path = os.path.join(project_root,"tests","performance","reports",f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(f"\n报告: {path}")

if __name__ == "__main__": asyncio.run(run())
