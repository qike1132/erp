"""add audit_log table

Revision ID: pg_standalone_012
Revises: add_backup_record
Create Date: 2026-05-15
"""
import sqlalchemy as sa
from alembic import op

from migrations._legacy_base_guard import create_index_if_columns_exist

revision = 'pg_standalone_012'
down_revision = 'add_backup_record'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
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
    create_index_if_columns_exist('idx_audit_user_action', 'audit_log', ['user_id', 'action'])
    create_index_if_columns_exist('idx_audit_resource', 'audit_log', ['resource_type', 'resource_id'])
    create_index_if_columns_exist('idx_audit_action_date', 'audit_log', ['action', 'created_at'])
    create_index_if_columns_exist('idx_audit_resource_date', 'audit_log', ['resource_type', sa.text('created_at DESC')])
    create_index_if_columns_exist('idx_audit_created_desc', 'audit_log', [sa.text('created_at DESC')])
    op.execute(
        "CREATE INDEX idx_audit_not_login ON audit_log (created_at DESC) WHERE action != 'LOGIN'"
    )

def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_audit_not_login')
    op.drop_index('idx_audit_created_desc', table_name='audit_log', if_exists=True)
    op.drop_index('idx_audit_resource_date', table_name='audit_log', if_exists=True)
    op.drop_index('idx_audit_action_date', table_name='audit_log', if_exists=True)
    op.drop_index('idx_audit_resource', table_name='audit_log', if_exists=True)
    op.drop_index('idx_audit_user_action', table_name='audit_log', if_exists=True)
    op.drop_table('audit_log')
