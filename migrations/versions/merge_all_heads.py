"""merge all migration heads

Revision ID: merge_all_heads
Revises: pg_standalone_010
Create Date: 2026-05-10

Merge migration that unifies all divergent migration heads into a
single linear history.  No schema changes -- upgrade / downgrade are
no-ops.

Heads merged:
  - pg_standalone_003  (disconnected pg_standalone branch tip)
  - add_device_token
  - add_order_batch_fields
  - add_order_type_country_stockin
  - add_pp_composite_idx
  - add_stock_return
  - add_updated_at
  - a8f3c2d1e5b7      (change_order_status_nullable)
  - perf_idx_001       (perf_covering_indexes)

The longest chain ends at pg_standalone_010 and is used as
down_revision; every other head is listed in depends_on.
"""

# revision identifiers, used by Alembic.
revision = 'merge_all_heads'
down_revision = 'pg_standalone_010'
branch_labels = None
depends_on = (
    'pg_standalone_003',
    'add_backup_record',
    'add_device_token',
    'add_order_batch_fields',
    'add_order_type_country_stockin',
    'add_pp_composite_idx',
    'add_stock_return',
    'add_updated_at',
    'a8f3c2d1e5b7',
    'perf_idx_001',
)


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
