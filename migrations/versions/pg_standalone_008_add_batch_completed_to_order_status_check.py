"""add_batch_completed_to_order_status_check

Revision ID: pg_standalone_008
Revises: pg_standalone_007
Create Date: 2026-05-07

Updates order_status_check to include '批次已完成' status.
PostgreSQL does not support ALTER CONSTRAINT, so we drop and recreate.
"""

from alembic import op

revision = 'pg_standalone_008'
down_revision = 'pg_standalone_007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE \"order\" DROP CONSTRAINT order_status_check"
    )
    op.execute(
        "ALTER TABLE \"order\" ADD CONSTRAINT order_status_check "
        "CHECK (\"status\" IN ('待备货', '部分备货', '已备货', '待出货', '已出货', '已取消', '批次已完成'))"
    )


def downgrade():
    op.execute(
        "ALTER TABLE \"order\" DROP CONSTRAINT order_status_check"
    )
    op.execute(
        "ALTER TABLE \"order\" ADD CONSTRAINT order_status_check "
        "CHECK (\"status\" IN ('待备货', '部分备货', '已备货', '待出货', '已出货', '已完成', '已取消'))"
    )
