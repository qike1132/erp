"""编号巡检结果表：counter_behind + 格式违规落库

为 services/numbering 巡检（ARQ cron numbering_audit_task）提供持久化：
每轮每个编号实体写一行（scope=前缀），格式违规另写一行（scope=<表>.<列>）。
只读端点 GET /api/v1/numbering-audit 拉取最近记录。

Revision ID: pg_standalone_059_numbering_audit
Revises: pg_standalone_058_fix_tz_naive_order_dates
Create Date: 2026-09-29
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_059_numbering_audit'
down_revision = 'pg_standalone_058_fix_tz_naive_order_dates'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'numbering_audit',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('scope', sa.String(length=64), nullable=False,
                  comment='PO/BH/... 或 <表>.<列>'),
        sa.Column('counter_behind', sa.Integer(), nullable=False, server_default='0',
                  comment='1=水位落后数据'),
        sa.Column('detail', sa.String(length=255), nullable=False, server_default='',
                  comment='偏差描述'),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False,
                  comment='巡检时间'),
    )


def downgrade() -> None:
    op.drop_table('numbering_audit')
