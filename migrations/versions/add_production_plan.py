"""添加排产计划表和操作日志表

Revision ID: add_production_plan
Revises:
Create Date: 2026-04-14
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

# revision identifiers, used by Alembic.
revision = 'add_production_plan'
down_revision = 'add_supplier_purchase_order'
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    # 排产计划主表
    op.create_table(
        'production_plan',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('customer_name', sa.String(100), nullable=False, index=True, comment='客户名称'),
        sa.Column('product_name', sa.String(100), nullable=False, comment='客户产品名称'),
        sa.Column('barcode', sa.String(50), nullable=False, index=True, comment='69码'),
        sa.Column('quantity', sa.Integer(), nullable=False, comment='排产计划数量'),
        sa.Column('plan_date', sa.Date(), nullable=False, comment='计划日期'),
        sa.Column('status', sa.String(20), server_default='pending', comment='状态: pending/confirmed/completed'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('create_time', sa.DateTime(), server_default=sa.func.now(), comment='创建时间'),
        sa.Column('update_time', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), comment='更新时间'),
        sa.Column('created_by', sa.String(50), nullable=True, comment='创建人'),
    )

    # 创建索引
    create_index_if_columns_exist('idx_pp_barcode', 'production_plan', ['barcode'])
    create_index_if_columns_exist('idx_pp_customer_name', 'production_plan', ['customer_name'])
    create_index_if_columns_exist('idx_pp_plan_date', 'production_plan', ['plan_date'])
    create_index_if_columns_exist('idx_pp_plan_month', 'production_plan', ['plan_date', 'customer_name'])

    # 排产计划操作日志表
    op.create_table(
        'production_plan_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(), nullable=False, index=True, comment='排产计划ID'),
        sa.Column('action', sa.String(20), nullable=False, comment='操作类型: create/update/delete'),
        sa.Column('old_value', sa.Text(), nullable=True, comment='变更前数据(JSON)'),
        sa.Column('new_value', sa.Text(), nullable=True, comment='变更后数据(JSON)'),
        sa.Column('operator', sa.String(50), nullable=False, comment='操作人'),
        sa.Column('operate_time', sa.DateTime(), server_default=sa.func.now(), comment='操作时间'),
    )

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_table('production_plan_log')
    op.drop_table('production_plan')
