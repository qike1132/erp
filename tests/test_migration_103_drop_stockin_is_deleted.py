"""Z03-R5：stock_in.is_deleted 死状态位已移除的回归护栏。

背景
----
``StockIn.is_deleted`` 从未被任何代码写入（备货删除是硬删），却有 7 处
``StockIn.is_deleted.isnot(True)`` 读取过滤恒真——读者会误以为存在备货软删
机制。2026-10-17 审计 Z03-R5 的处置：删列 + 删过滤 + 迁移
``pg_standalone_103_drop_stockin_is_deleted``。

本文件锁住：
1. ORM 模型不再声明该列（与迁移后的库结构一致）；
2. 全仓不再出现 ``StockIn.is_deleted`` 引用（死过滤不得回潮）；
3. 迁移的防御闸门：存在 is_deleted=TRUE 的行时**拒绝删列**（否则这些行会复活）；
4. 迁移链与 downgrade 结构正确。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / 'migrations' / 'versions' / 'pg_standalone_103_drop_stockin_is_deleted.py'
)
APP_ROOT = Path(__file__).resolve().parent.parent / 'fastapi_app'


def _load_migration_module():
    spec = importlib.util.spec_from_file_location('migration_103', MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeBind:
    def __init__(self, marked_rows: int):
        self.marked_rows = marked_rows
        self.statements: list[str] = []

    def execute(self, statement):
        self.statements.append(str(statement))
        return _FakeResult(self.marked_rows)


class _FakeOp:
    def __init__(self, bind: _FakeBind):
        self._bind = bind
        self.dropped_indexes: list[tuple] = []
        self.dropped_columns: list[tuple] = []
        self.added_columns: list[tuple] = []
        self.created_indexes: list[tuple] = []

    def get_bind(self):
        return self._bind

    def execute(self, statement):
        self._bind.statements.append(str(statement))

    def drop_index(self, name, table_name=None, **kwargs):
        self.dropped_indexes.append((name, table_name))

    def drop_column(self, table, column, **kwargs):
        self.dropped_columns.append((table, column))

    def add_column(self, table, column, **kwargs):
        self.added_columns.append((table, column.name))

    def create_index(self, name, table, columns, **kwargs):
        self.created_indexes.append((name, table, tuple(columns)))


class _FakeContext:
    @staticmethod
    def is_offline_mode():
        return False


def _prepare(monkeypatch, marked_rows: int = 0, present=None):
    from migrations import _legacy_base_guard as guard

    mod = _load_migration_module()
    bind = _FakeBind(marked_rows)
    fake_op = _FakeOp(bind)
    columns = {'id', 'stockin_no', 'is_deleted'} if present is None else present
    monkeypatch.setattr(mod, 'op', fake_op)
    monkeypatch.setattr(mod, 'base_schema_absent', lambda: False)
    monkeypatch.setattr(mod, 'table_columns', lambda table: columns)
    # drop_index/drop_column/add_column 的实现都在 guard 里，按同一套 fake 打桩
    monkeypatch.setattr(guard, 'op', fake_op)
    monkeypatch.setattr(guard, 'table_columns', lambda table: columns)
    monkeypatch.setattr(guard, 'context', _FakeContext())
    return mod, fake_op, bind


def test_revision_chain_follows_102() -> None:
    mod = _load_migration_module()

    assert mod.revision == 'pg_standalone_103_drop_stockin_is_deleted'
    assert mod.down_revision == 'pg_standalone_102_purchase_order_status_check'


def test_model_no_longer_declares_is_deleted() -> None:
    from fastapi_app.shared_models import StockIn

    assert 'is_deleted' not in StockIn.__table__.columns


def test_no_source_references_stockin_is_deleted() -> None:
    offenders = [
        str(path.relative_to(APP_ROOT.parent))
        for path in APP_ROOT.rglob('*.py')
        if 'StockIn.is_deleted' in path.read_text(encoding='utf-8')
    ]
    assert offenders == [], f'StockIn.is_deleted 已删除，不得再引用：{offenders}'


def test_upgrade_drops_index_and_column_when_no_marked_rows(monkeypatch) -> None:
    mod, fake_op, bind = _prepare(monkeypatch, marked_rows=0)

    mod.upgrade()

    assert any('is_deleted IS TRUE' in sql for sql in bind.statements), bind.statements
    assert fake_op.dropped_indexes == [('ix_stock_in_is_deleted', 'stock_in')]
    assert fake_op.dropped_columns == [('stock_in', 'is_deleted')]


def test_upgrade_refuses_when_marked_rows_exist(monkeypatch) -> None:
    """有 is_deleted=TRUE 的行 → 拒绝删列（硬删会让这些行复活）"""
    mod, fake_op, _bind = _prepare(monkeypatch, marked_rows=3)

    try:
        mod.upgrade()
    except RuntimeError as exc:
        assert '3 行' in str(exc)
    else:
        raise AssertionError('存在标记为已删除的行时必须拒绝删列')

    assert fake_op.dropped_columns == []
    assert fake_op.dropped_indexes == []


def test_upgrade_skips_when_column_absent(monkeypatch) -> None:
    mod, fake_op, _bind = _prepare(monkeypatch, present={'id', 'stockin_no'})

    mod.upgrade()

    assert fake_op.dropped_columns == []


def test_downgrade_restores_column_and_index(monkeypatch) -> None:
    # 降级场景：列已被升级删掉（表仍在）
    mod, fake_op, bind = _prepare(monkeypatch, present={'id', 'stockin_no'})

    mod.downgrade()

    assert fake_op.added_columns == [('stock_in', 'is_deleted')]
    assert any(
        'CREATE INDEX IF NOT EXISTS ix_stock_in_is_deleted' in sql for sql in bind.statements
    ), bind.statements
