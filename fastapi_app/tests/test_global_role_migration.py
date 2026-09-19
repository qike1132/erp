"""全局角色字典迁移脚本结构测试 — pg_standalone_045_global_role

**为何不真实执行 upgrade/downgrade**

本机为「生产兼开发机」，工程纪律严禁对生产库执行 ``alembic upgrade``；代码库亦
无 PostgreSQL 迁移测试基础设施（见 ``test_order_item_migration.py`` 顶部说明），
且本迁移含 PostgreSQL 专有语法——``lower(name)`` 函数唯一索引、``ON CONFLICT``、
``TEMP`` 表、``DO $$`` 匿名块、``uq_product_material_product_role``——SQLite 无法
承载。故与 ``test_order_item_migration.py`` 保持一致：加载迁移 Python 文件，
对其**完整源码**做结构与不变式断言（函数体不执行，``sa``/``op`` 调用不会真正运行）。

**覆盖任务书五项判据**

① 按分类物料行计数守恒：迁移不得 ``TRUNCATE`` / 清空三张物料表，``DROP TABLE``
   只允许命中 ``role`` / ``_pr_dup`` / ``_pm_group`` 等临时或字典表，且删除仅限
   「归并去重」的重复行（受 ``rn > 1`` 守卫）。
② 幂等：DDL 一律 ``IF NOT EXISTS``、上卷 ``INSERT ... ON CONFLICT DO NOTHING``、
   回填仅限 ``global_role_id IS NULL``、约束创建包在 ``DO $$ IF NOT EXISTS`` 内。
③ 归并：同产品同全局角色的多行 ``product_role`` 归并保 ``min(id)``，
   ``product_material``（有唯一约束）**先按组去重再改指保留角色**，
   **改指发生在删除重复 product_role 之前**（否则 CASCADE 连带删物料）。
④ ``lower(name)`` 唯一性：创建 ``uq_role_name_lower`` 函数唯一索引。
⑤ downgrade：删 ``global_role_id`` 列、删 ``role`` 表，且不得删除任何物料行。

通过 stub ``alembic`` / ``alembic.op`` 让 ``from alembic import op`` 在 alembic
上下文之外可导入；函数体不会被执行。SQL 操作通过 ``inspect.getsource`` 检视源码断言。
"""
import importlib.util
import inspect
import re
import sys
import types
from pathlib import Path

import pytest

_MIGRATIONS_DIR = Path(r"D:\erp_system\migrations\versions")
_MIGRATION_FILE = "pg_standalone_045_global_role.py"

# 三张物料表（本迁移的「轻迁移」对象：字段与外键零改动，仅改指重复行）
_MATERIAL_TABLES = ("product_material", "product_fabric", "product_accessory")
# 允许被 DROP 的表：新建的字典表 role + 两张归并用的 TEMP 表
_DROPPABLE_TABLES = {"role", "_pr_dup", "_pm_group"}

