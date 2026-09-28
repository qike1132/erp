"""add order_type and country to stock_in table

Revision ID: add_order_type_country_stockin
Revises: add_batch_no_to_order
Create Date: 2026-05-07
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'add_order_type_country_stockin'
down_revision = 'add_batch_no_to_order'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.add_column('stock_in', sa.Column('order_type', sa.String(20), nullable=False, server_default='regular', comment='订单类型：regular=常规订单, custom=定制订单'))
    op.add_column('stock_in', sa.Column('country', sa.String(100), nullable=True, comment='国家名称（仅定制订单使用）'))


def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_column('stock_in', 'country')
    op.drop_column('stock_in', 'order_type')
