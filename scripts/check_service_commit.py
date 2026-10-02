#!/usr/bin/env python3
r"""Service 层事务提交检测（AST 语法级判定）

扫描 fastapi_app/services/ 下的 .py（跳过 test_*.py），用 ast 解析后判定：
凡是在 **db / session 结尾的基座**上调用 `.commit(...)`，一律报告。

判定完全来自语法树，**不再有正则白名单、也不看注释**：

1. 是不是一次调用：ast.Call + ast.Attribute(attr="commit")。
   - 只写 `db.commit`（方法引用、没有括号）不算调用，不报（与老版一致）。
   - 带参数 `await db.commit(force=True)` **算调用，照报**：老正则版要求空括号 `()`，
     那是一个可以绕过的缺口（P1-10② 一并闭合）。
2. 基座是谁：取基座表达式的最后一个标识符（db、self.db、storage_db、session、self.session）。
   以 db / session 结尾即视为数据库会话基座。
3. 既有安全形态：基座以 nested / short_session / _session 结尾时不报
   （嵌套事务、独立短会话；db_session 也落在 _session 里）。
   这些形态过去是 ALLOWED_PATTERNS 的白名单，AST 下不再需要匹配文本。

注释与字符串天然不参与判定：`# await db.commit()`、docstring 里的同名示例都不会报
（老正则版会把文档/字符串里的 `db.commit()` 文本误报成真实提交）。

保留的语义（老调用方不受影响）：
- 人类可读输出、退出码、--json 契约与 P0 版逐字一致：
  {"violations": [{"file", "line", "text"}], "total", "scan_dir"}。
- 例外标注 `# manual-tx: <理由><BT>> 仍然只是评审说明，不改变判定（例外必须持续可见，
  见 docs/TRANSACTION_BOUNDARY_GUIDE.md §2.2）。
- 读不了或解析不了的文件**不会静默放过**（fail-closed）：stderr 打印原因，退出码 2，
  --json 走与「路径不存在」同形状的 error 字段。

用法：
    python scripts/check_service_commit.py              # 人类可读报告
    python scripts/check_service_commit.py --json       # 机器可读（quality_gate.py 语义解析用）
    python scripts/check_service_commit.py --self-test  # 自检：正例/反例双向断言

退出码：
- 0：未发现非法 commit（或 --self-test 通过）
- 1：发现非法 commit（或 --self-test 失败）
- 2：环境异常（服务层目录缺失、文件无法读取或无法解析）
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import sys
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = PROJECT_ROOT / "fastapi_app" / "services"

# 失败提示引用的文档（docs/TRANSACTION_BOUNDARY_GUIDE.md 会回引本脚本，改路径要同步）
DOC_HINT = "docs/TRANSACTION_BOUNDARY_GUIDE.md"

# 基座名后缀（只作用于 AST 里取出的标识符，不接触源码文本）
DB_LIKE_SUFFIXES = ("db", "session")
SAFE_SUFFIXES = ("nested", "short_session", "_session")


class ParseError(RuntimeError):
    """文件读不了 / 语法错误：门禁无法判定，按 fail-closed 处理。"""

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


def _is_safe_base(name: str) -> bool:
    """既有安全形态：嵌套事务 / 独立短会话（含 *_session）。"""
    return name.endswith(SAFE_SUFFIXES)


def _is_db_like_base(name: str) -> bool:
    """数据库会话基座（db / session 结尾）。"""
    return name.endswith(DB_LIKE_SUFFIXES)


def _base_identifier(node: ast.AST) -> str | None:
    """取 `<base>.commit(...)` 中 base 的最后一个标识符。

    - db.commit()         -> "db"
    - self.db.commit()    -> "db"
    - storage_db.commit() -> "storage_db"
    - get_db().commit()   -> "get_db"（对调用结果取标识符）
    其他形态（下标、字面量等）返回 None，视为不匹配。
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _base_identifier(node.func)
    return None


def iter_commit_calls(tree: ast.AST) -> list[ast.Call]:
    """按源码顺序返回所有 `<base>.commit(...)` 调用节点。"""
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]
    calls.sort(key=lambda node: (node.lineno, node.col_offset))
    return calls


def find_suspicious_commits(file_path: Path) -> list[tuple[int, str]]:
    """扫描单个文件，返回 [(行号, 该行源码 strip 后文本), ...]。

    解析失败抛 ParseError（调用方按 fail-closed 处理，不静默跳过）。
    """
    try:
        source = file_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ParseError(file_path, f"读取失败：{exc}") from exc
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        raise ParseError(file_path, f"语法错误：第 {exc.lineno} 行 {exc.msg}") from exc

    lines = source.splitlines()
    issues: list[tuple[int, str]] = []
    for node in iter_commit_calls(tree):
        base = _base_identifier(node.func.value)
        if base is None or not _is_db_like_base(base) or _is_safe_base(base):
            continue
        lineno = node.lineno
        text = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
        issues.append((lineno, text))
    return issues


