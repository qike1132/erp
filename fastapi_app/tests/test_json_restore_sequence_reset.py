"""P1-11：JSON 恢复后逐表重置主键序列，避免跨环境恢复首次插入 23505。"""
from __future__ import annotations

from unittest.mock import AsyncMock

from sqlalchemy.exc import SQLAlchemyError

from fastapi_app.services.backup import json_backup


class _One:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Table:
    def __init__(self, name: str, has_id: bool = True):
        self.name = name
        self.c = {'id': object()} if has_id else {}


class _FakeDB:
    def __init__(self, seq_by_table=None, fail_on: str | None = None):
        self._seq = seq_by_table or {}
        self._fail_on = fail_on
        self.calls: list[tuple[str, dict | None]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        if 'pg_get_serial_sequence' in sql:
            return _One(self._seq.get((params or {}).get('tbl')))
        if self._fail_on and self._fail_on in sql:
            raise SQLAlchemyError('boom')
        return _One(None)


async def test_resets_only_tables_with_sequences() -> None:
    db = _FakeDB({'products': 'public.products_id_seq', 'orders': None})
    tables = [_Table('products'), _Table('orders'), _Table('no_id_table', has_id=False)]

    reset, errors = await json_backup._reset_sequences_after_json_restore(db, tables)

    assert reset == ['products']
    assert errors == []
    setval_calls = [sql for sql, _ in db.calls if 'setval' in sql]
    assert len(setval_calls) == 1
    assert '"products"' in setval_calls[0]
    assert 'regclass' in setval_calls[0]
    # 无 id 列的表连序列查询都不发
    assert not any(params and params.get('tbl') == 'no_id_table' for _, params in db.calls)


async def test_sequence_reset_failure_is_reported_not_raised() -> None:
    db = _FakeDB({'products': 'public.products_id_seq'}, fail_on='setval')

    reset, errors = await json_backup._reset_sequences_after_json_restore(
        db, [_Table('products')],
    )

    assert reset == []
    assert errors and 'products' in errors[0]


async def test_restore_legacy_json_wires_sequence_reset(monkeypatch) -> None:
    monkeypatch.setattr(json_backup, '_disable_fk_constraints', AsyncMock(return_value=True))
    monkeypatch.setattr(json_backup, '_clear_tables_for_restore', AsyncMock(return_value=[]))
    monkeypatch.setattr(
        json_backup, '_restore_tables_from_json', AsyncMock(return_value=({}, 0, [])),
    )
    reset_mock = AsyncMock(return_value=(['products'], []))
    monkeypatch.setattr(json_backup, '_reset_sequences_after_json_restore', reset_mock)
    monkeypatch.setattr(json_backup, '_invalidate_caches_after_restore', AsyncMock())
    monkeypatch.setattr(
        json_backup, '_verify_restored_json', AsyncMock(return_value={'overall_pass': True}),
    )
    monkeypatch.setattr(json_backup, '_re_enable_fk_constraints', AsyncMock())

    db = AsyncMock()
    db.flush = AsyncMock()

    result = await json_backup.restore_legacy_json({'tables': {}}, db)

    assert reset_mock.await_count == 1
    assert result['database']['sequences_reset'] == 1
    assert result['database']['status'] == 'ok'


async def test_sequence_reset_error_makes_status_partial(monkeypatch) -> None:
    monkeypatch.setattr(json_backup, '_disable_fk_constraints', AsyncMock(return_value=True))
    monkeypatch.setattr(json_backup, '_clear_tables_for_restore', AsyncMock(return_value=[]))
    monkeypatch.setattr(
        json_backup, '_restore_tables_from_json', AsyncMock(return_value=({}, 0, [])),
    )
    monkeypatch.setattr(
        json_backup, '_reset_sequences_after_json_restore',
        AsyncMock(return_value=([], ['products: 主键序列重置失败（boom）'])),
    )
    monkeypatch.setattr(json_backup, '_invalidate_caches_after_restore', AsyncMock())
    monkeypatch.setattr(
        json_backup, '_verify_restored_json', AsyncMock(return_value={'overall_pass': True}),
    )
    monkeypatch.setattr(json_backup, '_re_enable_fk_constraints', AsyncMock())

    db = AsyncMock()
    db.flush = AsyncMock()

    result = await json_backup.restore_legacy_json({'tables': {}}, db)

    assert result['database']['status'] == 'partial'
    assert any('主键序列重置失败' in e for e in result['errors'])
