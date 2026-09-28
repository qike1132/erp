"""湖北订单确认流程：order 表新增确认时间/确认人字段

Revision ID: add_order_confirm_fields
Revises: add_outsource_module, pg_standalone_027_drop_pattern_room
Create Date: 2026-08-12

背景：
- beile-order（湖北订单）页面新增「确认订单」流程：新订单到达后需人工确认，
  确认前显示「未确认订单」标识并提供确认按钮，确认后转为只读「已确认」标识。
- 确认状态与订单派生状态（待备货/已备货/...）正交，故新增独立字段
  confirmed_at / confirmed_by_id，不污染 order.status 的状态机推导。

数据兼容：
- 存量订单统一回填 confirmed_at = order_date，视为已确认，
  仅迁移后新建的订单（confirmed_at IS NULL）进入「未确认」待确认流程。

以合并迁移（双 down_revision）收拢当前两条既有迁移分支
（add_outsource_module / pg_standalone_027_drop_pattern_room），
使其成为唯一新 head，保持 alembic upgrade head 可线性执行。
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

# revision identifiers, used by Alembic.
revision = 'add_order_confirm_fields'
down_revision = ('add_outsource_module', 'pg_standalone_027_drop_pattern_room')
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.add_column(
        'order',
        sa.Column('confirmed_at', sa.DateTime(), nullable=True, comment='订单确认时间（湖北订单确认流程）'),
    )
    op.add_column(
        'order',
        sa.Column('confirmed_by_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True, comment='订单确认人ID'),
    )
    create_index_if_columns_exist('ix_order_confirmed_at', 'order', ['confirmed_at'])

    # 存量订单回填：视为已确认，避免历史订单全部落入「未确认订单」待办
    op.execute(
        'UPDATE "order" SET confirmed_at = order_date WHERE confirmed_at IS NULL'
    )

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_index('ix_order_confirmed_at', table_name='order', if_exists=True)
    op.drop_column('order', 'confirmed_by_id')
    op.drop_column('order', 'confirmed_at')
