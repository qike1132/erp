"""fix customer_sampling_change_log.project_id nullable + SET NULL

修复既有 schema 不一致：数据库 customer_sampling_change_log.project_id
实际为 NOT NULL + ON DELETE CASCADE（019 创建时的状态），但 ORM 模型声明为
可空 + ondelete='SET NULL'（020 迁移的意图，未在库上生效）。

后果：删除打样项目时，ORM 尝试将日志 project_id 置 NULL（SET NULL 语义），
违反数据库 NOT NULL 约束 → DELETE /projects/{id} 返回 500。

修复：将 project_id 改为 nullable=True，并重建外键为 ON DELETE SET NULL，
与 ORM 模型对齐。幂等、可逆。

Revision ID: pg_standalone_033_changelog_project_id_nullable
Revises: pg_standalone_032_add_completed_at
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_033_changelog_project_id_nullable'
down_revision = 'pg_standalone_032_add_completed_at'
branch_labels = None
depends_on = None

_FK_NAME = 'customer_sampling_change_log_project_id_fkey'


def upgrade():
    # 1. 删除旧外键约束（CASCADE）
    op.drop_constraint(_FK_NAME, 'customer_sampling_change_log', type_='foreignkey')

    # 2. 将 project_id 改为 nullable=True
    op.alter_column(
        'customer_sampling_change_log', 'project_id',
        existing_type=sa.Integer(),
        nullable=True,
        existing_comment='关联项目ID（SET NULL：项目删除后日志保留可追溯）',
    )

    # 3. 重建外键约束（SET NULL）
    op.create_foreign_key(
        _FK_NAME,
        'customer_sampling_change_log',
        'customer_sampling_project',
        ['project_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    # 回滚：先删 SET NULL 约束，恢复 NOT NULL，再建 CASCADE 约束
    op.drop_constraint(_FK_NAME, 'customer_sampling_change_log', type_='foreignkey')

    # 注意：回滚前需确保没有 project_id IS NULL 的记录，否则 NOT NULL 会失败
    op.alter_column(
        'customer_sampling_change_log', 'project_id',
        existing_type=sa.Integer(),
        nullable=False,
        existing_comment='关联项目ID',
    )

    op.create_foreign_key(
        _FK_NAME,
        'customer_sampling_change_log',
        'customer_sampling_project',
        ['project_id'],
        ['id'],
        ondelete='CASCADE',
    )
