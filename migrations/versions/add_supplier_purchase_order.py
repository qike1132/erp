"""添加供应商和采购订单表

Revision ID: add_supplier_purchase_order
Revises: 9b7b1ead6c4a
Create Date: 2026-04-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_supplier_purchase_order'
down_revision = 'add_product_version'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('supplier',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('contact_person', sa.String(length=50), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('address', sa.String(length=200), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.Column('update_time', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index('idx_supplier_name', 'supplier', ['name'], unique=True)

    op.create_table('purchase_order',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_no', sa.String(length=30), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.Column('supplier_name', sa.String(length=100), nullable=True),
        sa.Column('order_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.Column('update_time', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_no')
    )
    op.create_index('idx_purchase_order_no', 'purchase_order', ['order_no'], unique=True)

    op.create_table('purchase_order_item',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('material_code', sa.String(length=50), nullable=True),
        sa.Column('material_name', sa.String(length=100), nullable=False),
        sa.Column('specification', sa.String(length=100), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('formal_quantity', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('spare_quantity', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('loss_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('unit_usage', sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column('material_category', sa.String(length=20), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['purchase_order.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('product_fabric',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('material_code', sa.String(length=50), nullable=True),
        sa.Column('fabric_name', sa.String(length=100), nullable=False),
        sa.Column('specification', sa.String(length=100), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.Column('supplier_name', sa.String(length=100), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('loss_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.Column('update_time', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('product_packaging',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('material_code', sa.String(length=50), nullable=True),
        sa.Column('packaging_name', sa.String(length=100), nullable=False),
        sa.Column('specification', sa.String(length=100), nullable=True),
        sa.Column('quantity', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('supplier_id', sa.Integer(), nullable=True),
        sa.Column('supplier_name', sa.String(length=100), nullable=True),
        sa.Column('unit', sa.String(length=20), nullable=True),
        sa.Column('loss_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('remark', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=True),
        sa.Column('update_time', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ),
        sa.ForeignKeyConstraint(['supplier_id'], ['supplier.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    try:
        op.add_column('product_material', sa.Column('material_code', sa.String(length=50), nullable=True))
        op.add_column('product_material', sa.Column('specification', sa.String(length=100), nullable=True))
        op.add_column('product_material', sa.Column('supplier_id', sa.Integer(), nullable=True))
        op.add_column('product_material', sa.Column('supplier_name', sa.String(length=100), nullable=True))
        op.add_column('product_material', sa.Column('unit', sa.String(length=20), nullable=True))
        op.add_column('product_material', sa.Column('loss_rate', sa.Numeric(precision=5, scale=2), nullable=True))
        op.add_column('product_material', sa.Column('remark', sa.Text(), nullable=True))
        op.add_column('product_material', sa.Column('update_time', sa.DateTime(), nullable=True))
        op.create_foreign_key('fk_product_material_supplier', 'product_material', 'supplier', ['supplier_id'], ['id'])
    except Exception:
        pass

    try:
        op.add_column('product_accessory', sa.Column('material_code', sa.String(length=50), nullable=True))
        op.add_column('product_accessory', sa.Column('specification', sa.String(length=100), nullable=True))
        op.add_column('product_accessory', sa.Column('supplier_id', sa.Integer(), nullable=True))
        op.add_column('product_accessory', sa.Column('supplier_name', sa.String(length=100), nullable=True))
        op.add_column('product_accessory', sa.Column('unit', sa.String(length=20), nullable=True))
        op.add_column('product_accessory', sa.Column('loss_rate', sa.Numeric(precision=5, scale=2), nullable=True))
        op.add_column('product_accessory', sa.Column('material_category', sa.String(length=20), nullable=True))
        op.add_column('product_accessory', sa.Column('remark', sa.Text(), nullable=True))
        op.add_column('product_accessory', sa.Column('update_time', sa.DateTime(), nullable=True))
        op.create_foreign_key('fk_product_accessory_supplier', 'product_accessory', 'supplier', ['supplier_id'], ['id'])
    except Exception:
        pass


def downgrade():
    op.drop_table('purchase_order_item')
    op.drop_table('purchase_order')
    op.drop_table('product_packaging')
    op.drop_table('product_fabric')
    op.drop_table('supplier')
    
    try:
        op.drop_column('product_material', 'remark')
        op.drop_column('product_material', 'loss_rate')
        op.drop_column('product_material', 'unit')
        op.drop_column('product_material', 'supplier_name')
        op.drop_column('product_material', 'supplier_id')
        op.drop_column('product_material', 'specification')
        op.drop_column('product_material', 'material_code')
        op.drop_column('product_material', 'update_time')
    except Exception:
        pass

    try:
        op.drop_column('product_accessory', 'remark')
        op.drop_column('product_accessory', 'material_category')
        op.drop_column('product_accessory', 'loss_rate')
        op.drop_column('product_accessory', 'unit')
        op.drop_column('product_accessory', 'supplier_name')
        op.drop_column('product_accessory', 'supplier_id')
        op.drop_column('product_accessory', 'specification')
        op.drop_column('product_accessory', 'material_code')
        op.drop_column('product_accessory', 'update_time')
    except Exception:
        pass
