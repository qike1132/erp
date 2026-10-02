"""皮套管理（case）表结构重写：统一流水台账 + 主件/配件 + 单位

背景
----
皮套管理全栈重写（见实施计划）。旧结构有两个真值来源——`case.current_stock`
与聚合 `Σ入库 − Σ出库`——会漂移；且写路径绕过统一库存写入口，导致"库存对不上"。

本次把四张表收敛为「一条 SKU 主档 + 一张统一流水」：

- 扩展现有 `case` 表：新增 `unit`（单位）、`parent_id`（配件所属主件，自引用 FK）、
  `qty_per_set`（每套配比，先存着备用）。主件与配件同为 `case` 行，配件靠
  `parent_id` 归属主件。
- 新增 `case_movement`：统一出入库流水（`direction` = in/out），**取代**
  `case_stock_in` / `case_stock_out` / `case_inventory_log` 三张表。
- 删除上述三张旧表。业务已确认**存量数据可弃**，不做数据迁移。

同时补齐 `case_manage` 权限码：此前只在 `scripts/init_permissions.py` 注册、
迁移链中从未种入，空库重放会缺该权限。

幂等
----
建表用 `IF NOT EXISTS`、加列用 `ADD COLUMN IF NOT EXISTS`、约束/索引带存在性
守卫、权限种入用 `NOT EXISTS`——重复执行安全。

Revision ID: pg_standalone_062_case_management_rebuild
Revises: pg_standalone_061_add_product_stock_check
Create Date: 2026-10-02
"""
from alembic import op

from migrations._legacy_base_guard import table_exists

revision = 'pg_standalone_062_case_management_rebuild'
down_revision = 'pg_standalone_061_add_product_stock_check'
branch_labels = None
depends_on = None

# 回滚时重建的旧三表（与 pg_standalone_001 初始建表 + updated_at 一致；空表）
_LEGACY_TABLES_DDL = (
    'CREATE TABLE IF NOT EXISTS case_stock_in ('
    ' id SERIAL NOT NULL, stockin_no VARCHAR(20) NOT NULL,'
    ' stockin_date TIMESTAMP WITH TIME ZONE, customer VARCHAR(100) NOT NULL,'
    ' case_id INTEGER NOT NULL, quantity INTEGER NOT NULL, note TEXT,'
    ' updated_at TIMESTAMP WITH TIME ZONE,'
    ' PRIMARY KEY (id), UNIQUE (stockin_no),'
    ' FOREIGN KEY(case_id) REFERENCES "case" (id))',
    'CREATE INDEX IF NOT EXISTS idx_case_stockin_case_date ON case_stock_in (case_id, stockin_date)',
    'CREATE TABLE IF NOT EXISTS case_stock_out ('
    ' id SERIAL NOT NULL, stockout_no VARCHAR(20) NOT NULL,'
    ' stockout_date TIMESTAMP WITH TIME ZONE, case_id INTEGER NOT NULL,'
    ' quantity INTEGER NOT NULL, customer VARCHAR(100), note TEXT,'
    ' updated_at TIMESTAMP WITH TIME ZONE,'
    ' PRIMARY KEY (id), UNIQUE (stockout_no),'
    ' FOREIGN KEY(case_id) REFERENCES "case" (id))',
    'CREATE INDEX IF NOT EXISTS idx_case_stockout_case_date ON case_stock_out (case_id, stockout_date)',
    'CREATE TABLE IF NOT EXISTS case_inventory_log ('
    ' id SERIAL NOT NULL, case_id INTEGER NOT NULL, change_type VARCHAR(20) NOT NULL,'
    ' change_quantity INTEGER NOT NULL, change_date TIMESTAMP WITH TIME ZONE,'
    ' related_id VARCHAR(50), note TEXT, customer VARCHAR(100),'
    ' updated_at TIMESTAMP WITH TIME ZONE,'
    ' PRIMARY KEY (id),'
    ' FOREIGN KEY(case_id) REFERENCES "case" (id) ON DELETE CASCADE)',
    'CREATE INDEX IF NOT EXISTS idx_case_inventory_log_case_date ON case_inventory_log (case_id, change_date DESC)',
)


