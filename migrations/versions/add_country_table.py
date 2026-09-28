"""添加国家表

Revision ID: add_country_table
Revises: add_device_token
Create Date: 2026-06-04
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import base_schema_absent

revision = 'add_country_table'
down_revision = 'add_device_token'
branch_labels = None
depends_on = None


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.create_table(
        'country',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), unique=True, nullable=False, comment='国家名称'),
    )


def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_table('country')
