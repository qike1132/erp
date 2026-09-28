"""convert datetime columns to timezone-aware

Revision ID: pg_standalone_013
Revises: None
Create Date: 2026-05-23

Fix asyncpg DataError: cannot pass offset-aware datetime to
TIMESTAMP WITHOUT TIME ZONE columns.  All DateTime columns that
use datetime.now(timezone.utc) as default/onupdate are changed to
DateTime(timezone=True), which maps to TIMESTAMP WITH TIME ZONE.
"""
from alembic import op

from migrations._legacy_base_guard import table_columns

revision = 'pg_standalone_013'
down_revision = 'pg_standalone_012'
branch_labels = None
depends_on = None

_COLUMNS = [
    ("user", "create_time"),
    ("user", "update_time"),
    ("supplier", "created_at"),
    ("supplier", "updated_at"),
    ("stock_return", "return_date"),
    ("stock_return", "updated_at"),
    ("stock_out", "stockout_date"),
    ("stock_out", "updated_at"),
    ("stock_in", "stockin_date"),
    ("stock_in", "updated_at"),
    ("staging_stock_out", "stockout_date"),
    ("staging_stock_out", "created_at"),
    ("staging_stock_out", "updated_at"),
    ("staging_stock_in", "stockin_date"),
    ("staging_stock_in", "created_at"),
    ("staging_stock_in", "updated_at"),
    ("staging_order", "order_date"),
    ("staging_order", "created_at"),
    ("staging_order", "updated_at"),
    ("purchase_plans", "create_time"),
    ("purchase_plans", "update_time"),
    ("shipment_records", "synced_at"),
    ("shipment_records", "created_at"),
    ("shipment_records", "updated_at"),
    ("modification_log", "modify_time"),
    ("modification_log", "updated_at"),
    ("saved_query", "create_time"),
    ("saved_query", "updated_at"),
    ("purchase_order", "create_time"),
    ("purchase_order", "update_time"),
    ("purchase_order_item", "create_time"),
    ("purchase_order_item", "updated_at"),
    ("production_plan", "create_time"),
    ("production_plan", "update_time"),
    ("production_plan_log", "operate_time"),
    ("production_plan_log", "updated_at"),
    ("staging_purchase_plan", "created_at"),
    ("staging_purchase_plan", "updated_at"),
    ("product_fabric", "create_time"),
    ("product_fabric", "update_time"),
    ("product_material", "create_time"),
    ("product_material", "update_time"),
    ("product_accessory", "create_time"),
    ("product_accessory", "update_time"),
    ("product_packaging", "create_time"),
    ("product_packaging", "update_time"),
    ("product", "create_time"),
    ("product", "updated_at"),
    ("permission", "updated_at"),
    ("packaging_record", "create_time"),
    ("packaging_record", "updated_at"),
    ("order_sync_record", "sync_time"),
    ("order_sync_record", "updated_at"),
    ("sync_retry_queue", "created_at"),
    ("sync_retry_queue", "updated_at"),
    ("order_sync_config", "updated_at"),
    ("order_status_log", "action_time"),
    ("order_status_log", "updated_at"),
    ("order", "order_date"),
    ("order", "updated_at"),
    ("order_batch_audit_log", "created_at"),
    ("material_registration", "create_time"),
    ("material_registration", "update_time"),
    ("material_registration_item", "create_time"),
    ("inventory_log", "change_date"),
    ("inventory_log", "updated_at"),
    ("daily_production_record", "create_time"),
    ("daily_production_record", "updated_at"),
    ("customer_access_log", "access_time"),
    ("customer_access_log", "updated_at"),
    ("customer", "create_time"),
    ("customer", "update_time"),
    ("case_stock_out", "stockout_date"),
    ("case_stock_out", "updated_at"),
    ("craft_work", "create_time"),
    ("craft_work", "updated_at"),
    ("case_stock_in", "stockin_date"),
    ("case_stock_in", "updated_at"),
    ("case_inventory_log", "change_date"),
    ("case_inventory_log", "updated_at"),
    ("case", "create_time"),
    ("case", "updated_at"),
    ("backup_record", "created_at"),
    ("backup_record", "updated_at"),
    ("audit_log", "created_at"),
]


def _q(identifier: str) -> str:
    """Quote a Postgres identifier (table/column name) with double quotes.

    All identifiers in _COLUMNS are plain ASCII snake_case, but we quote
    defensively in case future additions include reserved words.
    """
    return '"' + identifier.replace('"', '""') + '"'


def _convert(target_type: str, pairs) -> None:
    """批量改列类型；表或列不存在则跳过（空库重放时部分对象尚未建出）。

    真实库上所有列都存在，行为与改动前完全一致。
    """
    cache: dict[str, set | None] = {}
    for table, column in pairs:
        if table not in cache:
            cache[table] = table_columns(table)
        present = cache[table]
        if present is None or column not in present:
            continue
        op.execute(
            f'ALTER TABLE {_q(table)} '
            f'ALTER COLUMN {_q(column)} '
            f'TYPE {target_type} '
            f"USING {_q(column)} AT TIME ZONE 'UTC'"
        )


def upgrade() -> None:
    """Upgrade TIMESTAMP WITHOUT TIME ZONE → TIMESTAMP WITH TIME ZONE.

    CRITICAL: All existing values were stored as naive UTC (see pervasive
    ``datetime.now(UTC).replace(tzinfo=None)`` pattern in services/ and
    shared_models/).  Without ``AT TIME ZONE 'UTC'``, PostgreSQL would
    interpret naive values in the *session's local timezone* (e.g.
    Asia/Shanghai = UTC+8), silently shifting every historical timestamp
    by +/- N hours — a silent data-corruption event affecting audit logs,
    modification histories, inventory timing, and financial reports.
    """
    _convert('TIMESTAMP WITH TIME ZONE', _COLUMNS)


def downgrade() -> None:
    """Inverse: timestamptz → timestamp using UTC to preserve values."""
    _convert('TIMESTAMP WITHOUT TIME ZONE', reversed(_COLUMNS))
