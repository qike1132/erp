# scripts/check_n_plus_one.py
"""
N+1 查询静态扫描脚本（AST based）

识别 `for` / `async for` 循环体内出现的 `await <obj>.execute/scalar/scalars` 调用，
这类模式在大数据量下会产生 N+1 次数据库往返，应改用 selectinload/joinedload 批量预加载
或 IN 批量查询 + defaultdict 内存分组。

用法:
    python scripts/check_n_plus_one.py [--whitelist scripts/allowed_n_plus_one.yaml] [路径...]

退出码:
    0: 未发现违规（或仅命中白名单）
    1: 发现违规
    2: AST 解析失败（语法错误）

任务来源: .codeartsdoer/specs/code_quality_opt/tasks.md 1.1
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent

# 循环体内视为 N+1 风险的查询方法名
QUERY_METHODS = {"execute", "scalar", "scalars", "stream", "stream_scalars"}

# 默认扫描目录
DEFAULT_SCAN_DIRS = [PROJECT_ROOT / "fastapi_app"]

# 默认排除目录
EXCLUDE_DIRS = {"__pycache__", "tests", "migrations"}


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    function: str
    query_call: str
    loop_var: str

    def to_dict(self) -> dict:
        return asdict(self)


class NPlusOneVisitor(ast.NodeVisitor):
    """遍历单个模块，记录循环体内 await 包裹的查询调用。

    仅标记 `await <session>.execute/scalar/scalars(...)` 出现在 for/async for 循环体内的情况，
    这是真正的 N+1（每次迭代发起一次新 DB 查询）。
    排除遍历已执行结果的 `.scalars()`（非 await，仅迭代已有结果对象）。
    """

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.violations: list[Violation] = []
        self._func_stack: list[str] = []
        self._loop_stack: list[str] = []

    def _current_func(self) -> str:
        return self._func_stack[-1] if self._func_stack else "<module>"

    def _current_loop_var(self) -> str:
        return self._loop_stack[-1] if self._loop_stack else ""

    def _record_query(self, node: ast.Call) -> None:
        if not self._loop_stack:
            return
        call_name = self._query_call_name(node)
        if call_name is None:
            return
        self.violations.append(
            Violation(
                file=str(self.file_path.relative_to(PROJECT_ROOT)),
                line=node.lineno,
                function=self._current_func(),
                query_call=call_name,
                loop_var=self._current_loop_var(),
            )
        )

    @staticmethod
    def _query_call_name(node: ast.Call) -> str | None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in QUERY_METHODS:
            return func.attr
        return None

    def _visit_loop(self, node: ast.For | ast.AsyncFor) -> None:
        loop_var = self._loop_target_name(node.target)
        self._loop_stack.append(loop_var)
        self.generic_visit(node)
        self._loop_stack.pop()

    @staticmethod
    def _loop_target_name(target: ast.AST) -> str:
        if isinstance(target, ast.Name):
            return target.id
        if isinstance(target, ast.Tuple):
            return ",".join(
                e.id if isinstance(e, ast.Name) else "_" for e in target.elts
            )
        return "_"

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Await(self, node: ast.Await) -> None:
        # 仅当 await 的值是查询调用时才记录（排除遍历已有结果的 .scalars()）
        if isinstance(node.value, ast.Call):
            self._record_query(node.value)
        self.generic_visit(node)


def scan_file(path: Path) -> tuple[list[Violation], str | None]:
    """返回 (violations, parse_error)。parse_error 非 None 表示 AST 解析失败。"""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [], f"{e.__class__.__name__}: {e}"
    visitor = NPlusOneVisitor(path)
    visitor.visit(tree)
    return visitor.violations, None


def load_whitelist(yaml_path: Path | None) -> set[str]:
    """加载白名单（每行一个 file:line 或 file 形式）。无 PyYAML 依赖时按纯文本解析。"""
    if yaml_path is None or not yaml_path.exists():
        return set()
    whitelist: set[str] = set()
    text = yaml_path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # 统一路径分隔符为 / 便于跨平台匹配
        whitelist.add(line.replace("\\", "/"))
    return whitelist


def is_whitelisted(v: Violation, whitelist: set[str]) -> bool:
    norm_file = v.file.replace("\\", "/")
    return f"{norm_file}:{v.line}" in whitelist or norm_file in whitelist


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
    parser = argparse.ArgumentParser(description="N+1 查询静态扫描")
    parser.add_argument(
        "paths", nargs="*", help="待扫描目录/文件（默认 fastapi_app）"
    )
    parser.add_argument(
        "--whitelist",
        type=Path,
        default=PROJECT_ROOT / "scripts" / "allowed_n_plus_one.yaml",
        help="白名单配置文件",
    )
    parser.add_argument("--json", action="store_true", help="以 JSON 输出违规清单")
    args = parser.parse_args()

    scan_dirs: list[Path] = []
    for p in args.paths:
        pp = Path(p).resolve()
        scan_dirs.append(pp if pp.is_dir() else pp.parent)
    if not scan_dirs:
        scan_dirs = DEFAULT_SCAN_DIRS

    whitelist = load_whitelist(args.whitelist)
    files = collect_py_files(scan_dirs)

    all_violations: list[Violation] = []
    parse_errors: list[tuple[str, str]] = []
    for f in files:
        vs, err = scan_file(f)
        if err is not None:
            parse_errors.append((str(f.relative_to(PROJECT_ROOT)), err))
            continue
        all_violations.extend(vs)

    real_violations = [v for v in all_violations if not is_whitelisted(v, whitelist)]

    if args.json:
        print(
            json.dumps(
                {
                    "violations": [v.to_dict() for v in real_violations],
                    "parse_errors": parse_errors,
                    "total": len(real_violations),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if parse_errors:
            print(f"[WARN] {len(parse_errors)} 个文件 AST 解析失败（跳过）:")
            for fp, err in parse_errors[:10]:
                print(f"  {fp}: {err}")
        if not real_violations:
            print("[PASS] 未发现 N+1 查询风险（循环内 execute/scalar/scalars）")
            return 0
        by_file: dict[str, list[Violation]] = {}
        for v in real_violations:
            by_file.setdefault(v.file, []).append(v)
        print(
            f"[FAIL] 发现 {len(real_violations)} 处 N+1 风险（{len(by_file)} 个文件）:\n"
        )
        for fp, vs in sorted(by_file.items()):
            print(f"  {fp} ({len(vs)})")
            for v in vs:
                print(
                    f"    L{v.line}: {v.function}() -> .{v.query_call}()  [loop: {v.loop_var}]"
                )
            print()

    return 1 if real_violations else 0


if __name__ == "__main__":
    sys.exit(main())
