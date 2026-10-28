"""新增采购单人工生成幂等登记表（BOM 缺失下单续提 P0）。

仅新增 purchase_order_generate_attempt，不修改来源单、采购单或既有索引。
登记与生成结果在同一事务提交；downgrade 只删除本迁移新建表。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'pg_standalone_105_purchase_order_generate_idempotency'
down_revision = 'pg_standalone_104_dedup_default_bom_rows'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'purchase_order_generate_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('request_hash', sa.String(length=64), nullable=False),
        sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'actor_id', 'idempotency_key',
            name='uq_po_generate_attempt_actor_key',
        ),
    )


def downgrade() -> None:
    op.drop_table('purchase_order_generate_attempt')
