"""F3-9 / F3-8：危险写脚本必须接统一护栏；affected_rows 拒绝多语句。"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_affected_rows_rejects_multi_statement():
    guard = _load('_prod_write_guard_f38', ROOT / 'scripts' / '_prod_write_guard.py')

    class _DB:
        def execute(self, _stmt):
            raise AssertionError('非法多语句不得下发到数据库')

    with pytest.raises(ValueError, match='单条'):
        guard.affected_rows(_DB(), 'DELETE FROM a; DELETE FROM b', dry_run=True)


@pytest.mark.parametrize('rel', [
    'scripts/database/db_manager.py',
    'scripts/database/restore_db.py',
    'scripts/init_permissions.py',
    'scripts/backfill_purchase_order_sku.py',
    # 审查 H13 补齐的 5 个直写生产库脚本
    'scripts/reset_admin_password.py',
    'scripts/migrate_password_hashes.py',
    'scripts/perf_add_indexes.py',
    'scripts/cleanup_duplicate_purchase_orders.py',
    'scripts/backfill_production_stock_20261006.py',
])
def test_dangerous_write_scripts_wire_the_guard(rel):
    """F3-9：危险写入口必须出现 require_prod_write_consent。"""
    source = (ROOT / rel).read_text(encoding='utf-8')
    assert 'require_prod_write_consent' in source
    assert '_prod_write_guard' in source
