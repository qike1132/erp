"""同步 backup_schedule.task_type 列注释（去掉已移除的 incremental）

背景
----
全量-only 改造把 ORM 里该列的 comment 从
`任务类型: full/incremental/integrity_check/cleanup/disaster_recovery_test`
改为 `任务类型: full/integrity_check/cleanup/disaster_recovery_test`，
但当时没配迁移。CI 的 `alembic check`（空库 upgrade head 后按 ORM 元数据
autogenerate 比对）检出 `modify_comment` 差异而失败（CI run 38220091898）。
本迁移把**库侧**注释同步到模型，恢复 schema == ORM。

Revision ID: pg_standalone_095_sync_backup_schedule_task_type_comment
Revises: pg_standalone_094_drop_incremental_backup
"""
import sqlalchemy as sa
from alembic import op

revision = 'pg_standalone_095_sync_backup_schedule_task_type_comment'
down_revision = 'pg_standalone_094_drop_incremental_backup'
branch_labels = None
depends_on = None

_NEW = '任务类型: full/integrity_check/cleanup/disaster_recovery_test'
_OLD = '任务类型: full/incremental/integrity_check/cleanup/disaster_recovery_test'


def upgrade() -> None:
    op.alter_column(
        'backup_schedule', 'task_type',
        existing_type=sa.String(length=30), existing_nullable=False,
        comment=_NEW,
    )


def downgrade() -> None:
    op.alter_column(
        'backup_schedule', 'task_type',
        existing_type=sa.String(length=30), existing_nullable=False,
        comment=_OLD,
    )
