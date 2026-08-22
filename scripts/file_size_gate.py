#!/usr/bin/env python3
"""文件规模门禁（CI 用）：防止新增"上帝类"。

设计原则：
- 默认只检查 **git 变更文件**（modified/added 的 .py），存量超限文件不阻断，
  使门禁可立即在 CI 启用而不会让历史遗留问题卡住流水线。
- 新增/修改的文件超过 --threshold 行（默认 1200）即失败（退出码 1）。
- 本地无 git 或需全量扫描时用 --all 模式。

用法：
    python scripts/file_size_gate.py                # git 变更文件，阈值 1200
    python scripts/file_size_gate.py --threshold 1000
    python scripts/file_size_gate.py --all          # 全量扫描（只报告不失败，除非 --fail）
    python scripts/file_size_gate.py --fail --all   # 全量扫描且超限即失败
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 扫描范围：后端源码 + 测试 + 脚本 + 工具（不含迁移与构建产物）
SCAN_DIRS = ("fastapi_app", "tests", "utils", "scripts")
EXCLUDE_DIRS = {"__pycache__", ".archive", "migrations"}

DEFAULT_THRESHOLD = 1200


def _git_changed_py_files() -> list[Path]:
    """返回 git 追踪的变更 .py 文件（staged + unstaged + untracked）。"""
    try:
        # 已跟踪文件的改动
        tracked = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=AM", "HEAD"],
            capture_output=True, text=True, check=False, timeout=15,
        ).stdout.splitlines()
        # 暂存区的改动（含未提交新文件）
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
            capture_output=True, text=True, check=False, timeout=15,
        ).stdout.splitlines()
        # 未跟踪的新文件
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=False, timeout=15,
        ).stdout.splitlines()
    except (subprocess.SubprocessError, OSError):
        return []
    return [Path(p) for p in dict.fromkeys(tracked + staged + untracked) if p.endswith(".py")]


def _all_py_files() -> list[Path]:
    files: list[Path] = []
    for d in SCAN_DIRS:
        root = Path(d)
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"行数阈值（默认 {DEFAULT_THRESHOLD}）")
    parser.add_argument("--all", action="store_true", help="全量扫描（默认 git 变更文件）")
    parser.add_argument("--fail", action="store_true",
                        help="全量模式下超限即失败（默认仅报告）")
    args = parser.parse_args()

    files = _all_py_files() if args.all else _git_changed_py_files()
    if not files:
        print(f"[file-size-gate] 无扫描文件（{'all' if args.all else 'git-changed'} 模式），跳过")
        return 0

    over: list[tuple[Path, int]] = []
    for f in files:
        try:
            line_count = sum(1 for _ in f.open(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if line_count > args.threshold:
            over.append((f, line_count))

    if not over:
        print(f"[file-size-gate] 通过：{len(files)} 个文件均未超过 {args.threshold} 行")
        return 0

    for f, n in sorted(over, key=lambda x: -x[1]):
        print(f"[file-size-gate] ⚠ {f}: {n} 行（阈值 {args.threshold}）")
    print(f"[file-size-gate] 失败：{len(over)} 个文件超过 {args.threshold} 行"
          f"{'（--fail）' if args.all else '，请拆分后合入'}")
    return 1 if (args.all and args.fail) or not args.all else 0


if __name__ == "__main__":
    sys.exit(main())