def upgrade() -> None:
    # 1. 删除旧的皮套流水/单据/日志三表（存量数据可弃，不迁移）
    for tbl in ('case_inventory_log', 'case_stock_in', 'case_stock_out'):
        op.execute(f'DROP TABLE IF EXISTS "{tbl}"')

    # 2. 扩展 `case` 主档：单位 / 所属主件 / 配比
    if table_exists('case'):
        op.execute('ALTER TABLE "case" ADD COLUMN IF NOT EXISTS unit VARCHAR(20)')
        op.execute('ALTER TABLE "case" ADD COLUMN IF NOT EXISTS parent_id INTEGER')
        op.execute(
            'ALTER TABLE "case" ADD COLUMN IF NOT EXISTS qty_per_set INTEGER NOT NULL DEFAULT 1'
        )
        # 自引用外键（配件 → 主件）；删主件时配件不删，退化为独立 SKU
        op.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_case_parent') THEN
                    ALTER TABLE "case"
                        ADD CONSTRAINT fk_case_parent
                        FOREIGN KEY (parent_id) REFERENCES "case" (id) ON DELETE SET NULL;
                END IF;
            END $$;
            """
        )
        op.execute('CREATE INDEX IF NOT EXISTS idx_case_parent ON "case" (parent_id)')
        op.execute("COMMENT ON COLUMN \"case\".unit IS '单位'")
        op.execute("COMMENT ON COLUMN \"case\".parent_id IS '所属主件ID（配件用；主件为空）'")
        op.execute("COMMENT ON COLUMN \"case\".qty_per_set IS '每套主件配比（先存着备用）'")

    # 3. 统一流水台账
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS case_movement (
            id SERIAL NOT NULL,
            case_id INTEGER NOT NULL,
            direction VARCHAR(3) NOT NULL,
            movement_no VARCHAR(30) NOT NULL,
            quantity INTEGER NOT NULL,
            customer VARCHAR(100),
            movement_date TIMESTAMP WITH TIME ZONE,
            note TEXT,
            create_time TIMESTAMP WITH TIME ZONE,
            updated_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (id),
            CONSTRAINT uq_case_movement_no UNIQUE (movement_no),
            CONSTRAINT ck_case_movement_direction CHECK (direction IN ('in', 'out')),
            CONSTRAINT ck_case_movement_qty_positive CHECK (quantity > 0),
            FOREIGN KEY(case_id) REFERENCES "case" (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_case_movement_case_date'
        ' ON case_movement (case_id, movement_date)'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_case_movement_dir_date'
        ' ON case_movement (direction, movement_date)'
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_case_movement_customer_date'
        ' ON case_movement (customer, movement_date)'
    )
    op.execute("COMMENT ON COLUMN case_movement.direction IS '方向：in=入库 / out=出库'")
    op.execute("COMMENT ON COLUMN case_movement.movement_no IS '单号（CSI-/CSO-）'")

    # 4. 幂等种入 case_manage 权限（空库重放时缺失；生产库已存在则跳过）
    op.execute(
        """
        INSERT INTO permission (name, code, parent_id, icon, is_nav, sort_order, updated_at)
        SELECT '皮套管理', 'case_manage', NULL, 'fa-suitcase', true, 0, now()
        WHERE NOT EXISTS (SELECT 1 FROM permission WHERE code = 'case_manage')
        """
    )


def downgrade() -> None:
    # 回滚：删流水表、移除新增列、重建旧三表（空表；数据不可恢复）
    op.execute('DROP TABLE IF EXISTS case_movement')
    if table_exists('case'):
        op.execute('ALTER TABLE "case" DROP CONSTRAINT IF EXISTS fk_case_parent')
        op.execute('DROP INDEX IF EXISTS idx_case_parent')
        op.execute('ALTER TABLE "case" DROP COLUMN IF EXISTS qty_per_set')
        op.execute('ALTER TABLE "case" DROP COLUMN IF EXISTS parent_id')
        op.execute('ALTER TABLE "case" DROP COLUMN IF EXISTS unit')

    for ddl in _LEGACY_TABLES_DDL:
        op.execute(ddl)

    op.execute(
        "DELETE FROM user_permission WHERE permission_id IN "
        "(SELECT id FROM permission WHERE code = 'case_manage')"
    )
    op.execute("DELETE FROM permission WHERE code = 'case_manage'")
