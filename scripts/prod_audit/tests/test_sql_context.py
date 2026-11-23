"""L4/L6 静态 SQL 审计规则回归，不运行样例。"""
from __future__ import annotations

import ast

import pytest

from scripts.prod_audit.base.issue_builder import IssueBuilder
from scripts.prod_audit.base.sql_context import SqlContext
from scripts.prod_audit.layers.l4_data_access import _SqlInjectionVisitor
from scripts.prod_audit.layers.l6_security import _SqlInjectionRedTeamVisitor


@pytest.mark.parametrize("visitor_cls,layer", [(_SqlInjectionVisitor, "L4"), (_SqlInjectionRedTeamVisitor, "L6")])
@pytest.mark.parametrize(
    "source,expected_lines",
    [
        ("raise ValueError(f'bad value: {raw}')", []),
        ("logger.warning(f'SQL import failed: {detail}')", []),
        ("text = f'''\n备份告警：{detail}\n'''", []),
        ("while i + length < n and text[i + length]:\n    pass", []),
        ("raw = 10 % bucket", []),
        ("query = query.where(column.ilike(f'%{value}%'))", []),
        ("sql = 'SELECT id FROM records WHERE id = :record_id'", []),
        ("db.execute(text('SELECT id FROM records WHERE id = :record_id'), {'record_id': value})", []),
        ("statement = f'SELECT id FROM {table}'", [1]),
        ("statement = 'SELECT id FROM {}'.format(table)", [1]),
        ("statement = 'SELECT id FROM %s' % table", [1]),
        ("statement = 'SELECT id FROM ' + table", [1]),
        ("db.execute(\n    f'{fragment}'\n)", [2]),
        ("db.execute(statement=f'{fragment}')", [1]),
        ("db.execute(text(f'SELECT id FROM {table}'))  # sql-safe: fixture", []),
    ],
)
def test_static_sql_audit_context(visitor_cls, layer, source, expected_lines):
    tree = ast.parse(source)
    visitor = visitor_cls("fixture.py", layer, IssueBuilder(), source.splitlines(), SqlContext(tree))
    visitor.visit(tree)
    assert [issue.line for issue in visitor.issues] == expected_lines
