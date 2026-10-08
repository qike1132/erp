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

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"
# 迁移模块在模块级导入的守卫模块；stub 窗口内会被首次导入，需一并恢复
_GUARD_MODULE_NAME = "migrations._legacy_base_guard"


def _load_migration_module(filename: str):
    """按文件路径加载迁移模块，但不执行 upgrade()/downgrade()。

    迁移脚本顶部的 `from alembic import op`、以及迁移模块级导入的
    `migrations/_legacy_base_guard.py` 顶部的 `from alembic import context, op`，
    在 alembic 上下文之外都会失败，因此在 exec 前向 sys.modules 注入最小 stub
    `alembic`（含 op / context 两个子模块）。函数体不会被调用，故 sa/op 调用不会
    真正执行。加载后恢复 sys.modules 原状（含 stub 窗口内首次导入的守卫模块），
    既不污染其它测试，也不依赖其它测试先导入该守卫模块。
    """
    file_path = _MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"_migration_{file_path.stem}", file_path)
    module = importlib.util.module_from_spec(spec)

    # stub alembic / alembic.op / alembic.context，使 `from alembic import op`（迁移脚本）
    # 与 `from alembic import context, op`（守卫模块）都可成功；不引入真实 alembic。
    fake_op = types.ModuleType("alembic.op")
    fake_op.create_table = lambda *a, **kw: None
    fake_op.drop_table = lambda *a, **kw: None
    fake_op.create_index = lambda *a, **kw: None
    fake_op.drop_index = lambda *a, **kw: None
    fake_op.execute = lambda *a, **kw: None
    fake_op.f = types.SimpleNamespace()
    fake_alembic = types.ModuleType("alembic")
    fake_alembic.op = fake_op
    # 守卫模块所需的 context 子模块（模块级 import 期只需要它存在）
    fake_alembic.context = types.ModuleType("alembic.context")

    # 守卫模块在 stub 窗口内可能被【首次】导入并缓存：它会把 stub 的 context/op
    # 绑进自己的模块命名空间，因此也要保存/恢复，避免把 stub 泄漏给后续测试。
    saved_modules = {
        name: sys.modules.get(name)
        for name in ("alembic", "alembic.op", _GUARD_MODULE_NAME)
    }
    sys.modules["alembic"] = fake_alembic
    sys.modules["alembic.op"] = fake_op
    try:
        spec.loader.exec_module(module)
    finally:
        for name, saved_module in saved_modules.items():
            if saved_module is not None:
                sys.modules[name] = saved_module
            else:
                sys.modules.pop(name, None)

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
