"""add batch_no to order table

Revision ID: add_batch_no_order
Revises:
Create Date: 2026-04-20
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

# revision identifiers
revision = 'add_batch_no_to_order'
down_revision = 'add_customer_code_to_customer'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.add_column('order', sa.Column('batch_no', sa.String(100), nullable=True, comment='批次号'))

def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_column('order', 'batch_no')
