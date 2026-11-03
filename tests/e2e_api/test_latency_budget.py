"""性能延迟预算门禁（2026-11-03 审查 S3 / M14）。

背景
----
CI 此前**没有任何性能断言**：``docs/performance-baseline.md`` 与
``docs/db-index-analysis-2026-10-31.md`` 两轮实测结论无测试锁定，
2026-10-31~11-01 的索引大重构（迁移 105→107）也没有复测佐证。
本文件把 ``docs/slo.md`` 的阈值变成可执行门禁。

执行条件
--------
需要真实隔离后端（CI 的 5502 + ``*_test`` 库）。
``tests/e2e_api/conftest.py`` 的收集期守卫负责：未设置可达目标时整目录 skip、
目标身份不符时 fail —— 因此本文件在本地/无后端环境下**不会**误连生产。

阈值来源约定
------------
本文件**不重新定义**阈值：一律从 ``docs/slo.md`` 抄录，并在下方注释标注档位。
改阈值请同时改两处（或在后续重构中把 slo.md 解析进来）。
一旦出现跨环境抖动，先加采样次数/按实测 p95+3σ 收紧，不要直接删门禁。
"""
from __future__ import annotations

import math
import statistics
import time

import pytest

pytestmark = pytest.mark.e2e_api

# ---- 阈值（与 docs/slo.md 第三节一致）----
# 常规档：高频列表页，p50 ≤ 300ms / p95 ≤ 1500ms
REGULAR_P50_MS = 300.0
REGULAR_P95_MS = 1500.0
# 容忍档：聚合/报表类，p50 ≤ 800ms / p95 ≤ 3000ms
TOLERANT_P50_MS = 800.0
TOLERANT_P95_MS = 3000.0

WARMUP_ROUNDS = 3
SAMPLES = 20

# (展示名, 路径, 档位)
ENDPOINTS: list[tuple[str, str, str]] = [
    ("客户订单列表", "/api/v1/orders/list", "regular"),
    ("产品列表", "/api/v1/products/list", "regular"),
    ("库存结余", "/api/v1/stock/inventory", "regular"),
    ("客户列表", "/api/v1/customers/list", "regular"),
    ("仪表盘统计", "/api/v1/dashboard/stats", "tolerant"),
]


def _percentile(values: list[float], pct: float) -> float:
    """最近秩法分位（样本量小，不引 numpy）。"""
    ordered = sorted(values)
    if not ordered:
        raise ValueError("无采样数据")
    rank = math.ceil(pct / 100.0 * len(ordered)) - 1
    return ordered[min(max(rank, 0), len(ordered) - 1)]


@pytest.mark.parametrize(("label", "path", "tier"), ENDPOINTS, ids=[e[0] for e in ENDPOINTS])
async def test_latency_budget(admin_api, label: str, path: str, tier: str) -> None:
    """对单条主链路采样并断言延迟预算。"""
    # 预热：CI runner 首次请求要吃连接池建立/DNS/首编译开销，不能计入分位
    for _ in range(WARMUP_ROUNDS):
        warm = await admin_api.get(path)
        assert warm.status_code == 200, f"[{label}] 预热请求失败 HTTP {warm.status_code}: {warm.text[:200]}"

    samples: list[float] = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        response = await admin_api.get(path)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert response.status_code == 200, (
            f"[{label}] {path} 返回 HTTP {response.status_code}（SLO 要求 5xx 为 0）："
            f"{response.text[:200]}"
        )
        samples.append(elapsed_ms)

    p50 = statistics.median(samples)
    p95 = _percentile(samples, 95.0)
    worst = max(samples)

    if tier == "regular":
        p50_limit, p95_limit = REGULAR_P50_MS, REGULAR_P95_MS
    else:
        p50_limit, p95_limit = TOLERANT_P50_MS, TOLERANT_P95_MS

    detail = (
        f"[{label}] {path}（{tier} 档）\n"
        f"  p50={p50:.1f}ms（限 {p50_limit:.0f}）\n"
        f"  p95={p95:.1f}ms（限 {p95_limit:.0f}）\n"
        f"  最差={worst:.1f}ms，采样 {SAMPLES} 次，预热 {WARMUP_ROUNDS} 次\n"
        f"  阈值口径见 docs/slo.md"
    )
    assert p50 <= p50_limit, f"延迟超出 {tier} 档中位数预算：\n{detail}"
    assert p95 <= p95_limit, f"延迟超出 {tier} 档 p95 预算：\n{detail}"
