"""nosec 压制预算检查（L6 修复）

防止 `# nosec` 压制注解数量无限增长——每个压制点都应是"经人工核验的例外"，
而非掩盖问题的常规手段。超出预算时以非零码退出，可接入 CI/质量门禁。

用法:
    python scripts/check_nosec_budget.py            # 默认预算 60
    python scripts/check_nosec_budget.py --budget 70
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_BUDGET = 70  # 2026-09-11 基线：生产代码实测 66 处（不含 tests 与本脚本），留少量余量
NOSEC_RE = re.compile(r"#\s*nosec\b")
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "dist", "build", ".venv", "venv",
             "tests"}  # tests 与本脚本自身不计入预算（口径：生产代码）


def count_nosec(project_root: Path) -> list[str]:
    hits: list[str] = []
    for py in project_root.rglob("*.py"):
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
    args = parser.parse_args()

    hits = count_nosec(args.root)
    hits = [h for h in hits
            if Path(h.rsplit(":", 1)[0]).name != "check_nosec_budget.py"]  # 排除本脚本文档示例
    print(f"nosec 压制点总数: {len(hits)} / 预算 {args.budget}")
    if len(hits) > args.budget:
        print("FAIL: 超出预算。新增压制必须先经人工核验并在本脚本调增预算，"
              "或在报告中说明理由。")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
