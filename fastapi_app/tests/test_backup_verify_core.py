"""还原校验核心：标识符安全引用与动态导出。

背景（上线前审计）
------------------
备份/还原是**唯一不可逆**的链路，而 `services/backup/verify/core.py` 覆盖率仅 16%。
其中 `quote_table()` 是**动态表名的唯一防线**（`REV-08`）——`query_table_rows()`
把表名拼进 `SELECT * FROM {qtname}`，一旦引用失效就是 SQL 标识符注入。

本文件先覆盖**不需要真库**、且风险最高的部分：
- `quote_table` 的接受/拒绝边界（注入防线本身）；
- `query_table_rows` **在构造 SQL 之前**就拒绝危险表名；
- `since` 走**绑定参数**而不是字符串插值。
"""
from __future__ import annotations

import pytest

from fastapi_app.services.backup.verify import core as verify_core
from fastapi_app.services.backup.verify.core import (
    get_checksum_tables,
    query_table_rows,
    quote_table,
)

# ---------------------------------------------------------------------------
# quote_table —— 注入防线
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    'name',
    ['orders', 'order_items', 'a1', '_internal', 'order-items'],
)
def test_quote_table_accepts_and_quotes_safe_names(name: str) -> None:
    assert quote_table(name) == f'"{name}"'


@pytest.mark.parametrize(
    'name',
    [
        '',                                  # 空
        'orders; DROP TABLE users; --',      # 语句注入
        'orders"; DROP TABLE users; --',     # 引号逃逸
        'ord er',                            # 空格
        'ord.er',                            # schema 限定
        'ord/er',
        'ord\ner',
        "ord'er",
        'ord`er',
    ],
)
def test_quote_table_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(ValueError):
        quote_table(name)


def test_quote_table_rejects_unicode_quotes() -> None:
    """全角/弯引号也不行 —— 只允许 ascii alnum 与 `_`/`-`。"""
    with pytest.raises(ValueError):
        quote_table('orders”')


# ---------------------------------------------------------------------------
# get_checksum_tables
# ---------------------------------------------------------------------------

def test_checksum_tables_exclude_alembic_version() -> None:
    tables = get_checksum_tables()

    assert 'alembic_version' not in tables, '迁移版本表不该参与业务校验和'
    assert tables, '校验和表集合不应为空'


def test_checksum_tables_are_real_model_tables() -> None:
    """集合必须来自 ORM 元数据（否则校验会比对一个不存在的表）。"""
    from fastapi_app.shared_models import Base

    model_tables = {str(t.name) for t in Base.metadata.sorted_tables}
    assert get_checksum_tables() <= model_tables


# ---------------------------------------------------------------------------
# query_table_rows —— 注入在构造 SQL 之前就被拦下
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def keys(self):
        return list(self._rows[0].keys()) if self._rows else []


class _FakeDb:
    """记录每次 execute 的 (sql, params)，返回预置行。"""

    def __init__(self, rows: list[dict] | None = None):
        self.executed: list[tuple[str, dict]] = []
        self._rows = rows or []

    async def execute(self, statement, params=None):
        self.executed.append((str(statement), dict(params or {})))
        return _FakeResult(self._rows)

    async def rollback(self):  # pragma: no cover - 本文件不触发
        pass


async def test_query_table_rows_rejects_injection_before_any_sql() -> None:
    db = _FakeDb()

    with pytest.raises(ValueError):
        await query_table_rows('orders"; DROP TABLE users; --', db)

    assert db.executed == [], '危险表名必须在构造 SQL 之前就被拒绝，而不是拼进语句后再报错'


async def test_query_table_rows_quotes_table_name(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _FakeDb(rows=[{'id': 1}])

    await query_table_rows('order_items', db)

    sql, _ = db.executed[0]
    assert '"order_items"' in sql, f'表名未加引号：{sql}'
    assert 'SELECT * FROM' in sql


async def test_query_table_rows_binds_since_as_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    """`since` 必须走**绑定参数**，不能字符串插值进 SQL。"""
    db = _FakeDb(rows=[{'id': 1}])
    monkeypatch.setattr(verify_core, 'find_timestamp_column', _fake_ts_col)

    await query_table_rows('orders', db, since='2026-01-01 00:00:00')

    sql, params = db.executed[0]
    assert ':since' in sql, f'since 未作为绑定参数：{sql}'
    assert '2026-01-01' not in sql, '时间值不得出现在 SQL 文本里（说明是插值而非绑定）'
    assert 'since' in params


async def test_query_table_rows_serializes_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """行值必须经 serialize_value（datetime/Decimal 等需转成可 JSON 化）。"""
    from datetime import datetime

    stamp = datetime(2026, 1, 1, 12, 0, 0)
    db = _FakeDb(rows=[{'id': 1, 'created_at': stamp}])

    rows = await query_table_rows('orders', db)

    assert rows and rows[0]['id'] == 1
    assert rows[0]['created_at'] != stamp, 'datetime 未被序列化'
    assert isinstance(rows[0]['created_at'], str)


async def _fake_ts_col(tname: str, db) -> str:  # pragma: no cover - 测试替身
    return 'created_at'
