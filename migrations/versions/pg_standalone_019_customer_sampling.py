"""create customer_sampling module tables

Revision ID: pg_standalone_019_customer_sampling
Revises: pg_standalone_017_pattern_room_v2, rebuild_po_dedup_use_supplier_name, add_product_factory
Create Date: 2026-08-08

新增按客户分类打样信息模块 4 张表：
- customer_sampling_project        打样项目主表（序列号/产品名/图片/客户/当前版本/乐观锁）
- customer_sampling_part           部位表（当前版本工作布料数据，含排序值）
- customer_sampling_fabric_version 版本快照表（不可变，JSONB 存完整快照 + 预计算 diff）
- customer_sampling_change_log     变更日志表（操作人/操作时间/变更内容审计）

序列号格式: CS-YYYYMMDD-XXXX（4 位序号，连字符分隔），由 services/numbering.py 生成。
权限码: customer_sampling_manage（替换旧 pattern_room_manage，权限码迁移留待 T14）。

本迁移仅创建新表与索引，不删除旧 pattern_room 表（遵循"旧代码清理最后"原则，留待 T14）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# 合并当前 3 个 head 为单一线性历史
revision = 'pg_standalone_019_customer_sampling'
down_revision = (
    'pg_standalone_017_pattern_room_v2',
    'rebuild_po_dedup_use_supplier_name',
    'add_product_factory',
)
branch_labels = None
depends_on = None


def upgrade():
    # 确保 pg_trgm 扩展存在（用于产品名 ILIKE 模糊搜索 GIN 索引）
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')

    # 1. 打样项目主表
    op.create_table(
        'customer_sampling_project',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('sequence_no', sa.String(32), nullable=False, comment='序列号 CS-YYYYMMDD-XXXX'),
        sa.Column('product_name', sa.String(200), nullable=False, comment='产品名称'),
        sa.Column('product_image_file_id', sa.Integer(), sa.ForeignKey('file_records.id', ondelete='SET NULL'), comment='产品图片文件ID'),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id', ondelete='SET NULL'), comment='关联客户ID'),
        sa.Column('customer_name', sa.String(200), comment='客户名称(冗余)'),
        sa.Column('current_version', sa.String(8), nullable=False, server_default='T1', comment='当前版本号 T1/T2/T3...'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), comment='创建人ID'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='更新时间'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0', comment='乐观锁版本号'),
        sa.UniqueConstraint('sequence_no', name='uq_csp_sequence_no'),
    )
    op.create_index('idx_csp_customer', 'customer_sampling_project', ['customer_id'])
    op.create_index('idx_csp_sequence_no', 'customer_sampling_project', ['sequence_no'])
    # GIN trigram 索引：使 ILIKE '%keyword%' 走索引
    op.create_index(
        'idx_csp_product_name_trgm', 'customer_sampling_project', ['product_name'],
        postgresql_using='gin', postgresql_ops={'product_name': 'gin_trgm_ops'},
    )
    op.create_index('idx_csp_updated_at_desc', 'customer_sampling_project', [sa.text('updated_at DESC')])
    op.create_index('idx_csp_created_at', 'customer_sampling_project', ['created_at'])

    # 2. 部位表
    op.create_table(
        'customer_sampling_part',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('customer_sampling_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('part_name', sa.String(100), nullable=False, comment='部位名称'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序值'),
        sa.Column('fabric_name', sa.String(200), comment='布料名称'),
        sa.Column('fabric_spec', sa.String(200), comment='布料规格'),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('supplier.id', ondelete='SET NULL'), comment='供应商ID'),
        sa.Column('supplier_name', sa.String(200), comment='供应商名称(冗余)'),
        sa.Column('contact_person', sa.String(100), comment='联系人'),
        sa.Column('contact_phone', sa.String(50), comment='联系电话'),
        sa.Column('unit_price', sa.Numeric(12, 2), comment='单价'),
        sa.Column('delivery_days', sa.Integer(), comment='交期(天)'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0', comment='乐观锁版本号'),
        # 同项目下部位名称唯一
        sa.UniqueConstraint('project_id', 'part_name', name='uq_csp_part_name'),
        # 单价非负、交期非负
        sa.CheckConstraint('unit_price IS NULL OR unit_price >= 0', name='ck_csp_part_unit_price_nonneg'),
        sa.CheckConstraint('delivery_days IS NULL OR delivery_days >= 0', name='ck_csp_part_delivery_days_nonneg'),
    )
    op.create_index('idx_csp_part_sort', 'customer_sampling_part', ['project_id', 'sort_order'])

    # 3. 版本快照表（不可变）
    op.create_table(
        'customer_sampling_fabric_version',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('customer_sampling_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version_no', sa.String(8), nullable=False, comment='版本号 T1/T2/T3...'),
        sa.Column('snapshot_data', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='完整部位布料快照数组'),
        sa.Column('change_summary', postgresql.JSONB(astext_type=sa.Text()), comment='相对前一版本 diff（T1 为 null）'),
        sa.Column('reason', sa.String(500), comment='变更原因'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), comment='创建人ID'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='变更时间'),
        # 同项目版本号唯一
        sa.UniqueConstraint('project_id', 'version_no', name='uq_csfv_project_version'),
    )
    op.create_index('idx_csfv_created_at', 'customer_sampling_fabric_version', [sa.text('created_at DESC')])

    # 4. 变更日志表
    op.create_table(
        'customer_sampling_change_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('customer_sampling_project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_version', sa.String(8), comment='目标版本号'),
        sa.Column('action', sa.String(32), nullable=False, comment='操作类型'),
        sa.Column('change_type', sa.String(16), comment='变更类型 add/modify/delete'),
        sa.Column('part_name', sa.String(100), comment='变更部位'),
        sa.Column('field_diffs', postgresql.JSONB(astext_type=sa.Text()), comment='字段级差异'),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('user.id'), comment='操作人ID'),
        sa.Column('operator_name', sa.String(100), comment='操作人姓名(冗余)'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='操作时间'),
    )
    op.create_index('idx_cscl_project_time', 'customer_sampling_change_log', ['project_id', sa.text('created_at DESC')])
    op.create_index('idx_cscl_action', 'customer_sampling_change_log', ['action'])


def downgrade():
    # 4. 变更日志表
    op.drop_index('idx_cscl_action', table_name='customer_sampling_change_log')
    op.drop_index('idx_cscl_project_time', table_name='customer_sampling_change_log')
    op.drop_table('customer_sampling_change_log')

    # 3. 版本快照表
    op.drop_index('idx_csfv_created_at', table_name='customer_sampling_fabric_version')
    op.drop_table('customer_sampling_fabric_version')

    # 2. 部位表
    op.drop_index('idx_csp_part_sort', table_name='customer_sampling_part')
    op.drop_table('customer_sampling_part')

    # 1. 打样项目主表
    op.drop_index('idx_csp_created_at', table_name='customer_sampling_project')
    op.drop_index('idx_csp_updated_at_desc', table_name='customer_sampling_project')
    op.drop_index('idx_csp_product_name_trgm', table_name='customer_sampling_project')
    op.drop_index('idx_csp_sequence_no', table_name='customer_sampling_project')
    op.drop_index('idx_csp_customer', table_name='customer_sampling_project')
    op.drop_table('customer_sampling_project')