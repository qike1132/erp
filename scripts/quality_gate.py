"""统一代码质量门禁 runner（基线棘轮 / ratchet）。

为什么需要它
------------
`scripts/check_*.py` 这批 AST 门禁脚本已经写好，但此前只有 `file_size_gate.py`
接进了 CI，其余 5 个既不在 pre-commit 也不在 CI —— 等于门禁不存在。
直接把它们接进去又会立刻报红（存量违规：超长函数 11、宽泛 except 14、
service 层 commit 9、N+1 8、巨型组件 6），红着的门禁最终一定会被人关掉。

所以本 runner 采用**基线棘轮**语义：
  - 存量违规记录在 `scripts/gate_baseline.json`，不阻断；
  - 违规数**超过基线**即失败（有人新增了问题）；
  - 违规数**少于基线**则提示可以收紧基线（自动提示 `--update-baseline`）；
  - 门禁只可能变严，不会变松。

用法
----
    python scripts/quality_gate.py                    # 判定：新增违规即退出码 1
    python scripts/quality_gate.py --report           # 只报告，永不失败（人工巡检用）
    python scripts/quality_gate.py --update-baseline  # 重建基线（收紧时用）
    python scripts/quality_gate.py --verbose          # 打印失败门禁的原始输出
    python scripts/quality_gate.py --only n_plus_one  # 只跑某个门禁

阈值来自 `pyproject.toml` 的 `[tool.code-quality]`，缺省时回落到内置默认值。

退出码：0 = 无新增；1 = 有新增违规；2 = 环境/解析异常（保守失败）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = PROJECT_ROOT / "scripts" / "gate_baseline.json"
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

DEFAULTS = {
    "max_function_length": 80,
    "max_vue_component_length": 400,
}


@dataclass(frozen=True)
class Gate:
    key: str
    title: str
    script: str
    fix_hint: str

    def argv(self, thresholds: dict[str, int]) -> list[str]:
        """构造调用命令（阈值来自 pyproject，按门禁类型注入）。"""
        base = [sys.executable, self.script]
        if self.key == "function_length":
            base += ["--max-length", str(thresholds["max_function_length"])]
        elif self.key == "vue_component_length":
            base += ["--max-length", str(thresholds["max_vue_component_length"])]
        return base


GATES: tuple[Gate, ...] = (
    Gate(
        "n_plus_one",
        "N+1 查询（循环内 execute/scalar/scalars）",
        "scripts/check_n_plus_one.py",
        "改 selectinload/joinedload 一次性加载，或收集外键 IN 批量查 + defaultdict 内存分组",
    ),
    Gate(
        "bare_except",
        "裸 except / 宽泛 except Exception",
        "scripts/check_bare_except.py",
        "收窄到具体异常类型；确需兜底请加 `# defensive: <理由>` 标注或登记白名单",
    ),
    Gate(
        "function_length",
        "后端超长函数",
        "scripts/check_function_length.py",
        "按职责拆分为私有辅助函数（单函数 ≤ 阈值行）",
    ),
    Gate(
        "vue_component_length",
        "前端巨型 Vue 组件",
        "scripts/check_vue_component_length.py",
        "拆子组件或把逻辑抽到 composable（单 SFC ≤ 阈值行）",
    ),
    Gate(
        "service_commit",
        "service 层手动 commit()",
        "scripts/check_service_commit.py",
        "改 flush-only，提交交给 get_async_db / db_transaction；"
        "确需独立事务时按 docs/TRANSACTION_BOUNDARY_GUIDE.md 标注 `# manual-tx: <理由>`",
    ),
)

# 每个门禁成功/失败时会打印统一格式的头部，从中取违规计数。
COUNT_RE = re.compile(r"\[FAIL\][^\d]*(\d+)\s*(?:处|个)")


def load_thresholds() -> dict[str, int]:
    """从 pyproject.toml 读取阈值，缺失或不可解析时回落默认值。"""
    thresholds = dict(DEFAULTS)
    if not PYPROJECT.exists():
        return thresholds
    try:
        import tomllib

        with PYPROJECT.open("rb") as fh:
            data = tomllib.load(fh)
        section = (data.get("tool") or {}).get("code-quality") or {}
        for key in DEFAULTS:
            value = section.get(key)
            if isinstance(value, int) and value > 0:
                thresholds[key] = value
    except Exception as exc:  # broad-except: 配置解析失败不应阻断门禁
        print(f"[WARN] 读取 pyproject.toml 失败，使用默认阈值：{exc}", file=sys.stderr)
    return thresholds


def run_gate(gate: Gate, thresholds: dict[str, int]) -> tuple[int, int | None, str]:
    """执行单个门禁，返回 (退出码, 违规数, 原始输出)。"""
    script_path = PROJECT_ROOT / gate.script
    if not script_path.exists():
        return 2, None, f"[SKIP] 未找到 {gate.script}"

    try:
        proc = subprocess.run(
            gate.argv(thresholds),
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return 2, None, "[ERROR] 超时（>180s）"
    except OSError as exc:
        return 2, None, f"[ERROR] 无法执行：{exc}"

    output = (proc.stdout or "") + (proc.stderr or "")
    match = COUNT_RE.search(output)
    count = int(match.group(1)) if match else None

    if count is None:
        # 解析不到计数：用 [PASS] 判定为 0，否则视为异常（保守失败）
        count = 0 if "[PASS]" in output else None
    return proc.returncode, count, output.strip()


def load_baseline() -> dict[str, int]:
    if not BASELINE_PATH.exists():
        return {}
    try:
        with BASELINE_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: int(v) for k, v in (data.get("counts") or {}).items()}
    except (OSError, ValueError) as exc:
        print(f"[WARN] 基线文件不可读，按空基线处理：{exc}", file=sys.stderr)
        return {}


def save_baseline(counts: dict[str, int]) -> None:
    payload = {
        "_comment": (
            "门禁基线（棘轮）。这些是当前存量违规数，不阻断；"
            "新增违规会被 scripts/quality_gate.py 拦下。数字只允许下调。"
        ),
        "counts": counts,
    }
    BASELINE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="统一代码质量门禁（基线棘轮）")
    parser.add_argument("--report", action="store_true", help="只报告，不判定失败")
    parser.add_argument("--update-baseline", action="store_true", help="用当前结果重建基线")
    parser.add_argument("--verbose", action="store_true", help="打印失败门禁的原始输出")
    parser.add_argument("--only", help="只运行指定门禁（key）")
    args = parser.parse_args()

    thresholds = load_thresholds()
    baseline = load_baseline()

    selected = [g for g in GATES if not args.only or g.key == args.only]
    if not selected:
        print(f"[ERROR] 未知门禁：{args.only}；可选：{', '.join(g.key for g in GATES)}")
        return 2

    results: list[tuple[Gate, int, int | None, str]] = []
    for gate in selected:
        rc, count, output = run_gate(gate, thresholds)
        results.append((gate, rc, count, output))

    print("=" * 78)
    print("代码质量门禁报告（基线棘轮）")
    print("=" * 78)
    print(f"阈值：函数 ≤{thresholds['max_function_length']} 行 / "
          f"Vue 组件 ≤{thresholds['max_vue_component_length']} 行")
    print()

    hard_failure = False
    counts_now: dict[str, int] = {}
    regressions: list[tuple[Gate, int, int]] = []
    improvements: list[tuple[Gate, int, int]] = []

    for gate, _rc, count, _output in results:
        if count is None:
            print(f"  {'ERROR':>8}  {gate.title}  （输出无法解析，保守判定为失败）")
            hard_failure = True
            continue

        counts_now[gate.key] = count
        base = baseline.get(gate.key)
        if base is None:
            print(f"  {'NEW':>8}  {gate.title}: {count} 处（无基线，本次建立）")
        elif count > base:
            print(f"  {'REGRESS':>8}  {gate.title}: {count} 处（基线 {base}）→ 新增 {count - base} 处")
            regressions.append((gate, base, count))
        elif count < base:
            print(f"  {'TIGHTEN':>8}  {gate.title}: {count} 处（基线 {base}）→ 已减少 {base - count} 处")
            improvements.append((gate, base, count))
        else:
            print(f"  {'OK':>8}  {gate.title}: {count} 处（与基线一致）")

    if regressions:
        print()
        print("-" * 78)
        print("必须修复（新增违规）")
        print("-" * 78)
        for gate, base, count in regressions:
            print(f"\n● {gate.title}：{base} → {count}")
            print(f"  通过标准：{gate.fix_hint}")
            if args.verbose:
                for _g, _rc, _c, output in results:
                    if _g.key == gate.key and output:
                        print("  --- 原始输出 ---")
                        for line in output.splitlines():
                            print(f"  {line}")

    if improvements:
        print()
        print("可以收紧基线（建议稍后执行 `--update-baseline`）")
        for gate, base, count in improvements:
            print(f"  ● {gate.title}：{base} → {count}")

    print()
    if args.report:
        print("[REPORT 模式] 不判定失败。")
        return 0
    if args.update_baseline:
        save_baseline(counts_now)
        print(f"[OK] 基线已更新：{BASELINE_PATH.relative_to(PROJECT_ROOT)}")
        return 0
    if hard_failure or regressions:
        print("[FAIL] 存在新增质量问题，请修复后重试。")
        return 1
    print("[PASS] 无新增质量问题。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
