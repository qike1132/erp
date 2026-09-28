"""rename default role

Revision ID: pg_standalone_029_rename_default_role
Revises: pg_standalone_028_cs_role
Create Date: 2026-08-12

把历史默认角色 role_name 由 '默认角色' 统一改为 '默认'。
028 迁移已经把硬编码默认值改成 '默认'，但 028 已 apply 过的库中
仍有 role_name='默认角色' 的历史行需要回填。
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_029_rename_default_role'
down_revision = 'pg_standalone_028_cs_role'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 仅更新 is_default=TRUE 的默认角色，避免误改用户自定义角色
    op.execute("""
        UPDATE customer_sampling_role
        SET role_name = '默认'
        WHERE is_default = TRUE AND role_name = '默认角色'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE customer_sampling_role
        SET role_name = '默认角色'
        WHERE is_default = TRUE AND role_name = '默认'
    """)
