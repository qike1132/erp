"""rebuild dedup index with COALESCE for NULL safety

Revision ID: rebuild_po_dedup_index
Revises: add_po_dedup_unique_index
Create Date: 2026-06-18

背景
----
前一个迁移 ``add_po_dedup_unique_index`` 创建了 partial unique index：

    (customer_id, supplier_id, source_order_ids) WHERE status='pending'

但 PostgreSQL 的唯一约束对 NULL 值不生效（NULL != NULL）。当 BOM 物料的
``supplier_id`` 为 NULL 时（实际数据中 ``product_fabric`` 表 4 条记录全部
为 NULL），``purchase_order.supplier_id`` 也是 NULL，约束完全失效，导致
每次审核都产生 4 条重复 pending 采购单。

修复
----
删除旧索引，改用 ``COALESCE`` 表达式索引，将 NULL 视为 0：

    (COALESCE(customer_id, 0), COALESCE(supplier_id, 0), source_order_ids)
    WHERE status = 'pending'

这样 ``supplier_id`` 为 NULL 的记录会被视为 0，唯一约束正常生效。
"""
from alembic import op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent

revision = 'rebuild_po_dedup_index'
down_revision = 'add_po_dedup_unique_index'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.execute(text("DROP INDEX IF EXISTS uq_po_pending_dedup"))
    op.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_po_pending_dedup
        ON purchase_order (COALESCE(customer_id, 0), COALESCE(supplier_id, 0), source_order_ids)
        WHERE status = 'pending'
        """
    ))


def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.execute(text("DROP INDEX IF EXISTS uq_po_pending_dedup"))
    op.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_po_pending_dedup
        ON purchase_order (customer_id, supplier_id, source_order_ids)
        WHERE status = 'pending'
        """
    ))
