"""purchase_order 增加 items_version（明细版本号，BOM 同步/编辑冲突保护）

Revision ID: pg_standalone_118_add_po_items_version
Revises: pg_standalone_117_add_role_final_versions
Create Date: 2026-11-11
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_118_add_po_items_version'
down_revision = 'pg_standalone_117_add_role_final_versions'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        "ALTER TABLE purchase_order "
        "ADD COLUMN IF NOT EXISTS items_version INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "COMMENT ON COLUMN purchase_order.items_version IS "
        "'采购明细版本号：BOM 同步与用户编辑都递增，用于 409 并发保护'"
    )


def downgrade():
    if base_schema_absent():
        return
    op.execute('ALTER TABLE purchase_order DROP COLUMN IF EXISTS items_version')
