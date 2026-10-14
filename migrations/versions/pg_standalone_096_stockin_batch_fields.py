"""stock_in 增加批次号字段（对齐 order）

备货记录也要能填批次号、也能被标记「批次完成」（见
docs/superpowers/specs/2026-10-13-stockin-batch-no-design.md）。
三列逐字段对齐 order 的 batch_no / batch_completed_at / batch_completed_by_id，
供 /batch 页把订单与备货统一按订单处理。

Revision ID: pg_standalone_096_stockin_batch_fields
Revises: pg_standalone_095_sync_backup_schedule_task_type_comment
"""
import sqlalchemy as sa

from migrations._legacy_base_guard import (
    add_column_if_absent,
    create_foreign_key_if_absent,
    create_index_if_absent,
    drop_column_if_exists,
    drop_constraint_if_exists,
    drop_index_if_exists,
)

revision = 'pg_standalone_096_stockin_batch_fields'
down_revision = 'pg_standalone_095_sync_backup_schedule_task_type_comment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_absent('stock_in', sa.Column('batch_no', sa.String(length=100), nullable=True, comment='批次号'))
    add_column_if_absent('stock_in', sa.Column('batch_completed_at', sa.DateTime(), nullable=True, comment='批次完成时间'))
    add_column_if_absent('stock_in', sa.Column('batch_completed_by_id', sa.Integer(), nullable=True, comment='批次完成操作人ID'))
    create_foreign_key_if_absent(
        'fk_stockin_batch_completed_by', 'stock_in', 'user',
        ['batch_completed_by_id'], ['id'], ondelete='SET NULL',
    )
    create_index_if_absent('idx_stockin_batch_no', 'stock_in', ['batch_no'])


def downgrade() -> None:
    drop_index_if_exists('idx_stockin_batch_no', table_name='stock_in')
    drop_constraint_if_exists('fk_stockin_batch_completed_by', 'stock_in', type_='foreignkey')
    drop_column_if_exists('stock_in', 'batch_completed_by_id')
    drop_column_if_exists('stock_in', 'batch_completed_at')
    drop_column_if_exists('stock_in', 'batch_no')
