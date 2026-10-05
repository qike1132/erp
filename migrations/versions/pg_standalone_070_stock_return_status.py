"""stock_return 增加 status 列：软取消（P1-①「取消而非删除」）

背景
----
P0 的退货删除是物理删除（流水有留痕但单据消失）。开源四项目（Odoo/ERPNext/
OFBiz/jshERP）无一例外保留退货记录。P1 引入 status：

- 'active'    正常（默认，存量行经 DEFAULT 回填）
- 'cancelled' 已取消（保留记录；取消走与删除完全相同的库存对称扣回链路）

P2 审批态（草稿/待审）未来在同一列上扩展，故不加 CHECK 白名单。
取消语义的库存口径不变：退货 +N 回补 / 取消 -N 扣回，inventory_log 记
change_type='退货取消'。

幂等性：ADD COLUMN IF NOT EXISTS，重复执行安全。

Revision ID: pg_standalone_070_stock_return_status
Revises: pg_standalone_069_stock_return_permission
Create Date: 2026-10-05
"""
from alembic import op

revision = 'pg_standalone_070_stock_return_status'
down_revision = 'pg_standalone_069_stock_return_permission'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE stock_return ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE stock_return DROP COLUMN IF EXISTS status")
