"""fix is_default flag on promoted roles

Revision ID: pg_standalone_051_fix_is_default_flag
Revises: pg_standalone_050_cleanup_default_role
Create Date: 2026-09-24

050 迁移为了让被接替的角色排在前面，把它标记成了 is_default=TRUE。
现在 is_default 仅表示「系统自动创建的『默认』角色」，不再代表任何不可删
限制（角色一律可删除），因此需要把 050 误标到用户自定义角色上的标记还原。

仅修正 is_default=TRUE 且 role_name <> '默认' 的行。
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_051_fix_is_default_flag'
down_revision = 'pg_standalone_050_cleanup_default_role'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE customer_sampling_role
        SET is_default = FALSE,
            updated_at = now()
        WHERE is_default = TRUE
          AND role_name <> '默认'
    """)
    # 列注释同步更新：is_default 不再表示「不可删除」
    op.execute("""
        COMMENT ON COLUMN customer_sampling_role.is_default IS
        '是否系统自动创建的「默认」角色（仅标记来源，不限制删除）'
    """)


def downgrade() -> None:
    """不可逆：仅是一次数据标记修正，回滚无意义。"""
    pass
