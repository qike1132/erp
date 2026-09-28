"""customer_sampling_change_log.project_id: CASCADE -> SET NULL

Revision ID: pg_standalone_020_cs_changelog_set_null
Revises: pg_standalone_019_customer_sampling
Create Date: 2026-08-08

修复代码审查问题1（严重）：审计日志被级联删除。

变更内容：
- customer_sampling_change_log.project_id 外键 ondelete 从 CASCADE 改为 SET NULL
- customer_sampling_change_log.project_id 改为 nullable=True

原因：删除打样项目时，审计日志（变更日志）也被级联删除，导致无法追溯删除操作。
改为 SET NULL 后，项目删除时日志的 project_id 被置为 NULL，日志记录保留可追溯。

注意：
- ORM 模型中 CustomerSamplingProject.change_logs relationship 已去掉
  cascade='all, delete-orphan'，避免 ORM 层级联删除日志。
- 本迁移仅修改数据库层外键约束与 nullable 属性。
- PostgreSQL 中 CREATE TABLE 自动生成的外键约束名为 <table>_<column>_fkey，
  即 customer_sampling_change_log_project_id_fkey（由 019 迁移创建）。
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'pg_standalone_020_cs_changelog_set_null'
down_revision = 'pg_standalone_019_customer_sampling'
branch_labels = None
depends_on = None


# 019 迁移创建表时未显式命名外键，PostgreSQL 自动命名为 <table>_<column>_fkey
_FK_NAME = 'customer_sampling_change_log_project_id_fkey'


def upgrade():
    # 1. 删除旧的外键约束（CASCADE）
    op.drop_constraint(_FK_NAME, 'customer_sampling_change_log', type_='foreignkey')

    # 2. 将 project_id 改为 nullable=True
    op.alter_column(
        'customer_sampling_change_log', 'project_id',
        existing_type=sa.Integer(),
        nullable=True,
        existing_comment='关联项目ID（SET NULL：项目删除后日志保留可追溯）',
    )

    # 3. 重新创建外键约束（SET NULL）
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
