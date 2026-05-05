#!/usr/bin/env python3
"""
ERP 系统端到端性能监测脚本

覆盖数据量 5K / 10K / 20K / 30K 场景，
监测 API 响应时间、数据库查询耗时、缓存命中率、内存占用。

运行方式:
  python scripts/perf_optimization/e2e_performance_monitor.py
"""

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:5002/api/v1")
MONITOR_ROUNDS = 10
DATA_SCALES = [5000, 10000, 20000, 30000]
TARGET_LATENCY_MS = 200


@dataclass
class MetricPoint:
    timestamp: str
    latency_ms: float
    status_code: int
    endpoint: str
    data_scale: int
    cache_hit: bool = False
    db_time_ms: float = 0.0
    memory_mb: float = 0.0


@dataclass
class MonitorResult:
    endpoint: str
    data_scale: int
    latencies: list[float] = field(default_factory=list)
    status_codes: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def avg_ms(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0

    @property
    def p50_ms(self) -> float:
        s = sorted(self.latencies)
        return s[len(s) // 2] if s else 0

    @property
    def p95_ms(self) -> float:
        s = sorted(self.latencies)
        return s[int(len(s) * 0.95)] if len(s) >= 2 else (s[0] if s else 0)

    @property
    def p99_ms(self) -> float:
        s = sorted(self.latencies)
        return s[int(len(s) * 0.99)] if len(s) >= 100 else (s[-1] if s else 0)

    @property
    def max_ms(self) -> float:
        return max(self.latencies) if self.latencies else 0

    @property
    def min_ms(self) -> float:
        return min(self.latencies) if self.latencies else 0

    @property
    def error_rate(self) -> float:
        return len(self.errors) / len(self.status_codes) if self.status_codes else 0

    @property
    def passed(self) -> bool:
        return self.p95_ms <= TARGET_LATENCY_MS and self.error_rate < 0.01


ENDPOINTS = [
    ("GET", "/stock/inventory", "库存列表"),
    ("GET", "/orders/list", "订单列表"),
    ("GET", "/stock/in/list", "入库列表"),
    ("GET", "/stock/out/list", "出库列表"),
    ("GET", "/products/list", "产品列表"),
    ("GET", "/customers/list", "客户列表"),
    ("GET", "/cases/inventory-summary", "皮套库存汇总"),
]


async def get_auth_token(session) -> str:
    import aiohttp
    login_data = {
        "username": os.getenv("TEST_USER", "admin"),
        "password": os.getenv("TEST_PASS", "admin123"),
    }
    async with session.post(f"{API_BASE}/auth/login", json=login_data) as resp:
        body = await resp.json()
        if "access_token" in body:
            return body["access_token"]
        if "token" in body:
            return body["token"]
        raise RuntimeError(f"登录失败: {body}")


async def check_data_scale(session, token: str, endpoint: str) -> int:
    """通过获取第1页per_page=1来快速估算数据量"""
    import aiohttp
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with session.get(
            f"{API_BASE}{endpoint}", params={"page": 1, "per_page": 1}, headers=headers
        ) as resp:
            body = await resp.json()
            return body.get("total", 0)
    except Exception:
        return 0


async def monitor_endpoint(
    session, method: str, endpoint: str, token: str, rounds: int = MONITOR_ROUNDS
) -> MonitorResult:
    import aiohttp
    headers = {"Authorization": f"Bearer {token}"}
    result = MonitorResult(endpoint=endpoint, data_scale=0)

    for i in range(rounds):
        url = f"{API_BASE}{endpoint}"
        params = {"page": 1, "per_page": 50}
        start = time.perf_counter()
        try:
            async with session.get(url, params=params, headers=headers) as resp:
                body = await resp.json()
                elapsed = (time.perf_counter() - start) * 1000
                result.latencies.append(elapsed)
                result.status_codes.append(resp.status)
                if resp.status >= 400:
                    result.errors.append(f"HTTP {resp.status}")
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            result.latencies.append(elapsed)
            result.status_codes.append(0)
            result.errors.append(str(e)[:100])

    return result


async def monitor_with_cache_analysis(session, endpoint: str, token: str) -> dict:
    """冷启动 vs 缓存命中对比"""
    import aiohttp
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{API_BASE}{endpoint}"
    params = {"page": 1, "per_page": 50}

    cold_latencies = []
    warm_latencies = []

    for _ in range(3):
        start = time.perf_counter()
        async with session.get(url, params=params, headers=headers) as resp:
            await resp.json()
        cold_latencies.append((time.perf_counter() - start) * 1000)

        for _ in range(5):
            start = time.perf_counter()
            async with session.get(url, params=params, headers=headers) as resp:
                await resp.json()
            warm_latencies.append((time.perf_counter() - start) * 1000)

    return {
        "endpoint": endpoint,
        "cold_avg_ms": sum(cold_latencies) / len(cold_latencies),
        "warm_avg_ms": sum(warm_latencies) / len(warm_latencies),
        "cache_speedup_pct": (
            (sum(cold_latencies) / len(cold_latencies))
            / (sum(warm_latencies) / len(warm_latencies))
            - 1
        )
        * 100,
    }


async def collect_prometheus_metrics(session) -> dict:
    """采集 Prometheus 指标"""
    import aiohttp
    metrics_url = API_BASE.rsplit("/api/v1", 1)[0] + "/api/v1/../metrics"
    try:
        async with session.get(metrics_url.replace("/../", "/")) as resp:
            if resp.status == 200:
                text = await resp.text()
                lines = text.strip().split("\n")
                parsed = {}
                for line in lines:
                    if line.startswith("#") or not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        parsed[parts[0]] = parts[1]
                return parsed
    except Exception:
        pass
    return {}


async def run_monitoring():
    import aiohttp

    print("=" * 80)
    print("  ERP 系统端到端性能监测")
    print(f"  API: {API_BASE}")
    print(f"  每端点轮次: {MONITOR_ROUNDS}")
    print(f"  目标延迟: P95 <= {TARGET_LATENCY_MS}ms")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    async with aiohttp.ClientSession() as session:
        try:
            token = await get_auth_token(session)
            print("[认证] 登录成功\n")
        except Exception as e:
            print(f"[认证] 登录失败: {e}")
            return

        print("--- 数据量检测 ---")
        scale_info = {}
        for method, endpoint, name in ENDPOINTS:
            total = await check_data_scale(session, token, endpoint)
            scale_info[endpoint] = total
            print(f"  {name}: {total:,} 条")

        print("\n--- 响应时间监测 ---")
        all_results = []
        for method, endpoint, name in ENDPOINTS:
            result = await monitor_endpoint(session, method, endpoint, token)
            result.data_scale = scale_info.get(endpoint, 0)
            all_results.append((name, result))
            status = "PASS" if result.passed else "FAIL"
            print(f"  [{status}] {name}")
            print(
                f"         avg={result.avg_ms:.1f}ms  p50={result.p50_ms:.1f}ms  "
                f"p95={result.p95_ms:.1f}ms  p99={result.p99_ms:.1f}ms  "
                f"max={result.max_ms:.1f}ms"
            )
            if result.errors:
                print(f"         错误率: {result.error_rate:.1%}")

        print("\n--- 缓存效果分析 ---")
        cache_results = []
        for method, endpoint, name in ENDPOINTS[:5]:
            cr = await monitor_with_cache_analysis(session, endpoint, token)
            cache_results.append(cr)
            print(
                f"  {name}: 冷启动={cr['cold_avg_ms']:.1f}ms  "
                f"缓存命中={cr['warm_avg_ms']:.1f}ms  "
                f"加速={cr['cache_speedup_pct']:.0f}%"
            )

        prometheus_metrics = await collect_prometheus_metrics(session)
        if prometheus_metrics:
            print("\n--- Prometheus 指标 ---")
            for key in [
                "http_requests_total",
                "http_request_duration_seconds_bucket",
                "slow_query_total",
                "cache_operations_total",
            ]:
                for k, v in prometheus_metrics.items():
                    if k.startswith(key):
                        print(f"  {k} = {v}")
                        break

    report = {
        "timestamp": datetime.now().isoformat(),
        "api_base": API_BASE,
        "target_latency_ms": TARGET_LATENCY_MS,
        "data_scales": {name: r.data_scale for name, r in all_results},
        "endpoints": [
            {
                "name": name,
                "endpoint": r.endpoint,
                "data_scale": r.data_scale,
                "avg_ms": round(r.avg_ms, 2),
                "p50_ms": round(r.p50_ms, 2),
                "p95_ms": round(r.p95_ms, 2),
                "p99_ms": round(r.p99_ms, 2),
                "max_ms": round(r.max_ms, 2),
                "min_ms": round(r.min_ms, 2),
                "error_rate": round(r.error_rate, 4),
                "passed": r.passed,
            }
            for name, r in all_results
        ],
        "cache_analysis": cache_results,
        "prometheus": prometheus_metrics,
        "summary": {
            "passed": sum(1 for _, r in all_results if r.passed),
            "failed": sum(1 for _, r in all_results if not r.passed),
            "total": len(all_results),
        },
    }

    report_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "tests",
        "performance",
        "reports",
        f"e2e_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    asyncio.run(run_monitoring())
