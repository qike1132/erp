"""待生成列表的软删谓词必须把 NULL 视为「未删除」。

模型层明确规定了口径（fastapi_app/shared_models/order.py:131-146）：
`is_deleted IS NOT TRUE`。服务层若写成 `is_deleted = false`，遗留 NULL 行会
从采购中心「待生成」列表里静默消失——这类缺数据的事故没有任何报错可查。
"""
from __future__ import annotations

from sqlalchemy.dialects import postgresql

from fastapi_app.services.purchase._unprocessed import _build_unprocessed_union


def _union_sql() -> str:
    stmt = _build_unprocessed_union().element
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))


def test_is_deleted_null_counts_as_not_deleted() -> None:
    sql = _union_sql().lower()
    assert 'is_deleted is not true' in sql, sql


def test_is_deleted_not_compared_with_equality() -> None:
    """等值比较会把 NULL 排除在外，与模型口径不一致。"""
    sql = _union_sql().lower()
    assert 'is_deleted = false' not in sql, sql
