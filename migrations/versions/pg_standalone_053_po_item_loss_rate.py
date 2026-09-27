"""采购单明细新增材料损耗率快照：purchase_order_item.loss_rate

**背景**

``/purchase`` 汇总下单弹窗的损耗率需支持「按表格中每一行布料（物料）单独配置」。
原有 ``purchase_order.spare_rate`` 只能表达「订单级」单一损耗率，无法承载同一采购单内
不同布料的差异化损耗率，故在采购单明细表新增一列：

- ``loss_rate NUMERIC(8,2)``：该明细布料的材料损耗率快照（千分之几）。
  为 NULL 表示「未单独配置」，前端回退到订单级 ``spare_rate`` 作为默认值。

**可空性/默认值**：可空且不带 ``server_default``，避免既有大表 ``SET DEFAULT`` 重写；
历史行保持 NULL。

**幂等**：``ADD COLUMN IF NOT EXISTS``，重复执行结果不变。

**回滚**：对称删列，无反向数据重建。

**链位置**：接在 052（Order.product 置空迁移）之后。

Revision ID: pg_standalone_053_po_item_loss_rate
Revises: pg_standalone_052_order_product_set_null
Create Date: 2026-09-27
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_053_po_item_loss_rate'
down_revision = 'pg_standalone_052_order_product_set_null'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        'ALTER TABLE purchase_order_item ADD COLUMN IF NOT EXISTS loss_rate NUMERIC(8,2)'
    ))
    op.execute(sa.text(
        "COMMENT ON COLUMN purchase_order_item.loss_rate IS "
        "'材料损耗率快照(千分之几)，逐布料行配置；NULL=未单独配置，回退订单级spare_rate'"
    ))


def downgrade() -> None:
    op.execute(sa.text('ALTER TABLE purchase_order_item DROP COLUMN IF EXISTS loss_rate'))
