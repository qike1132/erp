"""压测前后对比工具：让"提升多少"从推算变成实测。

为什么需要它
------------
上层报告里的性能数字（"导入快 2.5~6.6 倍"）如果没有前后实测，就永远无法证伪。
本项目此前没有任何可比对的性能基线，所有性能结论都是估算。

诚实测量的四条硬规则
--------------------
1. **必须记录运行模式**：dev 单 worker 与 prod 4 worker 的数字没有可比性。
   报告里内嵌 `scripts/diag/runtime_mode_probe.py` 的判定结果，模式不同会直接告警。
2. **必须预热**：首轮请求含连接建立、缓存冷启动，单独剔除。
3. **逐个端点测**：一次只压一个端点，避免端点间互相干扰；端点内部才用并发。
4. **基线过快的端点不判优劣**：P95 < `--min-baseline-ms`（默认 20ms）时抖动主导，
   「提升 30%」在 3ms 的量级上没有意义 —— 这类端点只报告、不判定。

用法
----
    # 改动前
    python scripts/benchmark_compare.py run --label before --requests 60 --concurrency 8
    # 改动后
    python scripts/benchmark_compare.py run --label after  --requests 60 --concurrency 8
    # 对比
    python scripts/benchmark_compare.py compare \
        --before docs/tickets/artifacts/benchmark/before.json \
        --after  docs/tickets/artifacts/benchmark/after.json \
        --min-improvement 0.3 --max-error-rate 0.01

退出码：run → 0 成功 / 2 环境错误；compare → 0 达标 / 1 未达标 / 2 输入错误
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 复用契约工具的端点配置与鉴权，避免维护两份端点清单。
# import 必须在 sys.path 插入之后（E402 已在 ruff.toml 全局忽略）。
from contract_snapshot import DEFAULT_BASE_URL, DEFAULT_CONFIG, Endpoint, load_config, resolve_token

DEFAULT_OUT_DIR = PROJECT_ROOT / "docs" / "tickets" / "artifacts" / "benchmark"


# ============================================================
# 统计
# ============================================================
def percentile(values: list[float], p: float) -> float:
    """线性插值分位数。values 单位毫秒。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * p
    low, high = math.floor(k), math.ceil(k)
    if low == high:
        return ordered[int(k)]
    return ordered[low] + (ordered[high] - ordered[low]) * (k - low)


def describe(samples: list[float], errors: int, wall_seconds: float) -> dict[str, Any]:
    total = len(samples) + errors
    return {
        "requests": total,
        "errors": errors,
        "error_rate": round(errors / total, 5) if total else 0.0,
        "p50_ms": round(percentile(samples, 0.50), 2),
        "p90_ms": round(percentile(samples, 0.90), 2),
        "p95_ms": round(percentile(samples, 0.95), 2),
        "p99_ms": round(percentile(samples, 0.99), 2),
        "mean_ms": round(sum(samples) / len(samples), 2) if samples else 0.0,
        "rps": round(total / wall_seconds, 1) if wall_seconds > 0 else 0.0,
    }


# ============================================================
# 压测
# ============================================================
async def hit(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    ep: Endpoint,
    headers: dict[str, str],
) -> tuple[float, int]:
    """返回 (耗时毫秒, 状态码；0 表示连接层异常)。"""
    async with sem:
        start = time.perf_counter()
        try:
            resp = await client.request(ep.method, ep.path, params=ep.query or None, headers=headers)
            return (time.perf_counter() - start) * 1000, resp.status_code
        except httpx.HTTPError:  # broad-except: 连接/超时异常要计入错误率而不是中断整轮压测
            return (time.perf_counter() - start) * 1000, 0


