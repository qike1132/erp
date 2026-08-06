"""add app_version table (placeholder, table created manually)

Revision ID: add_app_version
Revises: add_backup_record
Create Date: 2026-05-02

The app_version table was created outside of alembic before this
revision was added.  This is a no-op marker so that downstream
migrations (e.g. add_stock_return) can resolve their down_revision.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_app_version'
down_revision = 'add_backup_record'
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
