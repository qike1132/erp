"""add GIN index on purchase_order.source_order_ids::jsonb

Revision ID: pg_standalone_017_add_po_source_order_ids_gin_index
Revises: pg_standalone_016_dashboard_daily_stats_mv
Create Date: 2026-07-24

为 purchase_order.source_order_ids 创建 GIN 表达式索引，加速 P-6 引入的
NOT EXISTS + JSONB @> 子查询。source_order_ids 是 Text 类型存储 JSON 数组，
表达式索引 (source_order_ids::jsonb) 使 @> 操作符能走索引扫描。
"""
from alembic import op

revision = 'pg_standalone_017_add_po_source_order_ids_gin_index'
down_revision = 'pg_standalone_016_dashboard_daily_stats_mv'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_purchase_order_source_ids_gin "
        "ON purchase_order USING GIN ((source_order_ids::jsonb))"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_purchase_order_source_ids_gin")
