"""add app_version table (placeholder, table created manually)

Revision ID: add_app_version
Revises: add_backup_record
Create Date: 2026-05-02

The app_version table was created outside of alembic before this
revision was added.  This is a no-op marker so that downstream
migrations (e.g. add_stock_return) can resolve their down_revision.
"""

from migrations._legacy_base_guard import base_schema_absent

revision = 'add_app_version'
down_revision = 'add_backup_record'
branch_labels = None
depends_on = None


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    pass


def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    pass
