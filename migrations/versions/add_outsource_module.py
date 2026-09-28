"""湖北外发模块：SKU 工序预设表 + 订单外发工序表

Revision ID: add_outsource_module
Revises: partition_order_by_year, pg_standalone_025_add_cs_indexes
Create Date: 2026-08-11

以合并迁移（双 down_revision）收拢两条既有迁移分支
（partition_order_by_year / pg_standalone_025_add_cs_indexes），
使其成为唯一新 head，并创建外发模块两张业务表。
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    create_index_if_columns_exist,
)

# revision identifiers, used by Alembic.
revision = 'add_outsource_module'
down_revision = ('partition_order_by_year', 'pg_standalone_025_add_cs_indexes')
branch_labels = None
depends_on = None

def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    # SKU 外发工序预设：按产品固定配置外发工序类型（电绣/转印/配件等）
    op.create_table(
        'outsource_process_type',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id'), nullable=False, comment='产品(SKU)ID'),
        sa.Column('process_type', sa.String(50), nullable=False, comment='工序类型：电绣/转印/配件等'),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='工序顺序，数值越小越靠前'),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='是否启用'),
        sa.Column('remark', sa.String(200), nullable=True, comment='备注'),
        sa.Column('created_by', sa.String(50), nullable=True, comment='创建人'),
        sa.Column('create_time', sa.DateTime(timezone=True), server_default=sa.func.now(), comment='创建时间'),
        sa.Column('update_time', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), comment='更新时间'),
        sa.UniqueConstraint('product_id', 'process_type', name='uq_outsource_pt_product_process'),
    )
    create_index_if_columns_exist('ix_outsource_pt_product', 'outsource_process_type', ['product_id'])
    create_index_if_columns_exist('ix_outsource_pt_product_sort', 'outsource_process_type', ['product_id', 'sort_order'])

    # 订单外发工序实例：订单下每个 SKU 需经历的外发工序，含计划/实际完成时间与状态
    op.create_table(
        'order_outsource_process',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id', ondelete='CASCADE'), nullable=False, comment='主订单ID'),
        sa.Column('order_item_id', sa.Integer(), sa.ForeignKey('order_item.id', ondelete='CASCADE'), nullable=True, comment='订单明细ID（SKU 粒度）'),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id'), nullable=False, comment='产品(SKU)ID'),
        sa.Column('product_name', sa.String(200), nullable=True, comment='冗余产品名称'),
        sa.Column('process_type', sa.String(50), nullable=False, comment='工序类型：电绣/转印/配件等'),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False, comment='工序顺序'),
        sa.Column('status', sa.String(20), server_default='pending', nullable=False, comment='状态：pending/in_progress/completed'),
        sa.Column('planned_start_time', sa.DateTime(timezone=True), nullable=True, comment='计划开始时间'),
        sa.Column('planned_end_time', sa.DateTime(timezone=True), nullable=True, comment='计划完成时间'),
        sa.Column('actual_start_time', sa.DateTime(timezone=True), nullable=True, comment='实际开始时间'),
        sa.Column('actual_end_time', sa.DateTime(timezone=True), nullable=True, comment='实际完成时间'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('created_by', sa.String(50), nullable=True, comment='创建人'),
        sa.Column('create_time', sa.DateTime(timezone=True), server_default=sa.func.now(), comment='创建时间'),
        sa.Column('update_time', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), comment='更新时间'),
    )
    create_index_if_columns_exist('ix_oosp_order', 'order_outsource_process', ['order_id'])
    create_index_if_columns_exist('ix_oosp_order_sort', 'order_outsource_process', ['order_id', 'sort_order'])
    create_index_if_columns_exist('ix_oosp_item', 'order_outsource_process', ['order_item_id'])
    create_index_if_columns_exist('ix_oosp_product', 'order_outsource_process', ['product_id'])
    create_index_if_columns_exist('ix_oosp_status_date', 'order_outsource_process', ['status', 'create_time'])

def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    op.drop_table('order_outsource_process')
    op.drop_table('outsource_process_type')
