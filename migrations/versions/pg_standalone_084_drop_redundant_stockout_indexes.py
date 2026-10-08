"""收口冗余/错名索引：删 2 条 partial 子集、改 1 条名对齐 ORM（P2a-B）

Revision ID: pg_standalone_084_drop_redundant_stockout_indexes
Revises: pg_standalone_083_declare_stockout_order_indexes
Create Date: 2026-10-05

背景（2026-10-05 只读核实）
----
- `idx_stockout_has_stockin` `(stockin_id) WHERE stockin_id IS NOT NULL`
  —— 生产已有全量 `idx_stockout_stockin (stockin_id)`，本条是其 partial 子集 → 冗余，删。
- `idx_stockout_order_stockin` `(order_id, stockin_id) WHERE stockin_id IS NOT NULL`
  —— 生产已有全量 `idx_stockout_order_type (order_id, stockin_id)`，同上冗余，删。
  （`add_missing_perf_indexes.py` 的空转注释也点名了这条重复。）
- `idx_inventory_log_product_time` `(product_id, change_date DESC)`
  —— 与 ORM / 迁移 001 声明的 `idx_inventory_log_product_date` **同列同序**，只是名字不同；
  生产**没有** `_date` 那条，故**不能删**，应**改名**对齐（否则会丢掉该列唯一的索引）。

安全性 / 幂等
----
`DROP INDEX IF EXISTS` 与 DO 块内的条件 `ALTER INDEX ... RENAME` 均幂等：
空库重放时这两条索引不存在、`_date` 已由迁移 001 建好 → 整体空转，不影响 CI 的
空库 `upgrade head` + `check`。生产库按实际存在性生效。
**本文件不代维护者执行**；是否应用到生产由维护者决定。
"""
from alembic import op
from sqlalchemy import text

revision = 'pg_standalone_084_drop_redundant_stockout_indexes'
down_revision = 'pg_standalone_083_declare_stockout_order_indexes'
branch_labels = None
depends_on = None

_RENAME_FORWARD = text("""
DO $$
BEGIN
    IF to_regclass('idx_inventory_log_product_time') IS NOT NULL
       AND to_regclass('idx_inventory_log_product_date') IS NULL THEN
        ALTER INDEX idx_inventory_log_product_time RENAME TO idx_inventory_log_product_date;
    END IF;
END $$;
""")

_RENAME_BACK = text("""
DO $$
BEGIN
    IF to_regclass('idx_inventory_log_product_date') IS NOT NULL
       AND to_regclass('idx_inventory_log_product_time') IS NULL THEN
        ALTER INDEX idx_inventory_log_product_date RENAME TO idx_inventory_log_product_time;
    END IF;
END $$;
""")


def upgrade() -> None:
    # 用 op.drop_index(..., if_exists=True)（而非裸 SQL）：既幂等，也能被
    # migrations/_destructive_scan.py 的破坏性 DDL 守卫识别并纳入基线。
    op.drop_index('idx_stockout_has_stockin', table_name='stock_out', if_exists=True)
    op.drop_index('idx_stockout_order_stockin', table_name='stock_out', if_exists=True)
    op.execute(_RENAME_FORWARD)


def downgrade() -> None:
    op.execute(_RENAME_BACK)
    op.execute(text(
        'CREATE INDEX IF NOT EXISTS idx_stockout_has_stockin '
        'ON stock_out (stockin_id) WHERE stockin_id IS NOT NULL'
    ))
    op.execute(text(
        'CREATE INDEX IF NOT EXISTS idx_stockout_order_stockin '
        'ON stock_out (order_id, stockin_id) WHERE stockin_id IS NOT NULL'
    ))
