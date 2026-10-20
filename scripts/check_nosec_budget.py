"""nosec 压制预算检查（L6 修复）

防止 `# nosec` 压制注解数量无限增长——每个压制点都应是"经人工核验的例外"，
而非掩盖问题的常规手段。超出预算时以非零码退出；已接入 `scripts/quality_gate.py`
的 MODE_EXIT 门禁（本地提交钩子 + CI 同时生效）。

2026-10-20 审计 P1-32：
    - 计数口径改「git 跟踪的 .py」——旧实现 rglob 全盘扫描，把 logs/_head_check/
      等运行期副本计入（报 150 而非 83），且从未接任何门禁。
    - 预算重置为当前实测值（先还债再棘轮：不得新增；逐批压回 70）。

用法:
    python scripts/check_nosec_budget.py            # 使用脚本内预算
    python scripts/check_nosec_budget.py --budget 70
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 2026-10-20 审计 P1-32：git 跟踪口径实测 83（旧 rglob 口径 150 含 logs/ 副本）；
# 「先还债再棘轮」——先按实测值封顶防增长，再逐批压回原预算 70。
DEFAULT_BUDGET = 83
NOSEC_RE = re.compile(r"#\s*nosec\b")
SKIP_DIRS = {
    "__pycache__", "node_modules", ".git", "dist", "build", ".venv", "venv",
    "tests",  # tests 与本脚本自身不计入预算（口径：生产代码）
    "logs", "backups", "_ops", "team",  # 运行期/运维副本不得计入
    ".uv-cache", ".pre-commit-home", ".lockcheck-tmp",
}


def _git_tracked_py(project_root: Path) -> list[Path] | None:
    """git 跟踪的 .py 列表；非 git 环境返回 None（回退 rglob + SKIP_DIRS）。"""
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z", "*.py"],
            cwd=str(project_root), capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    names = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return [project_root / n for n in names if n]


def count_nosec(project_root: Path) -> list[str]:
    tracked = _git_tracked_py(project_root)
    candidates: list[Path] = tracked if tracked is not None else list(project_root.rglob("*.py"))
    hits: list[str] = []
    for py in candidates:
        if any(part in SKIP_DIRS for part in py.parts):
            continue
        try:
            lines = py.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if NOSEC_RE.search(line):
                hits.append(f"{py.as_posix()}:{i}")
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="nosec 压制预算检查")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                        help=f"允许的 nosec 总数上限（默认 {DEFAULT_BUDGET}）")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent,
                        help="项目根目录（默认仓库根）")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读 JSON（quality_gate MODE_JSON 棘轮用）")
    args = parser.parse_args()

    hits = count_nosec(args.root)
    hits = [h for h in hits
            if Path(h.rsplit(":", 1)[0]).name != "check_nosec_budget.py"]  # 排除本脚本文档示例
    if args.json:
        print(json.dumps({"total": len(hits), "budget": args.budget}))
        return 0 if len(hits) <= args.budget else 1
    print(f"nosec 压制点总数: {len(hits)} / 预算 {args.budget}")
    if len(hits) > args.budget:
        print("FAIL: 超出预算。先还债再棘轮——新压制必须先经人工核验并在本脚本调增预算，"
              "或在报告中说明理由。")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