def scan_label(targets: list[Path]) -> str:
    """把扫描目标渲染成一行相对路径标签（供 --json 的 scan_dir 字段）。"""
    labels = []
    for target in targets:
        try:
            labels.append(target.relative_to(PROJECT_ROOT).as_posix())
        except ValueError:
            labels.append(target.as_posix())
    return ",".join(labels)


def scan_services(targets: list[Path] | None = None) -> list[tuple[str, int, str]]:
    """扫描服务层，返回 [(相对路径(POSIX), 行号, 行内容), ...]。

    targets 缺省为 [fastapi_app/services]；显式传入时用于自检/调试
    （quality_gate.py --probe-dir 会把范围换成临时目录）。
    任一文件无法解析都会抛出 ParseError，让门禁整体失败而不是漏报。
    """
    findings: list[tuple[str, int, str]] = []
    files: list[Path] = []
    for target in targets or [SERVICES_DIR]:
        if target.is_file():
            files.append(target)
        else:
            files.extend(sorted(target.rglob("*.py")))
    for py_file in files:
        if py_file.name.startswith("test_"):
            continue
        for lineno, line in find_suspicious_commits(py_file):
            try:
                rel = py_file.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                rel = py_file.as_posix()
            findings.append((rel, lineno, line))
    return findings


def report_json(findings: list[tuple[str, int, str]], scan_dir: str) -> None:
    """机器可读输出：stdout 恰好一个 JSON 对象（quality_gate.py 只认它，不抠文本）。"""
    payload = {
        "violations": [
            {"file": file, "line": lineno, "text": text}
            for file, lineno, text in findings
        ],
        "total": len(findings),
        "scan_dir": scan_dir,
    }
    print(json.dumps(payload, ensure_ascii=False))


def report_human(findings: list[tuple[str, int, str]]) -> int:
    if not findings:
        print("[PASS] 未在 service 层发现非法 commit()")
        return 0

    print(f"[FAIL] 在 service 层发现 {len(findings)} 处非法 commit()：\n")
    for file, lineno, line in findings:
        print(f"  {file}:{lineno}: {line}")

    print(f"\n请按 {DOC_HINT} 规范进行改造。")
    return 1


def _probe(tmpdir: Path, name: str, body: str) -> Path:
    path = tmpdir / name
    path.write_text(body, encoding="utf-8")
    return path


def _probe_hits(tmpdir: Path, body: str, name: str = "probe.py") -> list[tuple[int, str]]:
    """写一个探针文件并返回 AST 判定结果（供自检的正例/反例断言）。"""
    return find_suspicious_commits(_probe(tmpdir, name, body))


def _selftest_basics(tmpdir: Path) -> list[tuple[str, bool, str]]:
    cases: list[tuple[str, bool, str]] = []

    n = len(_probe_hits(
        tmpdir,
        "async def f(db):\n    await db.commit()  # independent-transaction; manual-tx: 旧写法\n",
        "p_independent.py",
    ))
    cases.append(("正例：行内 independent-transaction 不再豁免", n == 1, f"命中 {n} 处"))

    n = len(_probe_hits(
        tmpdir, "async def f(db):\n    await db.commit()  # 顺手 commit(一下)\n", "p_inline.py"
    ))
    cases.append(("正例：行内含 commit( 不再豁免整行", n == 1, f"命中 {n} 处"))

    n = len(_probe_hits(
        tmpdir,
        "async def f(db):\n    await db.commit()  # manual-tx: 有正经理由也必须继续可见\n",
        "p_manual.py",
    ))
    cases.append(("正例：manual-tx 标注不豁免（例外持续可见）", n == 1, f"命中 {n} 处"))

    n = len(_probe_hits(
        tmpdir, "async def f(db):\n    # await db.commit()\n    return 1\n", "p_wholeline.py"
    ))
    cases.append(("反例：整行注释不算代码", n == 0, f"命中 {n} 处"))

    n = len(_probe_hits(
        tmpdir,
        "async def f(db, nested, short_session, _session, row_nested, db_session):\n"
        "    await nested.commit()\n"
        "    await short_session.commit()\n"
        "    await _session.commit()\n"
        "    await row_nested.commit()\n"
        "    await db_session.commit()\n",
        "p_safe.py",
    ))
    cases.append(
        ("反例：nested / short_session / _session / db_session 基座豁免", n == 0, f"命中 {n} 处")
    )

    lines = [ln for ln, _ in _probe_hits(
        tmpdir, "async def f(db):\n    await db.flush()\n    await db.commit()\n", "p_lineno.py"
    )]
    cases.append(("正例：行号准确", lines == [3], f"行号={lines}"))

    n = len(_probe_hits(
        tmpdir,
        "async def f(db):\n"
        '    """老写法示例：await db.commit() 已废弃。"""\n'
        '    note = "await db.commit()"\n'
        "    return note\n",
        "p_text.py",
    ))
    cases.append(
        ("反例：docstring / 字符串里的 db.commit() 文本不算违规", n == 0, f"命中 {n} 处")
    )

    n = len(_probe_hits(
        tmpdir, "async def f(db):\n    await db.commit(force=True)\n", "p_args.py"
    ))
    cases.append(("正例：db.commit(force=True) 也判定为违规", n == 1, f"命中 {n} 处"))

    n = len(_probe_hits(
        tmpdir,
        "async def f(self, storage_db):\n"
        "    await self.session.commit()\n"
        "    await storage_db.commit()\n",
        "p_bases.py",
    ))
    cases.append(("正例：self.session / storage_db 基座同样判定", n == 2, f"命中 {n} 处"))

    n = len(_probe_hits(
        tmpdir,
        "async def f(db, session, conn):\n"
        "    await db.flush()\n"
        "    await db.rollback()\n"
        "    await session.execute('select 1')\n"
        "    db.commit\n"
        "    await conn.commit()\n",
        "p_negative.py",
    ))
    cases.append(
        ("反例：flush/rollback/execute/方法引用/conn 基座均不报", n == 0, f"命中 {n} 处")
    )

    broken = _probe(tmpdir, "p_broken.py", "async def f(db:\n    await db.commit()\n")
    try:
        find_suspicious_commits(broken)
        detail = "未抛出 ParseError（漏报了不可解析文件）"
        ok = False
    except ParseError as exc:
        ok = "语法错误" in str(exc)
        detail = f"ParseError：{exc.detail}"
    cases.append(("fail-closed：语法错误文件抛 ParseError", ok, detail))

    return cases


