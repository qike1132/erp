"""外发发货单：outsource_shipment + outsource_shipment_item

Revision ID: add_outsource_shipment
Revises: pg_standalone_047_purchase_order_sku
Create Date: 2026-09-19

一键发货工作流：一键发货生成发货单（贝乐用户端「待收货」订单），
贝乐确认收货后发货单状态 shipped → received（「已完成」）闭环。
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'add_outsource_shipment'
down_revision = 'pg_standalone_047_purchase_order_sku'
branch_labels = None
depends_on = None


def upgrade():
    # 发货单：一键发货生成的单据，同时是推送给贝乐用户端的「待收货订单」
    op.create_table(
        'outsource_shipment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('shipment_no', sa.String(24), nullable=False, comment='发货单号 FH-YYYYMMDD-XXXX'),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id', ondelete='SET NULL'), nullable=True, comment='来源订单ID'),
        sa.Column('customer', sa.String(100), nullable=True, comment='冗余客户名称'),
        sa.Column('status', sa.String(20), server_default='shipped', nullable=False, comment='状态：shipped=已发货(待收货)/received=已收货(已完成)'),
        sa.Column('shipped_at', sa.DateTime(timezone=True), nullable=True, comment='发货时间'),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True, comment='收货时间'),
        sa.Column('shipped_by', sa.String(50), nullable=True, comment='发货人'),
        sa.Column('received_by', sa.String(50), nullable=True, comment='收货人'),
        sa.Column('remark', sa.Text(), nullable=True, comment='备注'),
        sa.Column('create_time', sa.DateTime(timezone=True), server_default=sa.func.now(), comment='创建时间'),
        sa.Column('update_time', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), comment='更新时间'),
        sa.UniqueConstraint('shipment_no', name='uq_outsource_shipment_no'),
    )
    op.create_index('ix_outsource_shipment_order', 'outsource_shipment', ['order_id'])
    op.create_index('ix_outsource_shipment_status', 'outsource_shipment', ['status'])
    op.create_index('ix_outsource_shipment_status_create', 'outsource_shipment', ['status', 'create_time'])

    # 发货单明细：每道被发货的工序一行（SKU + 工序 + 数量）
    op.create_table(
        'outsource_shipment_item',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('shipment_id', sa.Integer(), sa.ForeignKey('outsource_shipment.id', ondelete='CASCADE'), nullable=False, comment='发货单ID'),
        sa.Column('process_id', sa.Integer(), sa.ForeignKey('order_outsource_process.id', ondelete='SET NULL'), nullable=True, comment='对应外发工序实例ID'),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id', ondelete='SET NULL'), nullable=True, comment='产品(SKU)ID'),
        sa.Column('product_name', sa.String(200), nullable=True, comment='冗余产品名称'),
        sa.Column('process_type', sa.String(50), nullable=False, comment='工序类型：电绣/转印/配件等'),
        sa.Column('shipped_quantity', sa.Integer(), server_default='0', nullable=False, comment='发货数量'),
        sa.Column('received_quantity', sa.Integer(), server_default='0', nullable=False, comment='收货数量'),
        sa.Column('create_time', sa.DateTime(timezone=True), server_default=sa.func.now(), comment='创建时间'),
    )
    op.create_index('ix_outsource_shipment_item_shipment', 'outsource_shipment_item', ['shipment_id'])
    op.create_index('ix_outsource_shipment_item_process', 'outsource_shipment_item', ['process_id'])


def downgrade():
    op.drop_table('outsource_shipment_item')
    op.drop_table('outsource_shipment')
