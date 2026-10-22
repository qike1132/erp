"""L16：大表覆盖度用 pg_class.reltuples 估算，不再对大表做 COUNT(*)。"""
import pytest


class _FakeResult:
    def __init__(self, rows=None, scalar=0):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar


class _FakeNested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeSession:
    def __init__(self):
        self.calls = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        if "pg_class" in sql:
            return _FakeResult(rows=[("big", 5_000_000), ("small", 10)])
        if "COUNT" in sql:
            return _FakeResult(scalar=10)
        return _FakeResult()

    async def begin_nested(self):
        return _FakeNested()


@pytest.mark.asyncio
async def test_large_table_uses_reltuples():
    from fastapi_app.services.backup.orchestration import core

    db = _FakeSession()
    stats = await core._count_tables(db, ["big", "small"], {"big", "small"})

    assert stats["big"] == 5_000_000
    assert stats["small"] == 10
    assert not any("COUNT" in sql and "big" in sql for sql in db.calls), (
        "大表不应再发 COUNT(*)"
    )


@pytest.mark.asyncio
async def test_reltuples_query_runs_on_real_pg(async_db_session):
    """真库冒烟：ANY(:names) 的数组绑定必须可用，否则优化会静默回落 COUNT。"""
    from sqlalchemy import text

    from fastapi_app.shared_models import Base

    names = [t.name for t in Base.metadata.sorted_tables][:5]
    rows = await async_db_session.execute(
        text(
            "SELECT c.relname, c.reltuples::bigint FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' "
            "AND c.relname = ANY(:names)"
        ),
        {"names": names},
    )
    assert rows.all(), "reltuples 查询未返回任何表，ANY(:names) 绑定可能不可用"
