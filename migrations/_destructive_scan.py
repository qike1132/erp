"""迁移文件「破坏性 DDL」静态扫描器。

用途
----
`test_migration_autogenerate_safety.py` 依赖本模块，对 `migrations/versions/`
下每个迁移文件做 AST 扫描，提取其中的破坏性 DDL 调用（DROP TABLE/INDEX/COLUMN/
CONSTRAINT 等），与 `migrations/destructive_ddl_baseline.json` 基线比对：
**新增的破坏性语句即判失败**（棘轮 ratchet，允许清理减少、不允许悄悄新增）。

为什么需要它
------------
`alembic revision --autogenerate` 若误连生产库，会依据生产库的历史堆积生成
一批 `DROP INDEX` / `DROP TABLE` / `DROP COLUMN`（都是「库有、模型无」的对象）。
这些语句一旦提交就会在别处重放成破坏性 DDL。本扫描在**提交前**把它们拦下：
新出现的破坏性语句必须先人工审阅，再显式更新基线。

基线更新
--------
    python -m migrations._destructive_scan --update-baseline

仅在**确已人工审阅**这些破坏性语句后执行；更新基线的提交须说明理由。

已知局限
--------
仅扫描 AST 字面量（含 `op.execute(text("..."))` 包裹的那一层），不追踪变量/拼接出的
SQL；把 DDL 先存进变量再传入的写法无法识别。autogenerate 产出的都是字面量
（`op.drop_index('x', ...)` / `op.execute("DROP ...")`），故主要威胁已被覆盖。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
BASELINE_PATH = REPO_ROOT / "migrations" / "destructive_ddl_baseline.json"

# 直接调用（op.<name> 或裸名）即构成破坏性 DDL 的函数名
_DESTRUCTIVE_CALLS = frozenset({
    "drop_table",
    "drop_index",
    "drop_column",
    "drop_constraint",
    # migrations/_legacy_base_guard.py 提供的带守卫包装，语义同样是删除
    "drop_table_if_exists",
    "drop_table_if_empty",
    "drop_index_if_exists",
    "drop_column_if_absent",
    "drop_column_if_exists",
    "drop_constraint_if_exists",
})

# 裸 SQL（op.execute("DROP ...")）的识别关键字
_RAW_SQL_CALLS = frozenset({"execute"})


def _callee_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _string_args(node: ast.Call, limit: int = 2) -> list[str]:
    """提取调用的字符串实参；对 `text("...")` / `sa.text("...")` 包裹的再解一层。

    裸 SQL 常写作 `op.execute(text("DROP ..."))` —— 字符串在 `text(...)` 调用里，
    不是 `execute` 的直接实参，故需下钻一层，否则会漏掉这类破坏性 DDL。
    """
    out: list[str] = []
    for arg in node.args:
        value: str | None = None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            value = arg.value
        elif isinstance(arg, ast.Call) and _callee_name(arg) == "text":
            for inner in arg.args:
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    value = inner.value
                    break
        if value is not None:
            out.append(" ".join(value.split()))
        if len(out) >= limit:
            break
    return out


def scan_source(source: str) -> list[str]:
    """返回一段迁移源码里的破坏性 DDL 签名列表（已排序去重）。"""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node)
        if name is None:
            continue
        if name in _DESTRUCTIVE_CALLS:
            args = _string_args(node)
            found.add(f"{name}:{'|'.join(args)}")
        elif name in _RAW_SQL_CALLS:
            for sql in _string_args(node, limit=1):
                upper = sql.upper().lstrip("(")
                if upper.startswith("DROP") or " DROP " in upper:
                    found.add(f"execute:{sql[:80]}")
    return sorted(found)


def scan_versions_dir(versions_dir: Path | None = None) -> dict[str, list[str]]:
    """扫描 `migrations/versions/*.py`，返回 {相对路径: [破坏性签名...]}（仅含非空项）。"""
    versions_dir = versions_dir or VERSIONS_DIR
    result: dict[str, list[str]] = {}
    for path in sorted(versions_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        sigs = scan_source(path.read_text(encoding="utf-8"))
        if sigs:
            rel = path.relative_to(REPO_ROOT).as_posix()
            result[rel] = sigs
    return result


def load_baseline(path: Path | None = None) -> dict[str, list[str]]:
    path = path or BASELINE_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("files", {})


def find_new_destructive_ops(
    current: dict[str, list[str]], baseline: dict[str, list[str]]
) -> dict[str, list[str]]:
    """返回「相对基线新增」的破坏性语句（按文件）。基线里多出的（已清理）不算问题。"""
    new: dict[str, list[str]] = {}
    for file, sigs in current.items():
        allowed = set(baseline.get(file, []))
        extra = [s for s in sigs if s not in allowed]
        if extra:
            new[file] = extra
    return new


def write_baseline(current: dict[str, list[str]], path: Path | None = None) -> None:
    path = path or BASELINE_PATH
    payload = {
        "_comment": (
            "迁移破坏性 DDL 棘轮基线：由 python -m migrations._destructive_scan "
            "--update-baseline 生成。只在人工审阅后更新；更新需在提交信息里说明理由。"
        ),
        "files": {k: sorted(v) for k, v in sorted(current.items())},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _main(argv: list[str]) -> int:
    current = scan_versions_dir()
    if "--update-baseline" in argv:
        write_baseline(current)
        print(f"已写入基线 {BASELINE_PATH}（{len(current)} 个文件）")
        return 0
    new = find_new_destructive_ops(current, load_baseline())
    if new:
        print("发现新增的破坏性 DDL（未在基线中）：")
        for f, sigs in new.items():
            print(f"  {f}")
            for s in sigs:
                print(f"     - {s}")
        print("\n如确为人工审阅后有意为之，请执行：")
        print("  python -m migrations._destructive_scan --update-baseline")
        return 1
    print("OK：无新增破坏性 DDL")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