def _selftest_module_guards() -> list[tuple[str, bool, str]]:
    """模块级守卫：退役旁路不得复活 + 真实树扫描不得静默为空。"""
    cases: list[tuple[str, bool, str]] = []
    module = sys.modules[__name__]
    leftovers = [
        name for name in ("ALLOWED_PATTERNS", "SUSPICIOUS_PATTERNS") if hasattr(module, name)
    ]
    cases.append(("退役旁路未复活（无正则/注释白名单常量）", not leftovers, f"残留={leftovers}"))

    cases.append((
        "服务层目录存在",
        SERVICES_DIR.is_dir(),
        SERVICES_DIR.relative_to(PROJECT_ROOT).as_posix(),
    ))

    real = scan_services()
    located = all(
        (PROJECT_ROOT / file).is_file() and "commit" in text for file, _, text in real
    )
    # 断言只验证「判定逻辑正确」，不与仓库存量耦合：此前要求 bool(real) 为真，
    # 于是团队把违规整改到 0 处时自检反而 FAIL（CI 的 --self-test 变红）——
    # 恰好在做对了的时候报错。空列表时 all() 为 True，语义正确。
    cases.append((
        "真实服务层扫描命中可回溯（0 处也通过）",
        located,
        f"实扫 {len(real)} 处",
    ))
    return cases


def _selftest_cases() -> list[tuple[str, bool, str]]:
    """自检用例：正例（该报必须报）+ 反例（不该报必须不报）+ fail-closed + 模块守卫。"""
    with tempfile.TemporaryDirectory(prefix="csc-selftest-") as tmp:
        cases = _selftest_basics(Path(tmp))
    cases.extend(_selftest_module_guards())
    return cases


def run_self_test() -> int:
    print("[SELFTEST] check_service_commit.py 自检（AST 判定）")
    ok = True
    cases = _selftest_cases()
    for name, passed, detail in cases:
        flag = "PASS" if passed else "FAIL"
        suffix = f"（{detail}）" if detail else ""
        print(f"[SELFTEST] {flag} {name}{suffix}")
        ok = ok and passed
    print(f"[SELFTEST] {'全部通过' if ok else '存在失败项'}：{len(cases)} 项")
    return 0 if ok else 1


def _emit_error(message: str, as_json: bool) -> int:
    """fail-closed 出口：--json 与「路径不存在」同形状；人类模式同时写 stderr。"""
    if as_json:
        print(json.dumps({"violations": [], "total": 0, "error": message}, ensure_ascii=False))
    else:
        print(f"[ERROR] {message}")
    print(f"[ERROR] {message}", file=sys.stderr)
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="service 层非法 commit() 检测（门禁，AST 判定）")
    parser.add_argument(
        "paths",
        nargs="*",
        help="待扫描目录/文件（缺省 fastapi_app/services；自检/调试时可覆盖）",
    )
    parser.add_argument(
        "--json", action="store_true", help="机器可读输出（供 quality_gate.py 语义解析）"
    )
    parser.add_argument("--self-test", action="store_true", help="自检：正例/反例双向断言")
    args = parser.parse_args()

    if args.self_test:
        return run_self_test()

    targets = [Path(p).resolve() for p in args.paths] or [SERVICES_DIR]
    missing = [t for t in targets if not t.exists()]
    if missing:
        return _emit_error(f"路径不存在: {[str(t) for t in missing]}", args.json)

    try:
        findings = scan_services(targets)
    except ParseError as exc:
        return _emit_error(f"无法解析文件，门禁 fail-closed：{exc}", args.json)

    if args.json:
        report_json(findings, scan_label(targets))
        return 1 if findings else 0
    return report_human(findings)


if __name__ == "__main__":
    sys.exit(main())
