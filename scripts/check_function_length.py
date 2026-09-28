# scripts/check_function_length.py
"""
后端函数行数检测脚本（AST based）

统计每个 async def/def 的有效行数（剔除空行与纯注释行），
超过阈值（默认 80 行）视为超长函数，应按职责拆分。

用法:
    python scripts/check_function_length.py [--max-length 80] [路径...]

退出码:
    0: 未发现超长函数
    1: 发现超长函数
    2: 有文件无法解析为 Python AST（门禁失败，"解析失败 ≠ 无违规"）

任务来源: .codeartsdoer/specs/code_quality_opt/tasks.md 1.2
"""
from __future__ import annotations

import argparse
import ast
import io
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
# 默认扫描 fastapi_app(后端源码) + server_manager(桌面壳包,此前整包逃过门禁)
# + 仓库根顶层 .py(桌面壳入口等)。
DEFAULT_SCAN_DIRS = [
    PROJECT_ROOT / "fastapi_app",
    PROJECT_ROOT / "server_manager",
    PROJECT_ROOT,
]
EXCLUDE_DIRS = {"__pycache__", "tests", "migrations"}


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    function: str
    length: int

    def to_dict(self) -> dict:
        return asdict(self)


def _effective_length(lines: list[str], start: int, end: int) -> int:
    """统计 [start, end) 行的有效行数（剔除空行与纯注释行）。"""
    count = 0
    for i in range(start, min(end, len(lines))):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        count += 1
    return count


class FunctionLengthVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path, lines: list[str], max_length: int) -> None:
        self.file_path = file_path
        self.lines = lines
        self.max_length = max_length
        self.violations: list[Violation] = []

    def _check(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        start = node.lineno - 1
        end = node.end_lineno or len(self.lines)
        length = _effective_length(self.lines, start, end)
        if length > self.max_length:
            self.violations.append(
                Violation(
                    file=str(self.file_path.relative_to(PROJECT_ROOT)),
                    line=node.lineno,
                    function=node.name,
                    length=length,
                )
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


def scan_file(path: Path, max_length: int) -> tuple[list[Violation], str | None]:
    """返回 (违规列表, 解析错误)。

    解析失败必须显式上报——静默返回空会让"有语法错误的文件"被报告为
    "无违规"（假绿），而这类文件恰恰最需要被拦住。
    """
    try:
        # utf-8-sig 容忍 BOM：仓库根曾有几个带 U+FEFF 的探针脚本，用 utf-8 读会让
        # ast.parse 抛「invalid non-printable character U+FEFF」→ 整个文件被跳过。
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, OSError) as exc:
        return [], str(exc)
    lines = source.splitlines()
    visitor = FunctionLengthVisitor(path, lines, max_length)
    visitor.visit(tree)
    return visitor.violations, None


def collect_py_files(scan_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in scan_dirs:
        if not d.exists():
            continue
        # 显式传入单个文件时必须真的扫它。
        # 否则 Path(file).rglob("*.py") 返回空 → 静默 PASS（假绿），比报错更危险。
        if d.is_file():
            if d.suffix == ".py" and not any(part in EXCLUDE_DIRS for part in d.parts):
                files.append(d)
            continue
        # 仓库根只取**顶层** *.py：否则 rglob 会递归进 frontend-vite/node_modules
        # 等非 Python 目录，把门禁拖慢到不可用。
        if d.resolve() == PROJECT_ROOT.resolve():
            candidates = d.glob("*.py")
        else:
            candidates = d.rglob("*.py")
        for p in candidates:
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            files.append(p)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="后端函数行数检测")
    parser.add_argument("paths", nargs="*", help="待扫描目录/文件")
    parser.add_argument("--max-length", type=int, default=80, help="函数最大行数阈值")
    args = parser.parse_args()

    scan_dirs = [Path(p).resolve() for p in args.paths] or DEFAULT_SCAN_DIRS
    files = collect_py_files(scan_dirs)

    # 显式传了路径却一个文件都没扫到 → 静默 PASS 会造成"假绿"，必须让人看见
    if args.paths and not files:
        print(
            f"[WARN] 传入的路径未匹配到任何可扫描的 .py 文件：{[str(p) for p in args.paths]}",
            file=sys.stderr,
        )

    all_violations: list[Violation] = []
    parse_errors: list[tuple[str, str]] = []
    for f in files:
        violations, err = scan_file(f, args.max_length)
        if err is not None:
            parse_errors.append((str(f.relative_to(PROJECT_ROOT)), err))
            continue
        all_violations.extend(violations)

    if parse_errors:
        # 解析失败必须**响亮失败**：一个连 AST 都读不了的文件被报成「无违规」正是本仓库
        # 反复出现的「假绿」类缺陷。但注意 quality_gate.py 用 ``[FAIL]…数字 处/个`` 从本
        # 脚本输出里抠违规计数，并把「小于等于基线」当作未新增 —— 故这里的失败标记
        # **绝不能**是「[FAIL] + 数字 + 处/个」的形式（会被误当成「违规变少=改善」）。
        # 这里既不打印 [PASS]，也不打印 [FAIL]计数行，直接以独立退出码 2 结束：
        # quality_gate 解析不到计数即保守判失败（hard_failure），不会被误读成改善。
        print(
            f"[PARSE-ERROR] {len(parse_errors)} 个文件无法解析为 Python AST，门禁失败"
            "（解析失败 ≠ 无违规）:",
            file=sys.stderr,
        )
        for rel, err in parse_errors[:10]:
            print(f"  {rel}: {err}", file=sys.stderr)
        return 2

    if not all_violations:
        print(f"[PASS] 未发现超过 {args.max_length} 行的函数")
        return 0

    by_file: dict[str, list[Violation]] = {}
    for v in all_violations:
        by_file.setdefault(v.file, []).append(v)

    print(
        f"[FAIL] 发现 {len(all_violations)} 个超长函数（>{args.max_length} 行，{len(by_file)} 个文件）:\n"
    )
    for fp, vs in sorted(by_file.items()):
        print(f"  {fp} ({len(vs)})")
        for v in sorted(vs, key=lambda x: -x.length):
            print(f"    L{v.line}: {v.function}() = {v.length} 行")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
