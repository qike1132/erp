"""daily_production_record 增加客户字段

生产录入增加可选客户选择：新增 customer_id（关联 customer.id）与 customer_name
快照列。纯新增可空列和索引，不改既有数据、不做破坏性 DDL。

Revision ID: pg_standalone_097_add_daily_production_customer
Revises: pg_standalone_096_stockin_batch_fields
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_097_add_daily_production_customer'
down_revision = 'pg_standalone_096_stockin_batch_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'daily_production_record',
        sa.Column(
            'customer_id',
            sa.Integer(),
            sa.ForeignKey('customer.id', ondelete='SET NULL'),
            nullable=True,
            comment='客户ID',
        ),
    )
    op.add_column(
        'daily_production_record',
        sa.Column(
            'customer_name',
            sa.String(length=100),
            nullable=True,
            comment='客户名称(冗余)',
        ),
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS idx_dpr_customer_id '
        'ON daily_production_record (customer_id)'
    )


def downgrade() -> None:
    # 只新增可空列和索引；回滚保留列，避免在非空库上自动执行破坏性 DDL。
    pass
