"""供 L4/L6 共用的动态 SQL 静态判据；不追踪跨语句的数据流。"""

from __future__ import annotations

import ast
import re

_SQL_PREFIX = re.compile(
    r"^\s*(?:SELECT\s|WITH\s+(?:RECURSIVE\s+)?\w+\s+AS\s*\(|"
    r"INSERT\s+INTO\b|UPDATE\s+\S+\s+SET\b|DELETE\s+FROM\b|"
    r"(?:CREATE|ALTER|DROP|TRUNCATE)\s+(?:TABLE|INDEX|VIEW|SCHEMA)\b)",
    re.IGNORECASE,
)
_SQL_CALLS = frozenset({"text", "execute", "executemany", "exec_driver_sql"})
_SQL_ARGUMENTS = frozenset({"text", "statement", "query", "sql"})


def is_string_expression(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (
        isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def _has_sql_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(_SQL_PREFIX.match(node.value))
    if isinstance(node, ast.JoinedStr):
        return any(_has_sql_literal(part) for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _has_sql_literal(node.left) or _has_sql_literal(node.right)
    return False


class SqlContext:
    """只使用 SQL 文本或动态表达式作为 SQL 调用的直接实参这两类信号。"""

    def __init__(self, tree: ast.AST) -> None:
        self._arguments: set[ast.AST] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _SQL_CALLS:
                self._arguments.update(node.args[:1])
                self._arguments.update(kw.value for kw in node.keywords if kw.arg in _SQL_ARGUMENTS)

    def matches(self, node: ast.AST, sql_template: ast.AST | None = None) -> bool:
        return node in self._arguments or _has_sql_literal(sql_template or node)