_DROP_TABLE_RE = re.compile(
    r"DROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE
)
_DELETE_FROM_RE = re.compile(r"DELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


def _load_migration_module(filename: str):
    """按文件路径加载迁移模块，但不执行 upgrade()/downgrade()。

    迁移脚本顶部 ``from alembic import op`` 在 alembic 上下文之外会失败，
    因此在 exec 前向 sys.modules 注入 stub ``alembic`` 与 ``alembic.op``。
    函数体不会被调用，故 sa/op 调用不会真正执行。加载后恢复 sys.modules
    原状以避免污染其它测试。
    """
    file_path = _MIGRATIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(f"_migration_{file_path.stem}", file_path)
    module = importlib.util.module_from_spec(spec)

    fake_op = types.ModuleType("alembic.op")
    fake_op.create_table = lambda *a, **kw: None
    fake_op.drop_table = lambda *a, **kw: None
    fake_op.create_index = lambda *a, **kw: None
    fake_op.drop_index = lambda *a, **kw: None
    fake_op.execute = lambda *a, **kw: None
    fake_op.add_column = lambda *a, **kw: None
    fake_op.drop_column = lambda *a, **kw: None
    fake_op.create_foreign_key = lambda *a, **kw: None
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


class TestGlobalRoleMigrationStructure:
    """校验 pg_standalone_045_global_role.py 的结构与不变式。"""

    @pytest.fixture(scope="class")
    def migration(self):
        return _load_migration_module(_MIGRATION_FILE)

    @pytest.fixture(scope="class")
    def full_source(self, migration):
        return inspect.getsource(migration)

    @pytest.fixture(scope="class")
    def upgrade_source(self, migration):
        return inspect.getsource(migration.upgrade)

    @pytest.fixture(scope="class")
    def downgrade_source(self, migration):
        return inspect.getsource(migration.downgrade)

    @pytest.fixture(scope="class")
    def merge_source(self, migration):
        return inspect.getsource(migration._merge_duplicate_roles)

    @pytest.fixture(scope="class")
    def backfill_source(self, migration):
        return inspect.getsource(migration._backfill_global_role_id)

    # ---- 迁移骨架 ----

    def test_revision_is_expected(self, migration):
        assert migration.revision == "pg_standalone_045_global_role"

    def test_down_revision_points_to_seed_beile_export_print(self, migration):
        # 对齐生产已应用链：042(重命名权限)→043(补齐权限)→044(北乐导出打印)→045(本迁移)
        assert migration.down_revision == "pg_standalone_044_seed_beile_export_print"

    def test_upgrade_and_downgrade_are_callable(self, migration):
        assert callable(migration.upgrade)
        assert callable(migration.downgrade)

    def test_upgrade_runs_five_steps_in_order(self, upgrade_source):
        # upgrade 依次调用 建表 → 加列 → 回填 → 归并 → 收紧约束
        order = [
            "_create_role_dictionary",
            "_add_global_role_column",
            "_backfill_global_role_id",
            "_merge_duplicate_roles",
            "_tighten_constraints",
        ]
        positions = [upgrade_source.index(name) for name in order]
        assert positions == sorted(positions), "upgrade 步骤顺序被改动"

    # ---- ① 按分类物料行计数守恒 ----

    def test_no_truncate_anywhere(self, full_source):
        assert "TRUNCATE" not in full_source.upper()

    def test_drop_table_only_targets_allowed_tables(self, full_source):
        dropped = {m.group(1).lower() for m in _DROP_TABLE_RE.finditer(full_source)}
        assert dropped, "迁移未出现任何 DROP TABLE（连接收回也可能遗漏）"
        illegal = dropped - _DROPPABLE_TABLES
        assert not illegal, f"DROP TABLE 命中非允许表: {illegal}"

    def test_material_tables_never_dropped(self, full_source):
        dropped = {m.group(1).lower() for m in _DROP_TABLE_RE.finditer(full_source)}
        for table in _MATERIAL_TABLES:
            assert table not in dropped, f"物料表 {table} 被 DROP，违反行守恒"

    def test_delete_from_only_targets_material_or_product_role(self, full_source):
        deleted = {m.group(1).lower() for m in _DELETE_FROM_RE.finditer(full_source)}
        allowed = set(_MATERIAL_TABLES) | {"product_role"}
        illegal = deleted - allowed
        assert not illegal, f"DELETE FROM 命中非预期表: {illegal}"

    def test_fabric_and_accessory_never_deleted(self, full_source):
        # 无唯一约束表用纯改指（不删行）；删除只允许出现在有唯一约束的 product_material 去重
        deleted = {m.group(1).lower() for m in _DELETE_FROM_RE.finditer(full_source)}
        assert "product_fabric" not in deleted
        assert "product_accessory" not in deleted

    def test_product_material_delete_is_duplicate_dedup_only(self, full_source):
        # product_material 允许的唯一删除是「归并去重」：删除 rn > 1 的重复行
        assert "DELETE FROM product_material WHERE id IN (" in full_source
        assert "ranked.rn > 1" in full_source

    # ---- ② 幂等 ----

    def test_ddl_uses_if_not_exists(self, full_source):
        assert "CREATE TABLE IF NOT EXISTS role" in full_source
        assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_role_name_lower" in full_source
        assert "ADD COLUMN IF NOT EXISTS global_role_id" in full_source

    def test_temp_tables_drop_if_exists(self, full_source):
        assert "DROP TABLE IF EXISTS _pr_dup" in full_source
        assert "DROP TABLE IF EXISTS _pm_group" in full_source

    def test_upsert_uses_on_conflict_do_nothing(self, full_source):
        assert "INSERT INTO role(name)" in full_source
        assert "ON CONFLICT DO NOTHING" in full_source

    def test_backfill_only_touches_null_rows(self, backfill_source):
        assert "pr.global_role_id IS NULL" in backfill_source
        assert "lower(btrim(pr.role_name)) = lower(r.name)" in backfill_source

    def test_constraints_guarded_by_do_block(self, full_source):
        # 约束创建包在 DO $$ IF NOT EXISTS (SELECT 1 FROM pg_constraint ...) 内
        assert full_source.count("pg_constraint") >= 2
        assert "IF NOT EXISTS (SELECT 1 FROM pg_constraint" in full_source

    # ---- ③ 归并（保 min(id)、先去重再改指、改指先于删除） ----

    def test_merge_policy_table_marks_product_material_unique(self, migration):
        policy = dict(migration._MERGE_TABLES)
        assert policy["product_material"] is True
        assert policy["product_fabric"] is False
        assert policy["product_accessory"] is False

    def test_merge_keeps_min_id(self, merge_source):
        assert "MIN(id) AS keep_id" in merge_source
        assert "HAVING COUNT(*) > 1" in merge_source
        assert "WHERE pr.id <> k.keep_id" in merge_source

    def test_unique_table_dedup_before_reassign(self, full_source):
        # product_material 去重（按 product_id, keep_role_id 保 min mid）与改指两步都在
        assert "PARTITION BY product_id, keep_role_id ORDER BY mid" in full_source
        assert "DELETE FROM product_material WHERE id IN (" in full_source
        assert "UPDATE product_material pm SET role_id = g.keep_role_id" in full_source
        dedup_pos = full_source.index("DELETE FROM product_material WHERE id IN (")
        reassign_pos = full_source.index("UPDATE product_material pm SET role_id = g.keep_role_id")
        assert dedup_pos < reassign_pos, "去重必须先于改指，防止中间态违反唯一约束"

    def test_plain_table_reassign_template(self, migration):
        # 无唯一约束表：一条 UPDATE 直接改指
        template = migration._MERGE_REASSIGN_PLAIN
        assert template.startswith("UPDATE {table} t SET role_id = d.keep_id")
        assert "FROM _pr_dup d" in template

    def test_reassign_material_before_delete_product_role(self, merge_source):
        # 归并顺序铁律：改指物料(循环 _MERGE_TABLES)必须先于删除重复 product_role
        loop_pos = merge_source.index("_MERGE_TABLES")
        delete_pos = merge_source.index("DELETE FROM product_role pr USING _pr_dup d")
        assert loop_pos < delete_pos, "删除重复 product_role 前必须先改指物料行（防 CASCADE 丢数据）"

    # ---- ④ lower(name) 唯一性 ----

    def test_role_name_lower_unique_index(self, full_source):
        assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_role_name_lower ON role (lower(name))" in full_source

    # ---- ⑤ downgrade ----

    def test_downgrade_drops_column_and_role_table(self, downgrade_source):
        assert "DROP COLUMN IF EXISTS global_role_id" in downgrade_source
        assert "DROP TABLE IF EXISTS role" in downgrade_source

    def test_downgrade_drops_constraints_first(self, downgrade_source):
        assert "DROP CONSTRAINT IF EXISTS fk_product_role_global_role" in downgrade_source
        assert "DROP CONSTRAINT IF EXISTS uq_product_role_product_global" in downgrade_source
        fk_pos = downgrade_source.index("DROP CONSTRAINT IF EXISTS fk_product_role_global_role")
        col_pos = downgrade_source.index("DROP COLUMN IF EXISTS global_role_id")
        assert fk_pos < col_pos, "外键须先于其列被删除"

    def test_downgrade_does_not_delete_material_rows(self, downgrade_source):
        assert "DELETE" not in downgrade_source.upper()
        assert "TRUNCATE" not in downgrade_source.upper()
        dropped = {m.group(1).lower() for m in _DROP_TABLE_RE.finditer(downgrade_source)}
        for table in _MATERIAL_TABLES:
            assert table not in dropped, f"downgrade 删除了物料表 {table}"


class TestGlobalRoleMigrationChainHealth:
    """校验迁移链健康性：单一 head、无分叉，045 位于主链且父为 044，生产链 042–044 齐全。"""

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

    def test_head_is_dynamically_derived_leaf(self, script_dir):
        """迁移图的 head 必须等于「从图里动态推导的叶子修订」——不再写死修订字符串。

        历史写法 ``get_heads() == ['pg_standalone_045_global_role']`` 会在任何下游迁移
        （如本次新增 046/047）加入后误报为掉链/分叉（实为链被正确延长）。
        改为：从 revision 图推导出「不是任何人的 down_revision 的修订」= 叶子集合，
        再与 ``ScriptDirectory.get_heads()`` 交叉校验；今后新增迁移自动跟随，无需改本用例。
        045 仍在主链上（由 ``test_global_role_in_chain`` 保证）。
        """
        revs = list(script_dir.walk_revisions())
        downs: set[str] = set()
        for rev in revs:
            d = rev.down_revision
            if isinstance(d, (tuple, list)):
                downs.update(str(x) for x in d if x)
            elif d:
                downs.add(str(d))
        leaves = sorted({rev.revision for rev in revs} - downs)
        assert leaves, "迁移图未推导出任何叶子（head）修订"
        assert script_dir.get_heads() == leaves, (
            f"动态推导 head {leaves} 与 ScriptDirectory.get_heads() {script_dir.get_heads()} 不一致"
        )

    def test_global_role_in_chain(self, chain_revisions):
        assert "pg_standalone_045_global_role" in chain_revisions

    def test_production_chain_042_to_044_in_chain(self, chain_revisions):
        # 生产已应用的 042–044 必须在图内，否则与生产 alembic_version 冲突
        for rev in (
            "pg_standalone_041_web_vital",
            "pg_standalone_042_rename_pattern_room_permission",
            "pg_standalone_043_seed_missing_permissions",
            "pg_standalone_044_seed_beile_export_print",
        ):
            assert rev in chain_revisions, f"迁移链缺失 {rev}"
