"""rebuild po dedup index to use supplier_name instead of supplier_id

Revision ID: rebuild_po_dedup_use_supplier_name
Revises: add_file_records_table, add_user_factory_and_notification
Create Date: 2026-08-04

背景
----
前一个迁移 ``rebuild_po_dedup_index`` 使用 ``COALESCE(supplier_id, 0)`` 构建
partial unique index：

    (COALESCE(customer_id, 0), COALESCE(supplier_id, 0), source_order_ids)
    WHERE status='pending'

但业务层在 ``one_click_generate_order`` 中按 ``supplier_name`` 分组生成采购单
（不同供应商的物料各自生成一张单）。当 BOM 物料的 ``supplier_id`` 为 NULL 但
``supplier_name`` 不同时（实测 ``product_fabric`` / ``product_material`` /
``product_accessory`` 所有记录 ``supplier_id`` 均为 NULL，``supplier_name`` 有
"汇维仕"/"三虎"/"远华"/"美易达" 等多个值），同一客户订单会生成多张
``supplier_id=NULL`` 的采购单，它们在 ``COALESCE(supplier_id, 0)`` 下全部归入
bucket 0，互相冲突触发 IntegrityError。

endpoint 层捕获后调用 ``fetch_existing_pending_for_composite_ids`` 回查，但
冲突发生在新订单之间（同事务内），回滚后无任何已存在 pending 单，于是返回
"已存在 0 个对应采购单（并发幂等）"——这就是用户在 /purchase 页面审核时报的 BUG。

修复
----
删除旧索引，改用 ``supplier_name`` 作为 dedup 维度，与业务层分组逻辑对齐：

    (COALESCE(customer_id, 0), COALESCE(supplier_name, ''), source_order_ids)
    WHERE status = 'pending'

``supplier_name`` 由 ``create_purchase_order`` 从 BOM 物料透传，始终有值
（默认 ''），不存在 NULL 合并问题。

同时合并 alembic 两个 head（add_file_records_table / add_user_factory_and_notification）。
"""
from alembic import op
from sqlalchemy import text

revision = 'rebuild_po_dedup_use_supplier_name'
down_revision = ('add_file_records_table', 'add_user_factory_and_notification')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uq_po_pending_dedup"))
    op.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_po_pending_dedup
        ON purchase_order (COALESCE(customer_id, 0), COALESCE(supplier_name, ''), source_order_ids)
        WHERE status = 'pending'
        """
    ))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uq_po_pending_dedup"))
    op.execute(text(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_po_pending_dedup
        ON purchase_order (COALESCE(customer_id, 0), COALESCE(supplier_id, 0), source_order_ids)
        WHERE status = 'pending'
        """
    ))
