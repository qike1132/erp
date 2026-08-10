"""rebuild pattern_room module for plush toy sampling management

Revision ID: pg_standalone_017_pattern_room_v2
Revises: pg_standalone_016_dashboard_daily_stats_mv
Create Date: 2026-08-07

重构板房模块，聚焦毛绒产品打样管理：
- 删除旧表：pattern_room_bom, pattern_room_bom_item, pattern_room_bom_item_version, pattern_room_change_log
- 新建表：
  - pattern_room_sample           打样主表（按客户分类、产品图片）
  - pattern_room_sample_part      打样部位表（每个部位名称）
  - pattern_room_part_fabric      部位布料版本表（T1/T2/T3 布料记录+变更时间）
  - pattern_room_change_log_v2    变更日志表

打样编号格式: YS-YYYYMMDD-XXXX
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'pg_standalone_017_pattern_room_v2'
down_revision = 'pg_standalone_016_dashboard_daily_stats_mv'
branch_labels = None
depends_on = None


def upgrade():
    # ---- 删除旧表 ----
    op.drop_index('idx_prcl_created_at', table_name='pattern_room_change_log')
    op.drop_index('idx_prcl_type', table_name='pattern_room_change_log')
    op.drop_index('idx_prcl_bom_time', table_name='pattern_room_change_log')
    op.drop_table('pattern_room_change_log')

    op.drop_index('idx_prbiv_version', table_name='pattern_room_bom_item_version')
    op.drop_index('idx_prbiv_bom_item_version', table_name='pattern_room_bom_item_version')
    op.drop_table('pattern_room_bom_item_version')

    op.drop_index('idx_prbi_supplier', table_name='pattern_room_bom_item')
    op.drop_index('idx_prbi_category', table_name='pattern_room_bom_item')
    op.drop_index('idx_prbi_bom_parent', table_name='pattern_room_bom_item')
    op.drop_table('pattern_room_bom_item')

    op.drop_index('idx_prb_product_name', table_name='pattern_room_bom')
    op.drop_index('idx_prb_created_at', table_name='pattern_room_bom')
    op.drop_index('idx_prb_status_version', table_name='pattern_room_bom')
    op.drop_index('idx_prb_customer', table_name='pattern_room_bom')
    op.drop_table('pattern_room_bom')

    # ---- 1. 打样主表 ----
    op.create_table(
        'pattern_room_sample',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sample_no', sa.String(32), nullable=False, comment='打样编号 YS-YYYYMMDD-XXXX'),
        sa.Column('product_name', sa.String(200), nullable=False, comment='产品名称'),
        sa.Column('product_image', sa.Text(), comment='产品图片URL'),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id'), comment='客户ID'),
        sa.Column('customer_name', sa.String(200), comment='客户名称(冗余)'),
        sa.Column('current_version', sa.String(8), nullable=False, server_default='T1', comment='当前版本 T1/T2/T3'),
        sa.Column('status', sa.String(16), nullable=False, server_default='sampling', comment='状态: sampling/confirmed/archived'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), comment='创建人ID'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='更新时间'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0', comment='乐观锁'),
        sa.UniqueConstraint('sample_no', name='uq_prs_sample_no'),
    )
    op.create_index('idx_prs_customer', 'pattern_room_sample', ['customer_id'])
    op.create_index('idx_prs_created_at', 'pattern_room_sample', [sa.text('created_at DESC')])
    op.create_index('idx_prs_status', 'pattern_room_sample', ['status'])

    # ---- 2. 打样部位表 ----
    op.create_table(
        'pattern_room_sample_part',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sample_id', sa.Integer(), sa.ForeignKey('pattern_room_sample.id', ondelete='CASCADE'), nullable=False),
        sa.Column('part_name', sa.String(100), nullable=False, comment='部位名称（头部/身体/手臂/腿部/尾巴等）'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_prsp_sample_sort', 'pattern_room_sample_part', ['sample_id', 'sort_order'])

    # ---- 3. 部位布料版本表 ----
    op.create_table(
        'pattern_room_part_fabric',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sample_part_id', sa.Integer(), sa.ForeignKey('pattern_room_sample_part.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(8), nullable=False, comment='版本号 T1/T2/T3'),
        sa.Column('fabric_name', sa.String(200), nullable=False, comment='布料名称'),
        sa.Column('fabric_spec', sa.String(500), comment='布料规格/颜色/成分'),
        sa.Column('fabric_image', sa.Text(), comment='布料图片URL'),
        sa.Column('supplier_name', sa.String(200), comment='供应商名称'),
        sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='变更时间'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.UniqueConstraint('sample_part_id', 'version', name='uq_prpf_part_version'),
    )
    op.create_index('idx_prpf_part_version', 'pattern_room_part_fabric', ['sample_part_id', 'version'])
    op.create_index('idx_prpf_version', 'pattern_room_part_fabric', ['version'])

    # ---- 4. 变更日志表 ----
    op.create_table(
        'pattern_room_change_log_v2',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sample_id', sa.Integer(), sa.ForeignKey('pattern_room_sample.id', ondelete='CASCADE'), nullable=False),
        sa.Column('change_type', sa.String(20), nullable=False, comment='变更类型: create/version_upgrade/fabric_change/status_change'),
        sa.Column('from_version', sa.String(8), comment='原版本'),
        sa.Column('to_version', sa.String(8), comment='新版本'),
        sa.Column('change_reason', sa.Text(), nullable=False, comment='变更原因'),
        sa.Column('change_details', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb"), comment='字段级 diff'),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('user.id'), comment='操作人ID'),
        sa.Column('operator_name', sa.String(100), comment='操作人姓名'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_prcl2_sample_time', 'pattern_room_change_log_v2', ['sample_id', sa.text('created_at DESC')])
    op.create_index('idx_prcl2_type', 'pattern_room_change_log_v2', ['change_type'])


def downgrade():
    # ---- 删除新表 ----
    op.drop_index('idx_prcl2_type', table_name='pattern_room_change_log_v2')
    op.drop_index('idx_prcl2_sample_time', table_name='pattern_room_change_log_v2')
    op.drop_table('pattern_room_change_log_v2')

    op.drop_index('idx_prpf_version', table_name='pattern_room_part_fabric')
    op.drop_index('idx_prpf_part_version', table_name='pattern_room_part_fabric')
    op.drop_table('pattern_room_part_fabric')

    op.drop_index('idx_prsp_sample_sort', table_name='pattern_room_sample_part')
    op.drop_table('pattern_room_sample_part')

    op.drop_index('idx_prs_status', table_name='pattern_room_sample')
    op.drop_index('idx_prs_created_at', table_name='pattern_room_sample')
    op.drop_index('idx_prs_customer', table_name='pattern_room_sample')
    op.drop_table('pattern_room_sample')

    # ---- 重建旧表（省略，通常不需要在 downgrade 中重建） ----
