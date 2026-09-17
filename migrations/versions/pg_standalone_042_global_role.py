"""全局角色字典：新增 role 表 + product_role.global_role_id 回填与归并

**背景**

角色此前是「产品私有」：`product_role(product_id, role_name)` 无全局唯一约束，
同一角色在多个产品下重复建、名称易漂移（`爸爸` / `爸爸 ` / `Dad`）。本迁移把角色
升级为**全局字典**：

1. 新建 `role` 表（`lower(name)` 函数唯一索引实现「trim 存储 + 大小写不敏感唯一」，
   不引入 `citext` 扩展）；
2. `product_role` 加 `global_role_id`，按 `lower(btrim(role_name))` 上卷回填；
3. 同产品下归并为同一全局角色的多行 `product_role` **合并**（保 `min(id)`），
   并把其物料行改指保留行（`product_material` 有 `uq_product_material_product_role`
   唯一约束，需先按组去重再改指，否则迁移中止——风险 M4）；
4. 收紧 `global_role_id` 为 `NOT NULL` 并加 `uq_product_role_product_global` 唯一约束
   与 `ON DELETE RESTRICT` 外键（删全局角色被 DB 级拒绝）。

**轻迁移**：三张物料表（`product_material` / `product_fabric` / `product_accessory`）
的字段与外键（`role_id → product_role.id`）**零改动**——拖住最重的「生产机 DB 迁移
不可逆」风险。

**幂等**：DDL 一律 `IF NOT EXISTS` / `DO $$ ... IF NOT EXISTS`；只回填
`global_role_id IS NULL` 的行；上卷 `INSERT` 用 `ON CONFLICT DO NOTHING`；
重复执行结果不变。

**事务边界**：本迁移不自行开事务——由 Alembic 的 env（单事务）包裹，任一步失败
整体回滚，业务零影响。

Revision ID: pg_standalone_042_global_role
Revises: pg_standalone_041_web_vital  (已复核为 pg_standalone 系列 head)
Create Date: 2026-09-17
"""
from alembic import op

revision = 'pg_standalone_042_global_role'
down_revision = 'pg_standalone_041_web_vital'
branch_labels = None
depends_on = None

# 三张物料表的归并策略表（表名 → 该表是否在 (product_id, role_id) 上有唯一约束）。
# 策略表驱动，避免写三份 if/elif；两类表用各自的 SQL 模板处理。
_MERGE_TABLES: tuple[tuple[str, bool], ...] = (
    ('product_material', True),   # uq_product_material_product_role → 需去重
    ('product_fabric', False),    # 无唯一约束 → 直接改指
    ('product_accessory', False),
)

# 无唯一约束表的改指 SQL（一条 UPDATE 即可）
_MERGE_REASSIGN_PLAIN = 'UPDATE {table} t SET role_id = d.keep_id FROM _pr_dup d WHERE t.role_id = d.dup_id;'

# 有唯一约束表：先按 (product_id, keep_role_id) 分组保 min(id)，再把幸存行改指保留角色。
_MERGE_UNIQUE_STEPS = (
    (
        'DROP TABLE IF EXISTS _pm_group;'
        'CREATE TEMP TABLE _pm_group AS '
        'SELECT pm.id AS mid, pm.product_id AS product_id, '
        'COALESCE(d.keep_id, pm.role_id) AS keep_role_id '
        'FROM product_material pm LEFT JOIN _pr_dup d ON d.dup_id = pm.role_id '
        'WHERE pm.role_id IS NOT NULL;'
    ),
    (
        'DELETE FROM product_material WHERE id IN ('
        'SELECT mid FROM ('
        'SELECT mid, ROW_NUMBER() OVER '
        '(PARTITION BY product_id, keep_role_id ORDER BY mid) AS rn '
        'FROM _pm_group) ranked WHERE ranked.rn > 1);'
    ),
    (
        'UPDATE product_material pm SET role_id = g.keep_role_id '
        'FROM _pm_group g WHERE pm.id = g.mid '
        'AND pm.role_id IS DISTINCT FROM g.keep_role_id;'
    ),
    'DROP TABLE IF EXISTS _pm_group;',
)


def _create_role_dictionary() -> None:
    """建 role 表 + lower(name) 函数唯一索引 + 注释（幂等）。"""
    op.execute(
        'CREATE TABLE IF NOT EXISTS role ('
        'id SERIAL PRIMARY KEY,'
        'name VARCHAR(100) NOT NULL,'
        'create_time TIMESTAMPTZ NOT NULL DEFAULT now(),'
        'update_time TIMESTAMPTZ NOT NULL DEFAULT now());'
    )
    op.execute("COMMENT ON TABLE role IS '全局角色字典(跨产品复用)';")
    op.execute(
        "COMMENT ON COLUMN role.name IS "
        "'全局角色名(trim 后存储,大小写不敏感唯一)';"
    )
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_role_name_lower ON role (lower(name));'
    )


