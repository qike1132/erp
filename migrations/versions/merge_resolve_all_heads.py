"""merge all current heads into a single head

Revision ID: merge_resolve_all_heads
Revises: pg_standalone_013, add_country_table, add_missing_perf_idx,
         add_order_batch_fields, add_order_type_country_stockin,
         add_pp_composite_idx, add_stock_return, add_updated_at,
         a8f3c2d1e5b7, merge_all_heads, pg_standalone_003
Create Date: 2026-06-11

This merge unifies the 10 divergent migration heads into one.
All parent migrations have been stamped as applied because the
target schema is already present in the database (built by a
combination of alembic runs and manual ``Base.metadata.create_all``
calls).  The upgrade/downgrade bodies are no-ops.
"""
from alembic import op

revision = 'merge_resolve_all_heads'
down_revision = (
    'pg_standalone_013',
    'add_country_table',
    'add_missing_perf_idx',
    'add_order_batch_fields',
    'add_order_type_country_stockin',
    'add_pp_composite_idx',
    'add_stock_return',
    'add_updated_at',
    'a8f3c2d1e5b7',
    'merge_all_heads',
    'pg_standalone_003',
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
