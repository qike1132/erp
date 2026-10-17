"""成品库存页备注表 finished_stock_remark（一行 = 一个 (客户,产品,批次) 聚合行）

页面级自由文本备注，独立于包装录入的 remark。键与聚合口径一致：
(customer_name, product_id, batch_no)，batch_no 空串 = 未分批次行。
纯新增表，不夹带业务逻辑，不改既有数据。

Revision ID: pg_standalone_099_finished_stock_remark
Revises: pg_standalone_098_finished_stock_batch
"""
import sqlalchemy as sa

from migrations._legacy_base_guard import create_index_if_absent, create_table_if_absent

revision = 'pg_standalone_099_finished_stock_remark'
down_revision = 'pg_standalone_098_finished_stock_batch'
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_absent(
        'finished_stock_remark',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('customer_name', sa.String(length=100), nullable=False, server_default='', comment='客户名称（与聚合行展示值一致；空=未指定客户）'),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('product.id', ondelete='CASCADE'), nullable=False, comment='产品ID'),
        sa.Column('batch_no', sa.String(length=100), nullable=False, server_default='', comment='批次号（空串=未分批次）'),
        sa.Column('remark', sa.Text(), nullable=False, server_default='', comment='备注内容'),
        sa.Column('create_time', sa.DateTime(timezone=True), server_default=sa.func.now(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(timezone=True), comment='更新时间'),
    )
    # UPSERT 落点：(客户,产品,批次) 唯一。照既有 create_index_if_absent（幂等按名判重）
    create_index_if_absent(
        'uq_fs_remark_cust_prod_batch', 'finished_stock_remark',
        ['customer_name', 'product_id', 'batch_no'], unique=True,
    )


def downgrade() -> None:
    from migrations._legacy_base_guard import drop_table_if_empty
    drop_table_if_empty('finished_stock_remark')
