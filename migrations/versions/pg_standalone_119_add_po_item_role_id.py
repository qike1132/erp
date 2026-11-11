"""purchase_order_item 增加 role_id（损耗率/数量按 角色+部位 独立口径）

Revision ID: pg_standalone_119_add_po_item_role_id
Revises: pg_standalone_118_add_po_items_version
Create Date: 2026-11-11

存量行不回填：NULL = 默认 BOM / 历史行 / 手工行；pending 单在下次 BOM
保存/重建时按新口径自然生成，completed 单保持快照不动。
"""
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_119_add_po_item_role_id'
down_revision = 'pg_standalone_118_add_po_items_version'
branch_labels = None
depends_on = None


def upgrade():
    if base_schema_absent():
        return
    op.execute(
        "ALTER TABLE purchase_order_item "
        "ADD COLUMN IF NOT EXISTS role_id INTEGER"
    )
    op.execute(
        "COMMENT ON COLUMN purchase_order_item.role_id IS "
        "'产品角色ID（BOM 作用域）：同物料跨角色/跨部位各自成行；NULL=默认BOM/历史/手工'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_perf_poi_order_role "
        "ON purchase_order_item (order_id, role_id)"
    )


def downgrade():
    if base_schema_absent():
        return
    op.execute('DROP INDEX IF EXISTS idx_perf_poi_order_role')
    op.execute('ALTER TABLE purchase_order_item DROP COLUMN IF EXISTS role_id')