async def _one_round(
    client: httpx.AsyncClient,
    ep: Endpoint,
    headers: dict[str, str],
    requests: int,
    concurrency: int,
    warmup: int,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    for _ in range(warmup):
        await hit(client, sem, ep, headers)

    started = time.perf_counter()
    outcomes = await asyncio.gather(*(hit(client, sem, ep, headers) for _ in range(requests)))
    wall = time.perf_counter() - started

    samples = [ms for ms, code in outcomes if 200 <= code < 400]
    errors = sum(1 for _, code in outcomes if not 200 <= code < 400)
    return describe(samples, errors, wall)


def aggregate_rounds(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """多轮取中位数，并暴露轮间离散度。

    单轮在毫秒级端点上噪声可达 ±15%+，直接用单轮数字做前后对比会得出假提升/假退步。
    中位数 + 显式暴露 spread，让人一眼看出这次测量是否可信。
    """

    def median(key: str) -> float:
        return round(percentile([r[key] for r in rounds], 0.5), 2)

    p95s = [r["p95_ms"] for r in rounds]
    return {
        "rounds": len(rounds),
        "requests": rounds[0]["requests"],
        "errors": max(r["errors"] for r in rounds),
        "error_rate": round(max(r["error_rate"] for r in rounds), 5),
        "p50_ms": median("p50_ms"),
        "p90_ms": median("p90_ms"),
        "p95_ms": median("p95_ms"),
        "p99_ms": median("p99_ms"),
        "mean_ms": median("mean_ms"),
        "rps": median("rps"),
        "p95_min_ms": round(min(p95s), 2),
        "p95_max_ms": round(max(p95s), 2),
        "p95_spread": round((max(p95s) - min(p95s)) / min(p95s), 4) if min(p95s) > 0 else 0.0,
    }


async def measure_endpoint(
    client: httpx.AsyncClient,
    ep: Endpoint,
    headers: dict[str, str],
    requests: int,
    concurrency: int,
    warmup: int,
    repeat: int,
) -> dict[str, Any]:
    rounds = [
        await _one_round(client, ep, headers, requests, concurrency, warmup)
        for _ in range(repeat)
    ]
    stats = aggregate_rounds(rounds)
    stats["name"] = ep.name
    stats["path"] = ep.path
    stats["query"] = ep.query
    return stats


async def run_all(args, cfg, endpoints: list[Endpoint]) -> dict[str, Any]:
    token = resolve_token(args.token) if any(e.auth for e in endpoints) else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if token is None and any(e.auth for e in endpoints):
        print("[WARN] 未取得 token，鉴权端点将全部 401（结果无意义）", file=sys.stderr)

    limits = httpx.Limits(max_connections=args.concurrency * 2, max_keepalive_connections=args.concurrency)
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=args.timeout, trust_env=False, limits=limits
    ) as client:
        for ep in endpoints:
            stats = await measure_endpoint(
                client, ep, headers, args.requests, args.concurrency, args.warmup, args.repeat
            )
            results.append(stats)
            print(
                f"  {ep.name:<34} n={stats['requests']:<4} err={stats['error_rate']:.3f} "
                f"p50={stats['p50_ms']:>8.2f} p95={stats['p95_ms']:>8.2f} "
                f"p99={stats['p99_ms']:>8.2f} rps={stats['rps']:>7.1f} "
                f"spread={stats['p95_spread']:>6.1%}"
            )

    return {
        "schema_version": 1,
        "label": args.label,
        "base_url": args.base_url,
        "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "params": {
            "requests_per_endpoint": args.requests,
            "concurrency": args.concurrency,
            "warmup": args.warmup,
            "repeat": args.repeat,
            "timeout": args.timeout,
        },
        "env": capture_env(),
        "results": results,
    }


