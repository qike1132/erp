"""purchase_order_status_check_constraint

Revision ID: pg_standalone_102_purchase_order_status_check
Revises: pg_standalone_101_backup_record_comment
Create Date: 2026-10-20

P1-16：purchase_order.status 此前只有 String(20)、无 CHECK，Update DTO 与服务层
直通任意字符串 → 状态机漂移。本迁移补白名单约束，与
fastapi_app/shared_models/purchase_order.py 的 PurchaseOrderStatus.ALL
（pending / completed / 历史 confirmed）逐字一致。

NOT VALID：不扫描存量（生产可能含历史 confirmed 或脏值），新写入立即受约束；
存量清理后再单独 VALIDATE CONSTRAINT。
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_102_purchase_order_status_check'
down_revision = 'pg_standalone_101_backup_record_comment'
branch_labels = None
depends_on = None

# ⚠️ 必须与 PurchaseOrderStatus.ALL 逐字一致；由
# tests/test_purchase_order_status_check_migration.py 断言。
PURCHASE_ORDER_STATUSES = ('pending', 'completed', 'confirmed')


def _add_constraint_sql() -> str:
    values = ', '.join(f"'{s}'" for s in PURCHASE_ORDER_STATUSES)
    return (
        'ALTER TABLE purchase_order ADD CONSTRAINT purchase_order_status_check '
        f'CHECK (status IN ({values})) NOT VALID'
    )


def upgrade():
    if base_schema_absent():
        return
    op.execute('ALTER TABLE purchase_order DROP CONSTRAINT IF EXISTS purchase_order_status_check')
    op.execute(_add_constraint_sql())


def downgrade():
    if base_schema_absent():
        return
    op.execute('ALTER TABLE purchase_order DROP CONSTRAINT IF EXISTS purchase_order_status_check')
