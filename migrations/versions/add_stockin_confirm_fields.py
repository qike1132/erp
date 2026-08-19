"""湖北备货确认流程：stock_in 表新增确认时间/确认人字段

Revision ID: add_stockin_confirm_fields
Revises: pg_standalone_033_changelog_project_id_nullable
Create Date: 2026-08-18

背景：
- beile-order（湖北订单）页面的备货（StockIn）记录原先不参与确认流程，
  现按订单确认流程对齐：备货入库后同样需要人工确认，确认前显示「未确认」
  标识并提供「确认备货」按钮，确认后转为「已确认」。
- 与 order 表确认字段（add_order_confirm_fields）保持一致的正交设计：
  confirmed_at / confirmed_by_id 独立于备货业务字段，不影响库存逻辑。

数据兼容：
- 存量备货记录统一回填 confirmed_at = stockin_date，视为已确认，
  仅迁移后新建的备货（confirmed_at IS NULL）进入「未确认」待确认流程。
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'add_stockin_confirm_fields'
down_revision = 'pg_standalone_033_changelog_project_id_nullable'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'stock_in',
        sa.Column('confirmed_at', sa.DateTime(), nullable=True, comment='备货确认时间（湖北备货确认流程）'),
    )
    op.add_column(
        'stock_in',
        sa.Column('confirmed_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, comment='备货确认人ID'),
    )
    op.create_index('ix_stock_in_confirmed_at', 'stock_in', ['confirmed_at'])

    # 存量备货回填：视为已确认，避免历史备货全部落入「未确认」待办
    op.execute(
        'UPDATE stock_in SET confirmed_at = stockin_date WHERE confirmed_at IS NULL'
    )


def downgrade():
    op.drop_index('ix_stock_in_confirmed_at', table_name='stock_in')
    op.drop_column('stock_in', 'confirmed_by_id')
    op.drop_column('stock_in', 'confirmed_at')
