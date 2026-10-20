"""001 初始迁移的 downgrade 必须显式拒绝，不能静默清空整库。

审计 P1-17：downgrade 原实现执行 ``DROP SCHEMA public CASCADE``，
一条命令即删光全部业务数据；自动回滚没有安全的逆操作。
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / 'migrations'
    / 'versions'
    / 'pg_standalone_001_pg_standalone_initial_schema.py'
)


def _load_migration():
    spec = importlib.util.spec_from_file_location('pg_standalone_001_guard', _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_refuses_to_drop_schema() -> None:
    module = _load_migration()

    with pytest.raises(NotImplementedError, match='不支持自动 downgrade'):
        module.downgrade()


def test_downgrade_source_executes_no_ddl() -> None:
    module = _load_migration()

    source = inspect.getsource(module.downgrade)
    assert 'op.execute' not in source
    assert 'NotImplementedError' in source


def test_downgrade_statement_list_is_removed() -> None:
    module = _load_migration()

    assert not hasattr(module, '_DOWNGRADE_STATEMENTS')
