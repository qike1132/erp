#!/usr/bin/env python3
"""文件规模门禁（CI 用）：防止新增"上帝类"。

设计原则：
- 默认只检查 **git 变更文件**（modified/added 的 .py），存量超限文件不阻断，
  使门禁可立即在 CI 启用而不会让历史遗留问题卡住流水线。
- CI 里须用 ``--base origin/<base_branch>`` 对比 **PR 基线**：CI 是干净检出，
  ``git diff HEAD``（工作树 vs HEAD）恒为空 ⇒ 门禁空转。对比基线才能取到变更集，
  仓库根与 ``server_manager/`` 也随之进入扫描范围。
- **显式指定的 ``--base <ref>`` 解析不了时一律失败（退出码 1），不回落跳过**：
  静默跳过正是本门禁历史上"半交付"的成因 —— CI 少了 ``fetch-depth: 0``、基线与
  远端分支名不符、分支改名，都会让它悄悄退化成空转却报绿（2026-09-28 实测确认）。
  push 事件本就没有 ``base_ref``，由 CI 那侧改走 ``--all`` 报告路径（见 ci-cd.yml），
  不再传 ``--base``；「无变更文件」的正常跳过只保留给解析得通的基线。
- 新增/修改的文件超过阈值即失败（退出码 1）。阈值单一来源是
  `pyproject.toml` 的 `[tool.code-quality] max_file_size`；解析不到才回落到
  本脚本的 DEFAULT_THRESHOLD。此前该值在 pyproject / 本脚本 / CI workflow
  各写一份，改一处必漏两处。
- 本地无 git 或需全量扫描时用 --all 模式。

用法：
    python scripts/file_size_gate.py                # git 变更文件，阈值取 pyproject
    python scripts/file_size_gate.py --base origin/main   # 对比基线 ref 取变更(CI 用)
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
#            + 仓库根顶层 .py + 桌面壳包 server_manager/（全仓最大 .py 的所在）
#            + 前端源码（评审 2026-10-11：此前只扫 .py，前端手写大文件不受任何体积门禁）
SCAN_DIRS = ("fastapi_app", "tests", "utils", "scripts", "server_manager")
EXCLUDE_DIRS = {"__pycache__", ".archive", "migrations"}
SCAN_EXTS = (".py", ".ts", ".vue")
FRONTEND_SRC = "frontend-vite/src"
# 生成产物不受「上帝类」门禁约束：api.d.ts 由 `npm run generate-api-types` 生成，
# 体积由 OpenAPI 决定、非人写，纳入门禁会让每次重新生成都失败。
GENERATED_EXCLUDE = {"frontend-vite/src/types/api.d.ts"}

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


def _is_scanned(path: str) -> bool:
    """变更文件是否纳入扫描：.py 全收；.ts/.vue 仅前端 src（排除 node_modules）。"""
    p = path.replace("\\", "/")
    if p.endswith(".py"):
        return True
    return (
        p.endswith((".ts", ".vue"))
        and p.startswith(FRONTEND_SRC + "/")
        and "node_modules" not in p
    )


def _parse_name_status(lines: list[str]) -> list[str]:
    """解析 --name-status：A/M 取路径；R<score> 纯改名（R100）豁免、改动型改名取新路径。"""
    out: list[str] = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status.startswith("R"):
            try:
                score = int(status[1:] or "100")
            except ValueError:
                score = 100
            if score >= 100:
                continue  # 纯改名不改变文件规模；门禁只拦「新增/修改后超限」
            out.append(parts[2] if len(parts) > 2 else parts[1])
        elif status[:1] in ("A", "M"):
            out.append(parts[1])
    return out


def _git_changed_py_files(base: str = "HEAD") -> list[Path]:
    """返回 git 变更的 .py 文件。

    ``base == "HEAD"``（默认）：比较**工作树 vs HEAD** —— staged + unstaged +
      untracked，供本地与 pre-commit 用。
    ``base != "HEAD"``：比较**基线 ref vs HEAD** ——
      ``git diff --diff-filter=AM <base>...HEAD``（三点语法取 merge-base，即「相对
      基线新增/修改」的文件），供 CI 用。CI 是干净检出，工作树 == HEAD，原逻辑
      恒为空（空转）；对比 PR 基线（``origin/<base_branch>``）才能取到真正的变更集。

    编码必须是 utf-8 而非平台默认：本仓 `core.quotePath=false`，git 直接输出
    UTF-8 原始字节；中文 Windows 的默认编码是 cp936，用 GBK 解码会抛
    UnicodeDecodeError，子进程读取线程随之崩溃并让 stdout 变成 None。
    调用方原先直接 .stdout.splitlines()，于是报
    `AttributeError: 'NoneType' object has no attribute 'splitlines'` ——
    只要有中文名的未跟踪文件（如 deliverables/ 下的报告），本门禁必然失败。
    errors="replace" 兜底：极端情况下宁可让文件名略有损，也不要让门禁崩掉。
    """
    def _run_git(args: list[str]) -> list[str]:
        try:
            return subprocess.run(
                ["git", *args], capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False, timeout=15,
            ).stdout.splitlines()
        except (subprocess.SubprocessError, OSError):
            return []

    if base != "HEAD":
        # F3-1：--diff-filter=AM 漏掉 R（改名），rename+扩容可绕过门禁；改 AMR 后
        # 纯改名 R100 豁免（规模未变），R0xx（改名同时修改）按新路径扫描。
        changed = _parse_name_status(
            _run_git(["diff", "--name-status", "--diff-filter=AMR", f"{base}...HEAD"])
        )
        return [Path(p) for p in dict.fromkeys(changed) if _is_scanned(p)]

    # 已跟踪文件的改动
    tracked = _parse_name_status(
        _run_git(["diff", "--name-status", "--diff-filter=AMR", "HEAD"])
    )
    # 暂存区的改动（含未提交新文件）
    staged = _parse_name_status(
        _run_git(["diff", "--cached", "--name-status", "--diff-filter=AMR"])
    )
    # 未跟踪的新文件
    untracked = _run_git(["ls-files", "--others", "--exclude-standard"])
    return [Path(p) for p in dict.fromkeys(tracked + staged + untracked) if _is_scanned(p)]


def _ref_resolves(ref: str) -> bool:
    """``ref`` 能否解析为一个 commit。

    用于把「基线 ref 不存在」（配置/检出问题，必须响亮失败）与「基线存在但变更集
    为空」（正常，跳过）区分开 —— 此前两者都落到「无扫描文件…跳过」+ 退出码 0，
    使门禁可被静默废掉而 CI 仍报绿。
    """
    try:
        return subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
            capture_output=True, timeout=15, check=False,
        ).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


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
    # 顶层 .py(仓库根):此前遗漏,导致拆包前全仓最大的 server_manager.py 逃过门禁。
    # 只取顶层,不递归 —— 否则会扫进 frontend-vite/node_modules 等非 Python 目录。
    for p in PROJECT_ROOT.glob("*.py"):
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        files.append(p)
    # 前端源码（.ts/.vue），排除 node_modules
    frontend = PROJECT_ROOT / FRONTEND_SRC
    if frontend.is_dir():
        for p in frontend.rglob("*"):
            if p.is_file() and p.suffix in (".ts", ".vue") and "node_modules" not in p.parts:
                files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=int, default=None,
                        help="行数阈值（默认取 pyproject.toml 的 max_file_size）")
    parser.add_argument("--all", action="store_true", help="全量扫描（默认 git 变更文件）")
    parser.add_argument("--base", default="HEAD", metavar="REF",
                        help="对比的 git 基线 ref；默认 HEAD（工作树 vs HEAD）。"
                             "CI 传 origin/<base_branch> 以取 PR 变更集")
    parser.add_argument("--fail", action="store_true",
                        help="全量模式下超限即失败（默认仅报告）")
    args = parser.parse_args()

    threshold = args.threshold if args.threshold is not None else _threshold_from_pyproject()
    args.threshold = threshold

    # 显式给了基线却解析不了 ⇒ 响亮失败，绝不空转。默认 HEAD（工作树 vs HEAD）与
    # --all 不受影响：前者是本地/pre-commit 用法，后者是报告用法。
    if not args.all and args.base != "HEAD" and not _ref_resolves(args.base):
        print(f"[file-size-gate] 基线 ref 无法解析：{args.base!r}", file=sys.stderr)
        print("[file-size-gate] 门禁拒绝空转：CI 缺 fetch-depth: 0、基线分支名不符或"
              "分支已改名都会走到这里。", file=sys.stderr)
        return 1

    files = _all_py_files() if args.all else _git_changed_py_files(args.base)
    if not files:
        mode = "all" if args.all else f"git-diff(base={args.base})"
        print(f"[file-size-gate] 无扫描文件（{mode} 模式），跳过")
        return 0

    over: list[tuple[Path, int]] = []
    for f in files:
        # 生成产物不受上帝类门禁约束。--all 给的是绝对路径、git 模式给的是相对路径，
        # 统一转 posix 斜杠后按「以排除项结尾」比对。
        norm = f.as_posix().replace("\\", "/")
        if any(norm.endswith(ex) for ex in GENERATED_EXCLUDE):
            continue
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
    # 措辞必须与真实退出码一致：--all 不加 --fail 时只报告、退出 0，此前却打印
    # 「失败…（--fail）」——门禁自己说谎，与本文件要消灭的"假绿"同类。
    failing = (not args.all) or args.fail
    print(f"[file-size-gate] {'失败' if failing else '仅报告(未加 --fail)'}："
          f"{len(over)} 个文件超过 {args.threshold} 行"
          f"{'，请拆分后合入' if failing else ''}")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