def capture_env() -> dict[str, Any]:
    """抓取运行模式等环境信息 —— 不同模式下的数字不可比。"""
    probe = PROJECT_ROOT / "scripts" / "diag" / "runtime_mode_probe.py"
    env: dict[str, Any] = {"python": sys.version.split()[0]}
    if not probe.exists():
        env["runtime_mode"] = "probe-missing"
        return env
    try:
        proc = subprocess.run(
            [sys.executable, str(probe)],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
        data = json.loads(proc.stdout)
        env["runtime_mode"] = data.get("verdict")
        env["arq_worker_processes"] = data.get("arq_worker_processes")
        env["prod_state_claims"] = data.get("prod_runner_claims")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:  # broad-except: 环境探测失败不应让压测结果丢失
        env["runtime_mode"] = f"probe-failed: {type(exc).__name__}"
    return env


# ============================================================
# 对比
# ============================================================
def compare_reports(before: dict, after: dict, args) -> tuple[list[dict], bool]:
    before_map = {r["name"]: r for r in before.get("results", [])}
    after_map = {r["name"]: r for r in after.get("results", [])}
    rows: list[dict] = []
    all_pass = True

    for name in sorted(set(before_map) & set(after_map)):
        b, a = before_map[name], after_map[name]
        base_p95, new_p95 = b["p95_ms"], a["p95_ms"]
        improvement = (base_p95 - new_p95) / base_p95 if base_p95 > 0 else 0.0

        if base_p95 < args.min_baseline_ms:
            verdict, reason = "skip", f"基线 P95 {base_p95:.1f}ms < {args.min_baseline_ms}ms，抖动主导"
        elif a["error_rate"] > args.max_error_rate:
            verdict, reason = "fail", f"错误率 {a['error_rate']:.3f} > {args.max_error_rate}"
            all_pass = False
        elif improvement < args.min_improvement:
            verdict, reason = "fail", f"提升 {improvement:+.1%} < {args.min_improvement:.0%}"
            all_pass = False
        else:
            verdict, reason = "pass", f"提升 {improvement:+.1%}"

        spread = max(b.get("p95_spread", 0.0), a.get("p95_spread", 0.0))
        if spread > args.max_noise_spread:
            reason += f" ⚠噪声大(spread {spread:.0%})"
        rows.append(
            {
                "name": name,
                "before_p95_ms": base_p95,
                "after_p95_ms": new_p95,
                "improvement": round(improvement, 4),
                "before_error_rate": b["error_rate"],
                "after_error_rate": a["error_rate"],
                "round_spread": round(spread, 4),
                "verdict": verdict,
                "reason": reason,
            }
        )

    only_before = sorted(set(before_map) - set(after_map))
    only_after = sorted(set(after_map) - set(before_map))
    if only_before or only_after:
        all_pass = False
        rows.append(
            {
                "name": "(配置不一致)",
                "verdict": "fail",
                "reason": f"仅 before 有 {only_before}；仅 after 有 {only_after}",
            }
        )
    return rows, all_pass


def run_compare(args) -> int:
    try:
        before = json.loads(Path(args.before).read_text(encoding="utf-8"))
        after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[ERROR] 读取报告失败：{exc}", file=sys.stderr)
        return 2

    mode_b, mode_a = before.get("env", {}).get("runtime_mode"), after.get("env", {}).get("runtime_mode")
    if mode_b != mode_a:
        print(
            f"[WARN] 两次压测的运行模式不同：{mode_b} vs {mode_a}\n"
            "       不同模式（dev 单 worker / prod 4 worker）的数字**不可比**，请在同一模式下重测。",
            file=sys.stderr,
        )

    rows, all_pass = compare_reports(before, after, args)
    if not rows:
        print("[ERROR] 两份报告没有可比对的端点", file=sys.stderr)
        return 2

    print(f"{'端点':<34}{'before P95':>12}{'after P95':>12}{'提升':>10}{'轮间噪声':>10}  判定")
    print("-" * 94)
    for r in rows:
        if "before_p95_ms" not in r:
            print(f"{r['name']:<34}{'-':>12}{'-':>12}{'-':>10}{'-':>10}  FAIL  {r['reason']}")
            continue
        print(
            f"{r['name']:<34}{r['before_p95_ms']:>12.2f}{r['after_p95_ms']:>12.2f}"
            f"{r['improvement']:>10.1%}{r.get('round_spread', 0):>10.1%}  "
            f"{r['verdict'].upper():<6}{r['reason']}"
        )
    print("-" * 94)
    counted = [r for r in rows if r["verdict"] in ("pass", "fail")]
    skipped = len(rows) - len(counted)
    out = args.out or (DEFAULT_OUT_DIR / f"compare-{before.get('label')}-vs-{after.get('label')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "before_label": before.get("label"),
                "after_label": after.get("label"),
                "thresholds": {
                    "min_improvement": args.min_improvement,
                    "max_error_rate": args.max_error_rate,
                    "min_baseline_ms": args.min_baseline_ms,
                    "max_noise_spread": args.max_noise_spread,
                },
                "passed": all_pass,
                "judged": len(counted),
                "skipped": skipped,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"对比报告 → {out}")

    if not counted:
        # "无法判定" ≠ "达标"。全部被跳过时给出明确的不可判定结论与非零退出码，
        # 否则 CI 会把"没测出来"当成"没问题"。
        print(
            f"[不可判定] {skipped} 个端点全部被跳过 —— 基线 P95 低于 {args.min_baseline_ms}ms 判定线，"
            "轮间噪声主导。\n"
            "           解决方向：提高 --concurrency / --requests 让系统进入有意义的负载区，"
            "或使用更真实的数据量，使 P95 明显高于判定线后重测。"
        )
        return 2

    print(f"判定端点 {len(counted)} 个（跳过 {skipped} 个）→ {'达标' if all_pass else '未达标'}")
    return 0 if all_pass else 1


# ============================================================
# CLI
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="压测前后对比")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="执行一轮压测并落盘报告")
    run.add_argument("--label", required=True, help="标签，如 before / after")
    run.add_argument("--base-url", default=DEFAULT_BASE_URL)
    run.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    run.add_argument("--only", nargs="*", help="只压指定端点")
    run.add_argument("--requests", type=int, default=60, help="每个端点每轮的请求数")
    run.add_argument("--concurrency", type=int, default=8)
    run.add_argument("--warmup", type=int, default=5, help="预热的请求数（不计入统计）")
    run.add_argument(
        "--repeat", type=int, default=3,
        help="每个端点重复轮数，取中位数并暴露离散度（1 = 快速冒烟，但噪声大）",
    )
    run.add_argument("--timeout", type=float, default=30.0)
    run.add_argument("--token")
    run.add_argument("--out", type=Path, help="报告输出路径")

    cmp_ = sub.add_parser("compare", help="对比两份报告")
    cmp_.add_argument("--before", required=True)
    cmp_.add_argument("--after", required=True)
    cmp_.add_argument("--min-improvement", type=float, default=0.30, help="P95 至少下降多少比例")
    cmp_.add_argument("--max-error-rate", type=float, default=0.01)
    cmp_.add_argument(
        "--min-baseline-ms", type=float, default=50.0,
        help="基线 P95 低于该值则不判优劣。实测结论：20~30ms 量级的轮间噪声就有 ±15~17%%，"
             "在噪声地板上判 30%% 提升没有意义；基线越大判据越可信。",
    )
    cmp_.add_argument(
        "--max-noise-spread", type=float, default=0.20,
        help="轮间 P95 离散度超过该值时在判定后标注 ⚠噪声大（提示结论不可靠）",
    )
    cmp_.add_argument("--out", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.cmd == "compare":
        return run_compare(args)

    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] 读取配置失败：{exc}", file=sys.stderr)
        return 2

    endpoints = [e for e in cfg.endpoints if not args.only or e.name in args.only]
    if not endpoints:
        print("[ERROR] 过滤后没有可压测的端点", file=sys.stderr)
        return 2

    print(
        f"压测 {args.base_url}  端点 {len(endpoints)} 个  "
        f"每端点 {args.requests} 次  并发 {args.concurrency}  预热 {args.warmup}"
    )
    report = asyncio.run(run_all(args, cfg, endpoints))

    out = args.out or (DEFAULT_OUT_DIR / f"{args.label}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n运行模式：{report['env'].get('runtime_mode')}")
    print(f"报告 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
