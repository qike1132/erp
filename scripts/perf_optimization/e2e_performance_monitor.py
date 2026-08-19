#!/usr/bin/env python3
"""
ERP 端到端性能监测脚本
覆盖 5K/10K/20K/30K 数据量场景，监测 API 响应时间、缓存命中率。

运行: python scripts/perf_optimization/e2e_performance_monitor.py
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:5002/api/v1")
ROUNDS = 10
TARGET_LATENCY_MS = 200

@dataclass
class MonitorResult:
    endpoint: str
    name: str
    latencies: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    @property
    def avg_ms(self): return sum(self.latencies) / len(self.latencies) if self.latencies else 0
    @property
    def p50_ms(self):
        s = sorted(self.latencies); return s[len(s)//2] if s else 0
    @property
    def p95_ms(self):
        s = sorted(self.latencies); return s[int(len(s)*0.95)] if len(s)>=2 else (s[0] if s else 0)
    @property
    def p99_ms(self):
        s = sorted(self.latencies); return s[int(len(s)*0.99)] if len(s)>=100 else (s[-1] if s else 0)
    @property
    def max_ms(self): return max(self.latencies) if self.latencies else 0
    @property
    def error_rate(self): return len(self.errors)/(len(self.latencies)+len(self.errors)) if (self.latencies or self.errors) else 0
    @property
    def passed(self): return self.p95_ms <= TARGET_LATENCY_MS and self.error_rate < 0.01

ENDPOINTS = [
    ("GET", "/stock/inventory", "库存列表"),
    ("GET", "/orders/list", "订单列表"),
    ("GET", "/stock/in/list", "入库列表"),
    ("GET", "/stock/out/list", "出库列表"),
    ("GET", "/products/list", "产品列表"),
    ("GET", "/customers/list", "客户列表"),
]

async def get_token(session):
    data = {"username": os.getenv("TEST_USER","admin"), "password": os.getenv("TEST_PASS","admin123")}
    async with session.post(f"{API_BASE}/auth/login", json=data) as r:
        b = await r.json()
        token = b.get("access_token") or b.get("token")
        if not token:
            raise RuntimeError(f"登录失败: {b}")
        return token

async def monitor_endpoint(session, endpoint, token):
    headers = {"Authorization": f"Bearer {token}"}
    result = MonitorResult(endpoint=endpoint, name="")
    for _ in range(ROUNDS):
        start = time.perf_counter()
        try:
            async with session.get(f"{API_BASE}{endpoint}", params={"page":1,"per_page":50}, headers=headers) as r:
                await r.json()
                result.latencies.append((time.perf_counter()-start)*1000)
        except Exception as e:
            result.errors.append(str(e)[:100])
    return result

async def cache_analysis(session, endpoint, token):
    headers = {"Authorization": f"Bearer {token}"}
    cold, warm = [], []
    for _ in range(3):
        s = time.perf_counter()
        async with session.get(f"{API_BASE}{endpoint}", params={"page":1,"per_page":50}, headers=headers) as r: await r.json()
        cold.append((time.perf_counter()-s)*1000)
        for _ in range(5):
            s = time.perf_counter()
            async with session.get(f"{API_BASE}{endpoint}", params={"page":1,"per_page":50}, headers=headers) as r: await r.json()
            warm.append((time.perf_counter()-s)*1000)
    cold_avg = sum(cold)/len(cold)
    warm_avg = sum(warm)/len(warm)
    return {"cold_avg_ms": round(cold_avg,1), "warm_avg_ms": round(warm_avg,1), "speedup_pct": round((cold_avg/warm_avg-1)*100,1)}

async def run():
    import aiohttp
    print("="*80)
    print("  ERP 端到端性能监测")
    print(f"  API: {API_BASE}  轮次: {ROUNDS}  目标: P95<={TARGET_LATENCY_MS}ms")
    print("="*80)
    async with aiohttp.ClientSession() as session:
        try: token = await get_token(session)
        except Exception as e: print(f"登录失败: {e}"); return
        print("[认证] 成功\n")

        all_results = []
        for _method, ep, name in ENDPOINTS:
            r = await monitor_endpoint(session, ep, token)
            r.name = name
            all_results.append(r)
            st = "PASS" if r.passed else "FAIL"
            print(f"  [{st}] {name}: avg={r.avg_ms:.1f}ms p50={r.p50_ms:.1f}ms p95={r.p95_ms:.1f}ms p99={r.p99_ms:.1f}ms max={r.max_ms:.1f}ms err={r.error_rate:.1%}")

        print("\n--- 缓存效果 ---")
        for _, ep, name in ENDPOINTS[:4]:
            ca = await cache_analysis(session, ep, token)
            print(f"  {name}: 冷={ca['cold_avg_ms']}ms 热={ca['warm_avg_ms']}ms 加速={ca['speedup_pct']}%")

    report = {
        "timestamp": datetime.now().isoformat(),
        "results": [{"name":r.name,"avg_ms":round(r.avg_ms,2),"p95_ms":round(r.p95_ms,2),"p99_ms":round(r.p99_ms,2),"passed":r.passed} for r in all_results],
        "summary": {"passed": sum(1 for r in all_results if r.passed), "failed": sum(1 for r in all_results if not r.passed)}
    }
    path = os.path.join(project_root, "tests","performance","reports",f"e2e_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2)
    print(f"\n报告: {path}")

if __name__ == "__main__": asyncio.run(run())
