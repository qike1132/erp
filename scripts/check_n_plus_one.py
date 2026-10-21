# scripts/check_n_plus_one.py
"""
N+1 查询静态扫描脚本（AST based）

识别 `for` / `async for` 循环体**内**出现的 `await <obj>.execute/scalar/scalars` 调用，
这类模式在大数据量下会产生 N+1 次数据库往返，应改用 selectinload/joinedload 批量预加载
或 IN 批量查询 + defaultdict 内存分组。

以下情况**不**视为违规（2026-09-14 修正）：
1. 查询出现在循环的**可迭代表达式**里，如 `for x in (await db.execute(...)).all():`
   —— 该查询只求值一次，不是 N+1。此前被误报，现已修正。
2. 行内含**带理由**的豁免标注：`# batch-loop: <理由>` 或 `# n1-ok: <理由>`
   （仅写标记不写理由仍视为违规）

白名单 `scripts/allowed_n_plus_one.yaml` 支持三种键：
  - `path/to/file.py`                    —— 整个文件豁免（粗，慎用）
  - `path/to/file.py:123`                —— 指定行（**行号会随代码编辑漂移而失效**）
  - `path/to/file.py::function_name`     —— 指定函数（**推荐**，不随行号漂移）

用法:
    python scripts/check_n_plus_one.py [--whitelist scripts/allowed_n_plus_one.yaml] [路径...]

退出码:
    0: 未发现违规（或仅命中白名单），且白名单无僵尸键
    1: 发现违规，**或**白名单里有已失效的豁免键

（历史文档曾写「2: AST 解析失败」——本脚本从不返回 2：解析失败只打 [WARN] 并跳过该文件，
 与 check_function_length.py 的「解析失败 ≠ 无违规」口径不同，改动这里要一并核对。）

僵尸键（`zombie_whitelist_keys`）= 指向已删除文件 / 已改名函数 / 越界行号的豁免。
它们不报错、只静默失效，等于扫描面偷偷缩小，故与新增违规同等拦下。

任务来源: .codeartsdoer/specs/code_quality_opt/tasks.md 1.1
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import re
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


# 行内豁免标注：**必须附理由**，只写标记不写原因仍算违规。
# 项目既有约定是 `# batch-loop: 有意逐行处理,非 N+1`，此处一并支持 `# n1-ok:`。
_N1_MARKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#\s*batch-loop:\s*\S"),
    re.compile(r"#\s*n1-ok:\s*\S"),
)


def _has_justification(lines: list[str], start: int, end: int) -> bool:
    """检查调用表达式覆盖的所有行里是否带豁免理由（多行调用时标注常写在末尾行）。"""
    for idx in range(max(start - 1, 0), min(end, len(lines))):
        if any(p.search(lines[idx]) for p in _N1_MARKER_PATTERNS):
            return True
    return False


class NPlusOneVisitor(ast.NodeVisitor):
    """遍历单个模块，记录循环体内 await 包裹的查询调用。

    仅标记 `await <session>.execute/scalar/scalars(...)` 出现在 for/async for 循环**体**内的情况，
    这是真正的 N+1（每次迭代发起一次新 DB 查询）。
    - 排除遍历已执行结果的 `.scalars()`（非 await，仅迭代已有结果对象）
    - 排除出现在循环 iterable 表达式中的查询（只求值一次）
    - 排除带 `# batch-loop:` / `# n1-ok:` 理由标注的调用
    """

    def __init__(self, file_path: Path, source: str = "") -> None:
        self.file_path = file_path
        self.lines = source.splitlines()
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
        if _has_justification(
            self.lines,
            node.lineno,
            getattr(node, "end_lineno", node.lineno) or node.lineno,
        ):
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
        # 先访问 iter：循环的可迭代表达式只求值一次，不属于循环体。
        # 若放在 push 之后访问，`for x in (await db.execute(...)).all():` 会被误报为 N+1。
        self.visit(node.iter)
        # for/else 的 else 分支在循环正常结束后执行一次，同样不算循环体。
        for stmt in node.orelse:
            self.visit(stmt)

        loop_var = self._loop_target_name(node.target)
        self._loop_stack.append(loop_var)
        for stmt in node.body:
            self.visit(stmt)
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
    visitor = NPlusOneVisitor(path, source)
    visitor.visit(tree)
    return visitor.violations, None


def load_whitelist(yaml_path: Path | None) -> set[str]:
    """加载白名单。支持 file / file:line / file::function 三种键。无 PyYAML 依赖时按纯文本解析。"""
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
    """匹配顺序：文件级 → 精确行 → 函数级。

    函数级（`file::func`）不受行号漂移影响，是推荐的写法：
    此前白名单全部用 `file:line`，只要上游插入几行就整批失效（已实际发生）。
    """
    norm_file = v.file.replace("\\", "/")
    return (
        norm_file in whitelist
        or f"{norm_file}:{v.line}" in whitelist
        or f"{norm_file}::{v.function}" in whitelist
    )


def find_zombie_keys(whitelist: set[str], root: Path = PROJECT_ROOT) -> list[str]:
    """白名单里已经不生效的键：指向已删除的文件、已改名的函数、越界的行号。

    僵尸键不会报错，只会**静默失效**——豁免名单于是变成一份没人核对的历史包袱，
    而文件仍在时它曾压住的违规也会突然以"新增违规"的形式冒出来（更难归因）。
    与 scan_secrets 的 allowlist「只增不减」是同一类腐烂，故做成门禁而不是文档条目。
    """
    zombies: list[str] = []
    for key in sorted(whitelist):
        norm = key.replace("\\", "/")
        if "::" in norm:
            target, tail = norm.split("::", 1)
            kind = "func"
        elif ":" in norm:
            target, tail = norm.split(":", 1)
            kind = "line"
        else:
            target, tail, kind = norm, "", "file"
        path = root / target
        if not path.is_file():
            zombies.append(key)
            continue
        if kind == "file":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            zombies.append(key)
            continue
        if kind == "func":
            try:
                tree = ast.parse(source, filename=str(path))
            except SyntaxError:
                zombies.append(key)
                continue
            names = {
                n.name
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if tail not in names:
                zombies.append(key)
        elif not tail.isdigit() or int(tail) > len(source.splitlines()):
            zombies.append(key)
    return zombies


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
        # 文件路径原样传入（由 collect_py_files 处理）。
        # 曾退化为 pp.parent —— 那会让"只检查这一个文件"变成整目录扫描，
        # 产生与本次改动无关的违规（棘轮模式下表现为假 REGRESS）。
        scan_dirs.append(pp)
    if not scan_dirs:
        scan_dirs = DEFAULT_SCAN_DIRS

    whitelist = load_whitelist(args.whitelist)
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
        vs, err = scan_file(f)
        if err is not None:
            parse_errors.append((str(f.relative_to(PROJECT_ROOT)), err))
            continue
        all_violations.extend(vs)

    real_violations = [v for v in all_violations if not is_whitelisted(v, whitelist)]
    zombie_keys = find_zombie_keys(whitelist)

    if args.json:
        print(
            json.dumps(
                {
                    "violations": [v.to_dict() for v in real_violations],
                    "zombie_whitelist_keys": zombie_keys,
                    "parse_errors": parse_errors,
                    # 僵尸键不是 N+1 违规，但同样计入门禁总数：豁免名单烂掉必须和
                    # 新增违规一样拦下来（prod_audit 只读 violations，不受影响）。
                    "total": len(real_violations) + len(zombie_keys),
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
        if zombie_keys:
            print(
                f"[FAIL] 白名单有 {len(zombie_keys)} 个僵尸键（指向已删除文件/已改名函数/越界行号，"
                "豁免会静默失效）:"
            )
            for k in zombie_keys:
                print(f"  {k}")
        if not real_violations and not zombie_keys:
            print("[PASS] 未发现 N+1 查询风险（循环内 execute/scalar/scalars）")
            return 0
        if real_violations:
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

    return 1 if (real_violations or zombie_keys) else 0


if __name__ == "__main__":
    sys.exit(main())
