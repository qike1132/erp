#!/usr/bin/env python3
"""文件规模门禁（CI 用）：防止新增"上帝类"。

设计原则：
- 默认只检查 **git 变更文件**（modified/added 的 .py），存量超限文件不阻断，
  使门禁可立即在 CI 启用而不会让历史遗留问题卡住流水线。
- 新增/修改的文件超过阈值即失败（退出码 1）。阈值单一来源是
  `pyproject.toml` 的 `[tool.code-quality] max_file_size`；解析不到才回落到
  本脚本的 DEFAULT_THRESHOLD。此前该值在 pyproject / 本脚本 / CI workflow
  各写一份，改一处必漏两处。
- 本地无 git 或需全量扫描时用 --all 模式。

用法：
    python scripts/file_size_gate.py                # git 变更文件，阈值取 pyproject
    python scripts/file_size_gate.py --threshold 1000   # 显式覆盖（临时排查用）
    python scripts/file_size_gate.py --all          # 全量扫描（只报告不失败，除非 --fail）
    python scripts/file_size_gate.py --fail --all   # 全量扫描且超限即失败
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

# 控制台编码必须显式强制 UTF-8，不能依赖平台默认：
# 中文 Windows 的 stdout 是 cp936，而本脚本会打印 `⚠`（U+26A0）等非 GBK 字符，
# print 时抛 UnicodeEncodeError 使门禁自身崩溃 —— 与下方 git 解码是同一类
# 「中文 Windows 默认编码」缺陷。范式同 scripts/check_service_commit.py。
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 扫描范围：后端源码 + 测试 + 脚本 + 工具（不含迁移与构建产物）
SCAN_DIRS = ("fastapi_app", "tests", "utils", "scripts")
EXCLUDE_DIRS = {"__pycache__", ".archive", "migrations"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

# 仅在 pyproject.toml 缺失/不可解析时使用的兜底值，正常路径不生效。
DEFAULT_THRESHOLD = 1600


def _threshold_from_pyproject() -> int:
    """读取 `[tool.code-quality] max_file_size`，作为阈值的唯一来源。

    与 scripts/quality_gate.py 的 load_thresholds() 同一套约定：
    解析失败只告警并回落默认值，不让门禁自身因配置问题崩溃。
    """
    if not PYPROJECT.exists():
        return DEFAULT_THRESHOLD
    try:
        import tomllib

        with PYPROJECT.open("rb") as fh:
            data = tomllib.load(fh)
        value = ((data.get("tool") or {}).get("code-quality") or {}).get("max_file_size")
        if isinstance(value, int) and value > 0:
            return value
    except Exception as exc:  # broad-except: 配置解析失败不应阻断门禁
        print(f"[WARN] 读取 pyproject.toml 失败，回落到阈值 {DEFAULT_THRESHOLD}：{exc}",
              file=sys.stderr)
    return DEFAULT_THRESHOLD


def _git_changed_py_files() -> list[Path]:
    """返回 git 追踪的变更 .py 文件（staged + unstaged + untracked）。

    编码必须是 utf-8 而非平台默认：本仓 `core.quotePath=false`，git 直接输出
    UTF-8 原始字节；中文 Windows 的默认编码是 cp936，用 GBK 解码会抛
    UnicodeDecodeError，子进程读取线程随之崩溃并让 stdout 变成 None。
    调用方原先直接 .stdout.splitlines()，于是报
    `AttributeError: 'NoneType' object has no attribute 'splitlines'` ——
    只要有中文名的未跟踪文件（如 deliverables/ 下的报告），本门禁必然失败。
    errors="replace" 兜底：极端情况下宁可让文件名略有损，也不要让门禁崩掉。
    """
    try:
        # 已跟踪文件的改动
        tracked = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=AM", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=15,
        ).stdout.splitlines()
        # 暂存区的改动（含未提交新文件）
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=15,
        ).stdout.splitlines()
        # 未跟踪的新文件
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=15,
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
    parser.add_argument("--threshold", type=int, default=None,
                        help="行数阈值（默认取 pyproject.toml 的 max_file_size）")
    parser.add_argument("--all", action="store_true", help="全量扫描（默认 git 变更文件）")
    parser.add_argument("--fail", action="store_true",
                        help="全量模式下超限即失败（默认仅报告）")
    args = parser.parse_args()

    threshold = args.threshold if args.threshold is not None else _threshold_from_pyproject()
    args.threshold = threshold

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
