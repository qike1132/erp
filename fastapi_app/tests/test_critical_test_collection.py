"""防止关键回归测试因文件命名或路径漂移而静默漏收集。"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_ROOTS = (ROOT / "tests", ROOT / "fastapi_app" / "tests")
COLLECT_PATTERN = "test_*.py"


def _test_function_count(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
        for node in ast.walk(tree)
    )


def test_no_test_like_file_escapes_pytest_name_pattern() -> None:
    """含测试函数的文件必须匹配 pytest.ini 的 test_*.py 收集规则。"""
    escaped: list[str] = []
    for root in TEST_ROOTS:
        for path in root.rglob("*.py"):
            if path.match(COLLECT_PATTERN) or path.name == "conftest.py":
                continue
            if _test_function_count(path):
                escaped.append(path.relative_to(ROOT).as_posix())
    assert escaped == [], "以下文件含测试函数但不会被默认收集；请改名为 test_*.py：\n" + "\n".join(escaped)


def test_backup_schedule_delete_guard_is_collectable() -> None:
    """P0 回归锚点：备份调度守卫必须位于默认收集路径且确有测试函数。"""
    path = ROOT / "fastapi_app" / "tests" / "test_schedule_delete_guard.py"
    assert path.is_file(), "备份调度删除守卫测试缺失或再次被错误改名"
    assert path.match(COLLECT_PATTERN)
    assert _test_function_count(path) >= 9
