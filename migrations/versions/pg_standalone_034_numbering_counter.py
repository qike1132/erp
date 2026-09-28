"""编号计数表：跨进程无重号序号分配

为 services.numbering.allocate_sequence 提供持久化计数水位：
以 (prefix, number_date) 为粒度，INSERT ... ON CONFLICT DO UPDATE 原子递增。
计数独立短事务提交，与业务事务解耦（业务回滚仅跳号，不重号）。

Revision ID: pg_standalone_034_numbering_counter
Revises: pg_standalone_017_product_aggregate_mv
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_034_numbering_counter'
down_revision = 'pg_standalone_017_product_aggregate_mv'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'numbering_counter',
        sa.Column('prefix', sa.String(length=20), primary_key=True),
        sa.Column('number_date', sa.String(length=8), primary_key=True),
        sa.Column('last_seq', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('numbering_counter')
