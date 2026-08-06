"""create pattern_room module tables

Revision ID: pg_standalone_015_pattern_room
Revises: pg_standalone_014_create_order_item
Create Date: 2026-07-18

新增板房模块 4 张表：
- pattern_room_bom              打样 BOM 主表
- pattern_room_bom_item         BOM 节点表（多级树）
- pattern_room_bom_item_version 物料版本快照表
- pattern_room_change_log       变更日志表

BOM 编号格式: BF-YYYYMMDD-XXXX（4 位序号，连字符分隔），由 services/numbering.py 生成。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'pg_standalone_015_pattern_room'
down_revision = 'pg_standalone_014_create_order_item'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 打样 BOM 主表
    op.create_table(
        'pattern_room_bom',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bom_no', sa.String(32), nullable=False, comment='打样编号 BF-YYYYMMDD-XXXX'),
        sa.Column('product_name', sa.String(200), nullable=False, comment='产品名称'),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customer.id'), comment='客户ID'),
        sa.Column('customer_name', sa.String(200), comment='客户名称(冗余)'),
        sa.Column('current_version', sa.String(8), nullable=False, server_default='T1', comment='当前版本 T1/T2/T3...'),
        sa.Column('status', sa.String(16), nullable=False, server_default='draft', comment='状态: draft/sampling/confirmed/archived'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), comment='创建人ID'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='更新时间'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='0', comment='乐观锁版本号'),
        sa.UniqueConstraint('bom_no', name='uq_pattern_room_bom_no'),
    )
    op.create_index('idx_prb_customer', 'pattern_room_bom', ['customer_id'])
    op.create_index('idx_prb_status_version', 'pattern_room_bom', ['status', 'current_version'])
    op.create_index('idx_prb_created_at', 'pattern_room_bom', [sa.text('created_at DESC')])
    op.create_index('idx_prb_product_name', 'pattern_room_bom', ['product_name'])

    # 2. BOM 节点表（多级树，自引用 parent_id）
    op.create_table(
        'pattern_room_bom_item',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('pattern_room_bom.id', ondelete='CASCADE'), nullable=False),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('pattern_room_bom_item.id', ondelete='CASCADE'), comment='父节点ID'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序'),
        sa.Column('material_name', sa.String(200), nullable=False, comment='物料名称'),
        sa.Column('category', sa.String(16), nullable=False, comment='类别: fabric/filling/accessory/packaging'),
        sa.Column('quantity', sa.Numeric(12, 3), nullable=False, server_default='1', comment='用量'),
        sa.Column('unit', sa.String(16), nullable=False, server_default='个', comment='单位'),
        sa.Column('spec', sa.String(200), comment='规格'),
        sa.Column('current_supplier_id', sa.Integer(), sa.ForeignKey('supplier.id'), comment='当前供应商ID'),
        sa.Column('current_supplier_name', sa.String(200), comment='当前供应商名称(冗余)'),
        sa.Column('current_version', sa.String(8), nullable=False, server_default='T1', comment='当前版本'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_prbi_bom_parent', 'pattern_room_bom_item', ['bom_id', 'parent_id', 'sort_order'])
    op.create_index('idx_prbi_category', 'pattern_room_bom_item', ['category'])
    op.create_index('idx_prbi_supplier', 'pattern_room_bom_item', ['current_supplier_id'])

    # 3. 物料版本快照表
    op.create_table(
        'pattern_room_bom_item_version',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bom_item_id', sa.Integer(), sa.ForeignKey('pattern_room_bom_item.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.String(8), nullable=False, comment='版本号 T1/T2/T3...'),
        sa.Column('supplier_id', sa.Integer(), sa.ForeignKey('supplier.id')),
        sa.Column('supplier_name', sa.String(200), comment='供应商名称'),
        sa.Column('material_spec', sa.String(200), comment='物料规格'),
        sa.Column('unit_price', sa.Numeric(12, 2), comment='单价'),
        sa.Column('contact_person', sa.String(100), comment='联系人'),
        sa.Column('contact_phone', sa.String(50), comment='联系电话'),
        sa.Column('delivery_days', sa.Integer(), comment='交期(天)'),
        sa.Column('remark', sa.Text(), comment='备注'),
        sa.Column('snapshot_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'), comment='快照时间'),
        sa.UniqueConstraint('bom_item_id', 'version', name='uq_prbiv_item_version'),
    )
    op.create_index('idx_prbiv_bom_item_version', 'pattern_room_bom_item_version', ['bom_item_id', 'version'])
    op.create_index('idx_prbiv_version', 'pattern_room_bom_item_version', ['version'])

    # 4. 变更日志表
    op.create_table(
        'pattern_room_change_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bom_id', sa.Integer(), sa.ForeignKey('pattern_room_bom.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bom_item_id', sa.Integer(), sa.ForeignKey('pattern_room_bom_item.id', ondelete='SET NULL'), comment='关联节点ID'),
        sa.Column('change_type', sa.String(16), nullable=False, comment='变更类型'),
        sa.Column('from_version', sa.String(8), comment='原版本'),
        sa.Column('to_version', sa.String(8), comment='新版本'),
        sa.Column('change_reason', sa.Text(), nullable=False, comment='变更原因'),
        sa.Column('change_details', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb"), comment='字段级 diff'),
        sa.Column('operator_id', sa.Integer(), sa.ForeignKey('user.id'), comment='操作人ID'),
        sa.Column('operator_name', sa.String(100), comment='操作人姓名(冗余)'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('idx_prcl_bom_time', 'pattern_room_change_log', ['bom_id', sa.text('created_at DESC')])
    op.create_index('idx_prcl_type', 'pattern_room_change_log', ['change_type'])
    op.create_index('idx_prcl_created_at', 'pattern_room_change_log', [sa.text('created_at DESC')])


def downgrade():
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
