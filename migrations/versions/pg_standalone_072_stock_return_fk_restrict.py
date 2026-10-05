"""stock_return.stockout_id 外键 CASCADE -> RESTRICT —— 防止历史退货单被级联物理删除

背景（第三轮评审 R2）
--------------------
stock_return.stockout_id 的外键在 DB 层为 ON DELETE CASCADE（迁移 030 落地）。
两条可触达路径会级联物理删掉退货单，与 P1-①「取消而非删除、记录保留可追溯」冲突：

1. 历史退货取消后 stock_out.returned_quantity 回减（可归零），delete_stockout 的
   应用层守卫「returned_quantity > 0 禁删」放行 → 删出货级联删掉已取消的历史退货单；
2. 删订单级联删 stock_out（stock_out.order_id CASCADE），同样波及关联退货单。

本迁移把该外键改为 ON DELETE RESTRICT：只要存在关联退货单（无论状态），出货行
禁止删除；配套在 delete_stockout_core 增加应用层前置校验（返回 400 而非 DB 层 500）。

幂等性：DROP IF EXISTS，重复执行安全。
注：SQL 全部内联字面量直书（Mimosa 写入门禁要求，勿提取为模块常量）。

Revision ID: pg_standalone_072_stock_return_fk_restrict
Revises: pg_standalone_071_stock_return_nullable_stockout
Create Date: 2026-10-05
"""
from alembic import op

revision = 'pg_standalone_072_stock_return_fk_restrict'
down_revision = 'pg_standalone_071_stock_return_nullable_stockout'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE stock_return DROP CONSTRAINT IF EXISTS stock_return_stockout_id_fkey')
    op.execute(
        'ALTER TABLE stock_return ADD CONSTRAINT stock_return_stockout_id_fkey '
        'FOREIGN KEY (stockout_id) REFERENCES stock_out(id) ON DELETE RESTRICT'
    )


def downgrade() -> None:
    op.execute('ALTER TABLE stock_return DROP CONSTRAINT IF EXISTS stock_return_stockout_id_fkey')
    op.execute(
        'ALTER TABLE stock_return ADD CONSTRAINT stock_return_stockout_id_fkey '
        'FOREIGN KEY (stockout_id) REFERENCES stock_out(id) ON DELETE CASCADE'
    )
