"""backup_record 列注释语义收尾：移除已删除的增量备份表述

迁移 094/095 已删除增量备份功能与数据，但 backup_record.type /
parent_record_id 的列注释仍描述 incremental（2026-10-17 审计 P2-19/P2-31）。
本迁移仅同步 COMMENT，不改结构。

Revision ID: pg_standalone_101_backup_record_comment
Revises: pg_standalone_100_fs_remark_key
"""
import sqlalchemy as sa
from alembic import context, op

revision = 'pg_standalone_101_backup_record_comment'
down_revision = 'pg_standalone_100_fs_remark_key'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PG 专属语法；sqlite（测试路径）跳过
    if not context.is_offline_mode() and op.get_bind().dialect.name == 'postgresql':
        op.execute(sa.text(
            "COMMENT ON COLUMN backup_record.type IS '备份类型: full/restore'"
        ))
        op.execute(sa.text(
            "COMMENT ON COLUMN backup_record.parent_record_id IS "
            "'父备份记录ID(历史增量功能已移除，列保留兼容)'"
        ))


def downgrade() -> None:
    if not context.is_offline_mode() and op.get_bind().dialect.name == 'postgresql':
        op.execute(sa.text(
            "COMMENT ON COLUMN backup_record.type IS '备份类型: full/incremental/restore'"
        ))
        op.execute(sa.text(
            "COMMENT ON COLUMN backup_record.parent_record_id IS '父备份记录ID(增量备份指向全量备份)'"
        ))
