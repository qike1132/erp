"""add order batch completed fields and audit log

Revision ID: add_order_batch_fields
Revises: 659467a97350
Create Date: 2026-05-07
"""
import sqlalchemy as sa
from alembic import op

revision = 'add_order_batch_fields'
down_revision = '659467a97350'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('order', sa.Column('batch_completed_at', sa.DateTime(), nullable=True, comment='批次完成时间'))
    op.add_column('order', sa.Column('batch_completed_by_id', sa.Integer(), nullable=True, comment='批次完成操作人ID'))
    op.create_foreign_key('fk_order_batch_completed_by', 'order', 'user', ['batch_completed_by_id'], ['id'])
    op.create_index('idx_order_batch_no', 'order', ['batch_no'])
    op.create_index('idx_order_batch_completed_at', 'order', ['batch_completed_at'])

    op.create_table(
        'order_batch_audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('batch_no', sa.String(100), nullable=False, index=True, comment='批次号'),
        sa.Column('action', sa.String(50), nullable=False, index=True, comment='操作类型'),
        sa.Column('order_ids', sa.Text(), nullable=False, comment='关联订单ID列表(JSON)'),
        sa.Column('operator_id', sa.Integer(), nullable=False, comment='操作人ID'),
        sa.Column('operator_name', sa.String(100), nullable=False, comment='操作人姓名'),
        sa.Column('old_value', sa.String(100), nullable=True, comment='变更前值'),
        sa.Column('new_value', sa.String(100), nullable=True, comment='变更后值'),
        sa.Column('detail', sa.Text(), nullable=True, comment='详细信息'),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True, comment='创建时间'),
        sa.ForeignKeyConstraint(['operator_id'], ['user.id']),
    )
    op.create_index('idx_batch_audit_batch_action', 'order_batch_audit_log', ['batch_no', 'action'])
    op.create_index('idx_batch_audit_time', 'order_batch_audit_log', ['created_at'])

    op.execute("""
        INSERT INTO order_sync_config (config_key, config_value, description)
        VALUES ('order_batch_whitelist', '["MINISO国际","MINISO国内","MINISO电商","MINISO小程序"]', '订单批次号白名单客户')
        ON CONFLICT (config_key) DO NOTHING
    """)

    op.execute("""
        INSERT INTO permission (name, code, parent_id, icon, url, section, section_name, sort_order, is_nav)
        VALUES ('订单批次号', 'order_batch_manage', NULL, 'fa-layer-group', 'order_batch.index', 'core', '核心业务', 5, true)
        ON CONFLICT (code) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM permission WHERE code = 'order_batch_manage'")
    op.execute("DELETE FROM order_sync_config WHERE config_key = 'order_batch_whitelist'")
    op.drop_index('idx_batch_audit_time', table_name='order_batch_audit_log')
    op.drop_index('idx_batch_audit_batch_action', table_name='order_batch_audit_log')
    op.drop_table('order_batch_audit_log')
    op.drop_index('idx_order_batch_completed_at', table_name='order')
    op.drop_index('idx_order_batch_no', table_name='order')
    op.drop_constraint('fk_order_batch_completed_by', 'order', type_='foreignkey')
    op.drop_column('order', 'batch_completed_by_id')
    op.drop_column('order', 'batch_completed_at')