def _add_global_role_column() -> None:
    """给 product_role 加 global_role_id 列（先 nullable，回填后再收紧）。"""
    op.execute('ALTER TABLE product_role ADD COLUMN IF NOT EXISTS global_role_id INTEGER;')
    op.execute(
        "COMMENT ON COLUMN product_role.global_role_id IS "
        "'全局角色ID(role.id); 与 product_id 组合唯一';"
    )


def _backfill_global_role_id() -> None:
    """上卷全局角色字典 + 回填 global_role_id（幂等）。"""
    # 1) 上卷：按 btrim(role_name) 去重入全局字典；大小写变体靠唯一索引 DO NOTHING 去重
    op.execute(
        'INSERT INTO role(name) SELECT DISTINCT btrim(role_name) FROM product_role '
        "WHERE btrim(role_name) <> '' "
        'ON CONFLICT DO NOTHING;'
    )
    # 2) 回填：仅未回填行（幂等）
    op.execute(
        'UPDATE product_role pr SET global_role_id = r.id FROM role r '
        'WHERE pr.global_role_id IS NULL '
        'AND lower(btrim(pr.role_name)) = lower(r.name);'
    )


def _merge_duplicate_roles() -> None:
    """同产品下同一全局角色的多行 product_role 归并为 1 行（保 min(id)）。

    归并顺序至关重要：必须**先把物料行改指保留角色**，再删重复 product_role 行，
    否则 `product_role` 的 `ON DELETE CASCADE` 会连带删除其物料行（数据丢失）。
    """
    op.execute('DROP TABLE IF EXISTS _pr_dup;')
    op.execute(
        'CREATE TEMP TABLE _pr_dup AS '
        'SELECT pr.id AS dup_id, k.keep_id AS keep_id '
        'FROM product_role pr JOIN ('
        'SELECT product_id, global_role_id, MIN(id) AS keep_id '
        'FROM product_role WHERE global_role_id IS NOT NULL '
        'GROUP BY product_id, global_role_id HAVING COUNT(*) > 1) k '
        'ON k.product_id = pr.product_id '
        'AND k.global_role_id = pr.global_role_id '
        'WHERE pr.id <> k.keep_id;'
    )
    for table, has_unique in _MERGE_TABLES:
        if has_unique:
            for sql in _MERGE_UNIQUE_STEPS:
                op.execute(sql)
        else:
            op.execute(_MERGE_REASSIGN_PLAIN.format(table=table))
    # 物料已改指保留角色，此删不会级联丢物料
    op.execute('DELETE FROM product_role pr USING _pr_dup d WHERE pr.id = d.dup_id;')
    op.execute('DROP TABLE IF EXISTS _pr_dup;')


def _tighten_constraints() -> None:
    """加唯一约束 + 外键 + 收紧 NOT NULL（幂等；存在空白名无法回填则中止）。"""
    op.execute(
        'DO $$ BEGIN '
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = "
        "'uq_product_role_product_global' AND conrelid = 'product_role'::regclass) THEN "
        'ALTER TABLE product_role ADD CONSTRAINT uq_product_role_product_global '
        'UNIQUE (product_id, global_role_id); END IF; END $$;'
    )
    op.execute('ALTER TABLE product_role ALTER COLUMN global_role_id SET NOT NULL;')
    op.execute(
        'DO $$ BEGIN '
        "IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = "
        "'fk_product_role_global_role' AND conrelid = 'product_role'::regclass) THEN "
        'ALTER TABLE product_role ADD CONSTRAINT fk_product_role_global_role '
        'FOREIGN KEY (global_role_id) REFERENCES role(id) ON DELETE RESTRICT; END IF; '
        'END $$;'
    )


def upgrade() -> None:
    _create_role_dictionary()
    _add_global_role_column()
    _backfill_global_role_id()
    _merge_duplicate_roles()
    _tighten_constraints()


def downgrade() -> None:
    """结构回滚（**不反向拆分已合并的数据**）。

    边界声明：归并阶段被合并掉的重复 `product_role` 行（及其被去重的重复物料行）
    **不会随 downgrade 还原**——这些行已被物理删除，无信息可反向重建。若确需还原，
    须从前置 `pg_dump` 全库备份中恢复。发布说明须预先登记此边界。
    三张物料表的行数在回滚后被合并行影响的部分同样不还原（结构回滚，数据不反向拆分）。
    """
    op.execute('ALTER TABLE product_role DROP CONSTRAINT IF EXISTS fk_product_role_global_role;')
    op.execute('ALTER TABLE product_role DROP CONSTRAINT IF EXISTS uq_product_role_product_global;')
    op.execute('ALTER TABLE product_role DROP COLUMN IF EXISTS global_role_id;')
    op.execute('DROP TABLE IF EXISTS role;')
