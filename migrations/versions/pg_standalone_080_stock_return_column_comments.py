"""库存退货表两处列注释追平 ORM metadata（补 070/071 裸 SQL 漏写的 COMMENT）

背景
----
`alembic check`（CI 空库门禁）在 head 上检出两处 `modify_comment` 漂移：

    stock_return.stockout_id  '关联出货ID'  →  '关联出货ID（P1 起可空：按产品退货不关联出货，仅历史行有值）'
    stock_return.status       None          →  '状态：active正常/cancelled已取消'

根因：`add_stock_return.py` 建表时 stockout_id 的注释是旧文案；status 列由
`pg_standalone_070_stock_return_status` 用裸 `op.execute("ALTER TABLE ... ADD COLUMN")`
添加，从未写 COMMENT；`pg_standalone_071` 只 `DROP NOT NULL`。而 ORM
（`shared_models/stock_return.py`）两列的 `comment=` 早已是新文案 —— 空库
`upgrade head` 后 schema 注释对不上 ORM，`alembic check` 判定存在未生成的升级操作。

为何新增迁移而非回改 070/071：两者可能已应用于生产，改历史迁移不会重跑，
只会让「已应用」语义与最终状态错位；补一个追平迁移对本仓既定范式
（参考 `pg_standalone_054_sync_schema_with_orm_metadata`）不增 root、不动迁移图。

幂等：`COMMENT ON COLUMN` 可重复执行。

Revision ID: pg_standalone_080_stock_return_column_comments
Revises: pg_standalone_079_report_flow_row_action_permissions
Create Date: 2026-10-08
"""
from alembic import op

revision = 'pg_standalone_080_stock_return_column_comments'
down_revision = 'pg_standalone_079_report_flow_row_action_permissions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "COMMENT ON COLUMN stock_return.stockout_id IS "
        "'关联出货ID（P1 起可空：按产品退货不关联出货，仅历史行有值）'"
    )
    op.execute(
        "COMMENT ON COLUMN stock_return.status IS '状态：active正常/cancelled已取消'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON COLUMN stock_return.status IS NULL")
    op.execute("COMMENT ON COLUMN stock_return.stockout_id IS '关联出货ID'")
