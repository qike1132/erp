"""add audit_log table

Revision ID: pg_standalone_012
Revises: None
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'pg_standalone_012'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.Index('ix_audit_log_user_id'), nullable=True),
        sa.Column('username', sa.String(50), nullable=True),
        sa.Column('action', sa.String(20), nullable=False, index=True),
        sa.Column('resource_type', sa.String(50), nullable=False, index=True),
        sa.Column('resource_id', sa.String(100), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(500), nullable=True),
        sa.Column('request_id', sa.String(36), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, index=True),
    )
    op.create_index('idx_audit_user_action', 'audit_log', ['user_id', 'action'])
    op.create_index('idx_audit_resource', 'audit_log', ['resource_type', 'resource_id'])
    op.create_index('idx_audit_action_date', 'audit_log', ['action', 'created_at'])
    op.create_index('idx_audit_resource_date', 'audit_log', ['resource_type', sa.text('created_at DESC')])
    op.create_index('idx_audit_created_desc', 'audit_log', [sa.text('created_at DESC')])
    op.execute(
        "CREATE INDEX idx_audit_not_login ON audit_log (created_at DESC) WHERE action != 'LOGIN'"
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_audit_not_login')
    op.drop_index('idx_audit_created_desc', table_name='audit_log')
    op.drop_index('idx_audit_resource_date', table_name='audit_log')
    op.drop_index('idx_audit_action_date', table_name='audit_log')
    op.drop_index('idx_audit_resource', table_name='audit_log')
    op.drop_index('idx_audit_user_action', table_name='audit_log')
    op.drop_table('audit_log')
