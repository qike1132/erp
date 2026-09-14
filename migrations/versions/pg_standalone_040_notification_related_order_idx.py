"""湖北订单确认：notification.related_order_id 索引

确认湖北订单/备货时按 related_order_id 批量标记未读通知为已读；
该列此前无索引，确认操作在通知表上退化为全表扫描，随通知量增长线性恶化。

Revision ID: pg_standalone_040_notification_related_order_idx
Revises: pg_standalone_039_product_default_bom_label
Create Date: 2026-09-13
"""
from alembic import op

revision = 'pg_standalone_040_notification_related_order_idx'
down_revision = 'pg_standalone_039_product_default_bom_label'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_notification_related_order '
        'ON notification (related_order_id);'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_notification_related_order;')
