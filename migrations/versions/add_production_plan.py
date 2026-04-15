"""添加排产计划表和操作日志表

Revision ID: add_production_plan
Revises:
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa


def upgrade():
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
    op.create_index('idx_pp_barcode', 'production_plan', ['barcode'])
    op.create_index('idx_pp_customer_name', 'production_plan', ['customer_name'])
    op.create_index('idx_pp_plan_date', 'production_plan', ['plan_date'])
    op.create_index('idx_pp_plan_month', 'production_plan', ['plan_date', 'customer_name'])

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
    op.drop_table('production_plan_log')
    op.drop_table('production_plan')
