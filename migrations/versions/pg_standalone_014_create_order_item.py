"""create order_item table

Revision ID: pg_standalone_014_create_order_item
Revises: rebuild_po_dedup_index
Create Date: 2026-06-26

新增 order_item 表承载 SKU 级字段，使一个主订单可包含多个 SKU。
upgrade() 内从 "order" 表回填历史数据（每个订单一条 item），JOIN product
获取冗余 name/barcode。Order 表的 SKU 字段在本 migration 中保留，删列在
后续 Task 5 完成。
"""
from alembic import op
import sqlalchemy as sa

revision = 'pg_standalone_014_create_order_item'
down_revision = 'rebuild_po_dedup_index'
branch_labels = None
depends_on = None


def upgrade():
    """创建 order_item 表并从 order 表回填历史数据。"""
    op.create_table(
        'order_item',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('order_id', sa.Integer(), sa.ForeignKey('order.id', ondelete='CASCADE'), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id'), nullable=False),
        sa.Column('product_name', sa.String(200), nullable=True),
        sa.Column('product_barcode', sa.String(100), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('order_type', sa.String(20), nullable=False, server_default='regular'),
        sa.Column('country', sa.String(100), nullable=True),
        sa.Column('deduct_stock', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deduct_quantity', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_order_item_order_id', 'order_item', ['order_id'])
    op.create_index('ix_order_item_product_id', 'order_item', ['product_id'])
    op.create_index('ix_order_item_order_product', 'order_item', ['order_id', 'product_id'])

    # 数据回填：从 "order" 表复制 SKU 字段，JOIN product 获取冗余 name/barcode
    op.execute("""
        INSERT INTO order_item (
            order_id, product_id, product_name, product_barcode,
            quantity, order_type, country, deduct_stock, deduct_quantity,
            note, created_at, updated_at
        )
        SELECT
            o.id, o.product_id, p.name, p.barcode,
            o.quantity, o.order_type, o.country,
            false AS deduct_stock, 0 AS deduct_quantity,
            o.note,
            COALESCE(o.order_date, NOW()) AS created_at,
            COALESCE(o.updated_at, COALESCE(o.order_date, NOW())) AS updated_at
        FROM "order" o
        LEFT JOIN product p ON o.product_id = p.id
    """)


def downgrade():
    op.drop_index('ix_order_item_order_product', table_name='order_item')
    op.drop_index('ix_order_item_product_id', table_name='order_item')
    op.drop_index('ix_order_item_order_id', table_name='order_item')
    op.drop_table('order_item')
