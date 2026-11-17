#!/usr/bin/env python
"""测试库隔离门禁（AST）：禁止 `fastapi_app/tests/**` 使用应用自身的库引擎。

## 为什么需要这条门禁（2026-11-17 上线前审计 P0-2）

`fastapi_app/tests/` 这棵测试树**没有**把 `settings.DATABASE_URL` 重定向到测试库
（做这件事的是**根树** `tests/conftest.py` 的 `app_on_test_db` session fixture，
只对 `tests/` 子树生效）。因此本树里凡是走应用自身引擎的代码，连的都是 `.env`
里那个库 —— 在本机就是**生产库**。

代价实例：`test_product_stock_check_constraint.py` 用 `get_sync_engine()` 对
`product` 表做 `ALTER TABLE ... ADD CONSTRAINT` + 负值写探针 + 全表快照。
AGENTS §4 推荐的聚焦跑法（`pytest fastapi_app/tests/<文件>`）会直接对生产表
加 `ACCESS EXCLUSIVE` 锁；一旦事务在回滚前被进程级中断，就留下未回滚事务与挂起锁。

## 规则

扫描 `fastapi_app/tests/**/*.py` 的 AST，命中以下任一即违规：

- 名字 `get_sync_engine` / `SyncSession` / `SyncSessionLocal`
  （`from fastapi_app.core.database import ...` 或直接调用）
- 属性访问 `<x>.get_sync_engine`

**放行**：测试若要连真库，必须走测试库硬闸
`fastapi_app.tests._test_db_guard.resolve_test_db_url()` /
`derive_test_db_url()`（它们强制库名以 `_test` 结尾），再自建
`create_engine(url, poolclass=NullPool)`。

## 用法

    python scripts/check_test_db_isolation.py            # 人读输出
    python scripts/check_test_db_isolation.py --json     # 供 quality_gate 解析
    python scripts/check_test_db_isolation.py <dir>      # 覆盖扫描面（自检用）

退出码：0 = 无违规；1 = 有违规；2 = 用法/路径错误。
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# 说明：**不在 import 期重包 stdout**（会被 pytest/工具 import 时踩坏捕获器）。
# UTF-8 重包只发生在 `__main__`（见文件末尾）——被 import 时本模块零副作用。

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_SCAN_DIR = PROJECT_ROOT / "fastapi_app" / "tests"
EXCLUDE_DIRS = {"__pycache__"}

# 应用自身引擎的构造入口：出现即说明"这个测试可能连 .env 里那个库"
FORBIDDEN_NAMES = frozenset({"get_sync_engine", "SyncSession", "SyncSessionLocal"})


@dataclass(frozen=True)
class Violation:
    file: str
    line: int
    name: str

    def to_dict(self) -> dict:
        return asdict(self)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        # 语法错误由 ruff / BOM 门禁负责，本门禁不重复报
        return None


def scan_file(path: Path) -> list[Violation]:
    tree = _parse(path)
    if tree is None:
        return []
    found: list[Violation] = []
    for node in ast.walk(tree):
        hit: str | None = None
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            hit = node.id
        elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            hit = node.attr
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name in FORBIDDEN_NAMES:
                    hit = alias.name
                    break
        if hit is not None:
            found.append(Violation(file=_rel(path), line=getattr(node, "lineno", 0), name=hit))
    return found


def iter_py_files(scan_dir: Path) -> list[Path]:
    return [
        p
        for p in sorted(scan_dir.rglob("*.py"))
        if not any(part in EXCLUDE_DIRS for part in p.parts)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="测试库隔离门禁（禁止 fastapi_app/tests 使用应用自身引擎）")
    parser.add_argument("scan_dir", nargs="?", help="覆盖扫描目录（默认 fastapi_app/tests）")
    parser.add_argument("--json", action="store_true", help="机器可读输出（供 quality_gate）")
    args = parser.parse_args(argv)

    scan_dir = Path(args.scan_dir).resolve() if args.scan_dir else DEFAULT_SCAN_DIR
    if not scan_dir.is_dir():
        print(f"[ERROR] 扫描目录不存在：{scan_dir}", file=sys.stderr)
        return 2

    files = iter_py_files(scan_dir)
    violations: list[Violation] = []
    for path in files:
        violations.extend(scan_file(path))

    payload = {
        "total": len(violations),
        "scanned_files": len(files),
        "scan_dir": _rel(scan_dir),
        "violations": [v.to_dict() for v in violations],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"扫描 {len(files)} 个文件（{payload['scan_dir']}）")
        if not violations:
            print("OK 测试树未使用应用自身库引擎（测试库隔离成立）")
        else:
            print(f"发现 {len(violations)} 处违规：")
            for v in violations:
                print(f"  {v.file}:{v.line}  使用 {v.name}")
            print("修法：改用 fastapi_app.tests._test_db_guard.resolve_test_db_url() 拿测试库 URL，"
                  "再 create_engine(url, poolclass=NullPool)；不要用 get_sync_engine()/SyncSession。")
    return 0 if not violations else 1


if __name__ == "__main__":
    # 只在作为脚本运行时把 stdout 重包为 UTF-8（中文提示 / JSON 不乱码）。
    # 被 import 时**不动** stdout —— 否则会关掉 pytest 捕获器的底层 buffer。
    _buf = getattr(sys.stdout, "buffer", None)
    if _buf is not None:
        sys.stdout = io.TextIOWrapper(_buf, encoding="utf-8")
    sys.exit(main())
