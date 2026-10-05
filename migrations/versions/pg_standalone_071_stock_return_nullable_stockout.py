"""stock_return.stockout_id 改为可空 —— 退货录入改为「按产品」制（P1 录入逻辑变更）

背景
----
2026-10-05 业务决定：退货单录入不再选择出货单/订单，直接**选产品 + 数量**退货
（退货是收回货物入库的物理事件，不必追溯出自哪张出货单）。stockout_id 从
必填改为可空，仅保留两类用途：

1. 历史数据（P0/P1 早期经出货行发起、带出货关联的退货单）的可追溯性；
2. cancel 的对称回冲分支：带 stockout_id 的旧记录取消时，需同步回减
   stock_out.returned_quantity（新录入的按产品退货无此关联，无需回减）。

order_id 本就可空（SET NULL），不受影响；新录入的退货 stockout_id/order_id
均为 NULL，订单状态不因产品制退货而变化（业务明确接受）。

幂等性：重复执行安全（DROP NOT NULL 幂等）。

Revision ID: pg_standalone_071_stock_return_nullable_stockout
Revises: pg_standalone_070_stock_return_status
Create Date: 2026-10-05
"""
from alembic import op

revision = 'pg_standalone_071_stock_return_nullable_stockout'
down_revision = 'pg_standalone_070_stock_return_status'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE stock_return ALTER COLUMN stockout_id DROP NOT NULL")


def downgrade() -> None:
    # 第三轮评审 Y1：物理删除按产品制退货行会抹掉业务记录（库存已回补、流水仍在但单据
    # 消失）。回退到"必填"需先人工归档/处置这些行——显式中止而非静默删除。
    raise RuntimeError(
        '071 downgrade 会物理删除 stockout_id IS NULL 的按产品制退货记录，'
        '需先人工归档后手工执行：DELETE FROM stock_return WHERE stockout_id IS NULL; '
        '再 ALTER TABLE stock_return ALTER COLUMN stockout_id SET NOT NULL'
    )
