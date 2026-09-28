"""外发工序：发货数量/收货数量字段 + 状态语义迁移为 待发货/已发货/已收货

Revision ID: add_outsource_ship_receive
Revises: add_stockin_confirm_fields
Create Date: 2026-08-20

外发工序进度逻辑由「开始/完成」改为「发货→确认收货」：
- 新增 shipped_quantity（发货数量，每道工序独立）
- 新增 received_quantity（收货数量，确认收货时默认等于发货数量）
- 存量状态迁移：in_progress → shipped（已发货）、completed → received（已收货）
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

# revision identifiers, used by Alembic.
revision = 'add_outsource_ship_receive'
down_revision = 'add_stockin_confirm_fields'
branch_labels = None
depends_on = None


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.add_column(
        'order_outsource_process',
        sa.Column('shipped_quantity', sa.Integer(), nullable=True, comment='发货数量（发货时录入，每道工序独立）'),
    )
    op.add_column(
        'order_outsource_process',
        sa.Column('received_quantity', sa.Integer(), nullable=True, comment='收货数量（确认收货时默认等于发货数量）'),
    )
    # 存量状态语义迁移：in_progress→shipped（已发货）、completed→received（已收货）
    op.execute(sa.text("UPDATE order_outsource_process SET status='shipped' WHERE status='in_progress'"))
    op.execute(sa.text("UPDATE order_outsource_process SET status='received' WHERE status='completed'"))


def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.execute(sa.text("UPDATE order_outsource_process SET status='in_progress' WHERE status='shipped'"))
    op.execute(sa.text("UPDATE order_outsource_process SET status='completed' WHERE status='received'"))
    op.drop_column('order_outsource_process', 'received_quantity')
    op.drop_column('order_outsource_process', 'shipped_quantity')
