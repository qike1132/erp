"""采购单备品字段：purchase_order 新增 spare_quantity / spare_rate 两列

**背景**

`/beile-order` 的订单数量与备品数量需实时同步自 `/purchase` 的真实下单数据。
备品真相源是「汇总下单」弹窗里的损耗率（千分之几）：`备品 = ceil(订单数量 × 损耗率‰)`。
原先备品只活在前端会话态，本次将其落库，故 `purchase_order` 新增两列：

1. `spare_quantity NUMERIC(12,2)`：备品数量，随下单完成 / 保存修改写入；
2. `spare_rate NUMERIC(8,2)`：损耗率快照(千分之几)，用于追溯该备品按多少损耗率算出。

**可空性/默认值**：两列均**可空且不带 server_default**，避免在既有大表上触发
`SET DEFAULT` 全表重写 / 长事务锁表。历史行保持 NULL，展示层按「无损耗率记录」处理。

**幂等**：DDL 一律 `ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS`，
重复执行结果不变。

**回滚**：`downgrade()` 对称删列，无反向数据重建（两列均为本次新增，无历史数据可丢）。

**链位置**：接在 045（全局角色字典）之后，保证全图单一 head、线性无分叉。

Revision ID: pg_standalone_046_po_spare_fields
Revises: pg_standalone_045_global_role
Create Date: 2026-09-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_046_po_spare_fields'
down_revision = 'pg_standalone_045_global_role'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增备品数量 / 损耗率快照两列（幂等，可空无默认）。

    DDL 以 ``sa.text`` 包裹原生 SQL：``ADD COLUMN IF NOT EXISTS`` 提供幂等性
    （alembic 的 ``op.add_column`` 无 if_not_exists 能力），同时保证
    ``sqlalchemy`` 的使用真实可追溯（避免未使用导入）。
    """
    op.execute(sa.text(
        'ALTER TABLE purchase_order ADD COLUMN IF NOT EXISTS spare_quantity NUMERIC(12,2)'
    ))
    op.execute(sa.text(
        'ALTER TABLE purchase_order ADD COLUMN IF NOT EXISTS spare_rate NUMERIC(8,2)'
    ))
    op.execute(sa.text(
        "COMMENT ON COLUMN purchase_order.spare_quantity IS "
        "'备品数量=ceil(订单数量×损耗率‰)，随下单/保存写入'"
    ))
    op.execute(sa.text(
        "COMMENT ON COLUMN purchase_order.spare_rate IS "
        "'损耗率快照(千分之几)，用于追溯备品按多少损耗率算出'"
    ))


def downgrade() -> None:
    """对称删除两列（结构回滚，不反向重建数据）。"""
    op.execute(sa.text('ALTER TABLE purchase_order DROP COLUMN IF EXISTS spare_quantity'))
    op.execute(sa.text('ALTER TABLE purchase_order DROP COLUMN IF EXISTS spare_rate'))
