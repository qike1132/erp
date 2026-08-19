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
DEFAULT_SCAN_DIRS = [PROJECT_ROOT / "fastapi_app"]
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


def scan_file(path: Path, max_length: int) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    lines = source.splitlines()
    visitor = FunctionLengthVisitor(path, lines, max_length)
    visitor.visit(tree)
    return visitor.violations


def collect_py_files(scan_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for d in scan_dirs:
        if not d.exists():
            continue
        for p in d.rglob("*.py"):
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

    all_violations: list[Violation] = []
    for f in files:
        all_violations.extend(scan_file(f, args.max_length))

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
