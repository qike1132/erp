"""基线捕获：一次命令完成"性能改造前"的全部取证，并强制校验前置条件。

为什么不能直接跑 benchmark
--------------------------
性能数据只有在**正确的前置条件下**才有意义。最容易犯的两个错：
  1. 在 dev 单 worker 模式下测，却拿去做 prod 的对比基线 —— 数字不可比
  2. 在契约已漂移的状态下测 —— 连"改造前是什么行为"都没固定住，改完无法归因

所以本脚本把三件事串成一条命令，并在前置条件不满足时**拒绝执行**：

  ① 运行模式判定（必须 prod 多 worker，否则退出码 2 并给出修复指令）
  ② 契约快照比对（确保基线建立在已知的响应结构上）
  ③ 压测并把报告 + 代码状态指纹一起落盘

代码状态指纹
------------
报告里记录 `git HEAD` + 工作区改动摘要的哈希。这样 before/after 两份报告
能证明"测的确实是两份不同的代码"，而不是靠人记忆。

用法
----
    # 切换 prod 之后
    python scripts/capture_baseline.py --label before
    # 改造完成后
    python scripts/capture_baseline.py --label after

    # 允许在非 prod 模式下跑（仅用于冒烟，报告会标注不可比）
    python scripts/capture_baseline.py --label smoke --allow-non-prod

退出码：0 完成；1 契约漂移（基线不可信）；2 前置条件不满足
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "docs" / "tickets" / "artifacts" / "benchmark"
PROBE = PROJECT_ROOT / "scripts" / "diag" / "runtime_mode_probe.py"


def run_cmd(args: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def probe_mode() -> str:
    """运行模式判定；探针不可用时返回 'unknown' 而不是崩掉。"""
    if not PROBE.exists():
        return "probe-missing"
    rc, out, _ = run_cmd([str(PROBE.relative_to(PROJECT_ROOT))])
    if rc != 0:
        return "probe-failed"
    try:
        return str(json.loads(out).get("verdict") or "unknown")
    except ValueError:
        return "unparsable"


def code_fingerprint() -> dict[str, object]:
    """记录被测代码状态：HEAD + 工作区改动摘要哈希。"""

    def git(*a: str) -> str:
        proc = subprocess.run(
            ["git", *a], cwd=PROJECT_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        return (proc.stdout or "").strip()

    status = git("status", "--porcelain")
    changed = [line for line in status.splitlines() if line.strip()]
    return {
        "head": git("rev-parse", "HEAD") or "unknown",
        "dirty_files": len(changed),
        "worktree_hash": hashlib.sha256(status.encode("utf-8")).hexdigest()[:16],
    }


def check_contract() -> tuple[int, dict[str, int]]:
    """跑契约比对，返回 (退出码, 统计)。"""
    rc, out, _ = run_cmd(["scripts/contract_snapshot.py", "--check", "--json"])
    try:
        data = json.loads(out)
        return rc, {
            "matched": int(data.get("matched", 0)),
            "drifted": int(data.get("drifted", 0)),
            "errored": int(data.get("errored", 0)),
        }
    except ValueError:
        return rc, {"matched": 0, "drifted": 0, "errored": -1}


def main() -> int:
    parser = argparse.ArgumentParser(description="基线捕获（模式校验 + 契约 + 压测 + 指纹）")
    parser.add_argument("--label", required=True)
    parser.add_argument("--allow-non-prod", action="store_true",
                        help="允许在非 prod 模式下执行（报告会标注不可比）")
    parser.add_argument("--skip-contract", action="store_true")
    parser.add_argument("--requests", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--only", nargs="*", help="只压指定端点（透传给 benchmark）")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- ① 运行模式 ----------
    mode = probe_mode()
    is_prod = mode.startswith("prod")
    print(f"[1/4] 运行模式：{mode}")
    if not is_prod and not args.allow_non_prod:
        print(
            "\n[拒绝执行] 前置条件不满足：当前不是 prod 多 worker 模式。\n"
            "           在单 worker 下采集的数字与 prod 不可比，采了也是废数据。\n\n"
            "   修复方式（需要管理员权限的 PowerShell）：\n"
            "       powershell -Command \"Start-Process powershell -Verb RunAs -ArgumentList "
            "'-File d:\\erp_system\\_recover_prod.ps1'\"\n"
            "   或手动：以管理员身份运行 _recover_prod.ps1，然后重跑本命令。\n"
            "   仅想冒烟验证流程可加 --allow-non-prod（报告会标注不可比）。",
            file=sys.stderr,
        )
        return 2

    # ---------- ② 契约 ----------
    contract: dict[str, int] = {}
    if args.skip_contract:
        print("[2/4] 契约比对：已跳过")
    else:
        rc, contract = check_contract()
        print(f"[2/4] 契约比对：{contract}")
        if rc == 1:
            print(
                "\n[中止] 契约已漂移 —— 基线不可信。\n"
                "       先查清是接口有意变更还是非预期改动，再决定是否 --record 更新快照。",
                file=sys.stderr,
            )
            return 1
        if rc == 2:
            print("[中止] 契约工具环境错误（详见上方输出）", file=sys.stderr)
            return 2

    # ---------- ③ 压测 ----------
    report_path = OUT_DIR / f"{args.label}.json"
    print(f"[3/4] 压测中（每端点 {args.requests} 次 × {args.repeat} 轮，并发 {args.concurrency}）…")
    rc, out, err = run_cmd([
        "scripts/benchmark_compare.py", "run",
        "--label", args.label,
        "--requests", str(args.requests),
        "--concurrency", str(args.concurrency),
        "--repeat", str(args.repeat),
        "--out", str(report_path),
        *(["--only", *args.only] if args.only else []),
    ])
    sys.stdout.write(out)
    if rc != 0:
        print(f"[中止] 压测失败：{err[:400]}", file=sys.stderr)
        return 2

    # ---------- ④ 清单 ----------
    manifest = {
        "schema_version": 1,
        "label": args.label,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "runtime_mode": mode,
        "comparable": is_prod,
        "contract": contract,
        "code": code_fingerprint(),
        "benchmark_report": str(report_path.relative_to(PROJECT_ROOT)),
    }
    manifest_path = OUT_DIR / f"{args.label}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[4/4] 清单 → {manifest_path.relative_to(PROJECT_ROOT)}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if not is_prod:
        print("\n⚠️ 本次为 **不可比** 基线（非 prod 模式），请勿用于前后对比结论。")
    print("\n下一步：完成性能改造后执行  python scripts/capture_baseline.py --label after")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
