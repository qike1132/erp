"""
Alembic 迁移脚本结构测试 — multi-SKU order_item 表功能 (SubTask 7.3)

本测试不执行真实的 alembic upgrade/downgrade（代码库无 PostgreSQL 测试库与
迁移测试基础设施；历史上的多 head 已通过 merge_resolve_all_heads 合并为单一
head，merge_heads_for_order_item 迁移已不存在）。改为加载迁移 Python 文件并
校验其结构正确性：revision/down_revision、upgrade/downgrade 可调用性、SQL
操作、数据回填语句、必需列与索引，以及迁移链健康性（单一 head、无分叉）。

通过 stub `alembic` / `alembic.op` 让 `from alembic import op` 在 alembic
上下文之外可导入；函数体不会被执行，因此 `sa` / `op` 调用不会真正运行。
SQL 操作通过 `inspect.getsource` 检视函数源码断言。
"""
import importlib.util
import inspect
import sys
import types
from pathlib import Path

import pytest

_MIGRATIONS_DIR = Path(r"D:\erp_system\migrations\versions")


def _load_migration_module(filename: str):
    """按文件路径加载迁移模块，但不执行 upgrade()/downgrade()。

    迁移脚本顶部 `from alembic import op` 在 alembic 上下文之外会失败，
    因此在 exec 前向 sys.modules 注入 stub `alembic` 与 `alembic.op`。
    函数体不会被调用，故 sa/op 调用不会真正执行。加载后恢复 sys.modules
    原状以避免污染其它测试。
    """
    file_path = _MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"_migration_{file_path.stem}", file_path)
    module = importlib.util.module_from_spec(spec)

    # stub alembic + alembic.op，使 `from alembic import op` 可成功
    fake_op = types.ModuleType("alembic.op")
    fake_op.create_table = lambda *a, **kw: None
    fake_op.drop_table = lambda *a, **kw: None
    fake_op.create_index = lambda *a, **kw: None
    fake_op.drop_index = lambda *a, **kw: None
    fake_op.execute = lambda *a, **kw: None
    fake_op.f = types.SimpleNamespace()
    fake_alembic = types.ModuleType("alembic")
    fake_alembic.op = fake_op

    saved_alembic = sys.modules.get("alembic")
    saved_alembic_op = sys.modules.get("alembic.op")
    sys.modules["alembic"] = fake_alembic
    sys.modules["alembic.op"] = fake_op
    try:
        spec.loader.exec_module(module)
    finally:
        if saved_alembic is not None:
            sys.modules["alembic"] = saved_alembic
        else:
            sys.modules.pop("alembic", None)
        if saved_alembic_op is not None:
            sys.modules["alembic.op"] = saved_alembic_op
        else:
            sys.modules.pop("alembic.op", None)

    return module


# order_item 建表迁移所要求的全部列
_REQUIRED_COLUMNS = [
    "id",
    "order_id",
    "product_id",
    "product_name",
    "product_barcode",
    "quantity",
    "order_type",
    "country",
    "deduct_stock",
    "deduct_quantity",
    "note",
    "created_at",
    "updated_at",
]

# upgrade() 必须创建的 3 个索引
_REQUIRED_INDEXES = [
    "ix_order_item_order_id",
    "ix_order_item_product_id",
    "ix_order_item_order_product",
]


class TestOrderItemMigration:
    """校验 pg_standalone_014_create_order_item.py 的结构正确性。"""

    @pytest.fixture(scope="class")
    def migration(self):
        return _load_migration_module("pg_standalone_014_create_order_item.py")

    @pytest.fixture(scope="class")
    def upgrade_source(self, migration):
        return inspect.getsource(migration.upgrade)

    @pytest.fixture(scope="class")
    def downgrade_source(self, migration):
        return inspect.getsource(migration.downgrade)

    def test_revision_is_nonempty_string(self, migration):
        assert isinstance(migration.revision, str)
        assert len(migration.revision) > 0

    def test_down_revision_is_not_none(self, migration):
        # 历史上本代码库曾出现 down_revision=None 造成孤儿分支的 bug
        assert migration.down_revision is not None

    def test_down_revision_points_to_rebuild_po_dedup_index(self, migration):
        # merge_heads_for_order_item 已删除（迁移链已合并为单一 head），
        # 014 的实际父迁移为 rebuild_po_dedup_index
        assert migration.down_revision == "rebuild_po_dedup_index"

    def test_upgrade_is_callable(self, migration):
        assert callable(migration.upgrade)

    def test_downgrade_is_callable(self, migration):
        assert callable(migration.downgrade)

    def test_upgrade_creates_order_item_table(self, upgrade_source):
        assert "create_table" in upgrade_source
        assert "'order_item'" in upgrade_source

    def test_upgrade_creates_required_indexes(self, upgrade_source):
        for index_name in _REQUIRED_INDEXES:
            assert index_name in upgrade_source, f"缺失索引创建: {index_name}"
            assert "create_index" in upgrade_source

    def test_upgrade_contains_data_backfill(self, upgrade_source):
        # op.execute 调用，且 SQL 同时引用 order_item 与 "order"
        assert "op.execute" in upgrade_source
        assert "INSERT INTO order_item" in upgrade_source
        assert 'FROM "order"' in upgrade_source

    def test_downgrade_drops_order_item_table(self, downgrade_source):
        assert "drop_table" in downgrade_source
        assert "'order_item'" in downgrade_source

    def test_create_table_has_required_columns(self, upgrade_source):
        for col in _REQUIRED_COLUMNS:
            pattern = f"sa.Column('{col}'"
            assert pattern in upgrade_source, f"缺失列定义: {col}"


class TestMigrationChainHealth:
    """校验迁移链健康性：单一 head、无分叉，order_item 迁移位于主链。

    取代旧的 TestMergeHeadsMigration（其依赖的 merge_heads_for_order_item.py
    已删除）。迁移链已由 merge_resolve_all_heads 合并为单一 head，此处验证
    该健康状态持续成立。
    """

    @pytest.fixture(scope="class")
    def script_dir(self):
        from alembic.script import ScriptDirectory
        return ScriptDirectory(str(_MIGRATIONS_DIR.parent))

    @pytest.fixture(scope="class")
    def chain_revisions(self, script_dir):
        return {rev.revision for rev in script_dir.walk_revisions()}

    def test_single_head_no_fork(self, script_dir):
        heads = script_dir.get_heads()
        assert len(heads) == 1, f"迁移链分叉，存在多个 head: {heads}"

    def test_order_item_migration_in_chain(self, chain_revisions):
        assert "pg_standalone_014_create_order_item" in chain_revisions

    def test_order_item_parent_in_chain(self, chain_revisions):
        assert "rebuild_po_dedup_index" in chain_revisions
