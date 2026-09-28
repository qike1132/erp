"""add updated_at to all tables

Revision ID: add_updated_at
Revises:
Create Date: 2026-05-06

修正说明
--------
1. 原文里 plpgsql 的 dollar-quoting 写成单个 `$`（`AS $`、`DO $`、`END$;`），
   在 PostgreSQL 下是语法错误，迁移从未生效（现网 `erp_system` 亦无
   `set_updated_at` 触发器与 `trigger_set_updated_at` 函数）。此处恢复为 `$$`。
2. 列表里的 `app_version` / `daily_production_record` 并非由任何迁移创建
   （前者注释即写明「表由手工创建」），空库重放时 `ALTER TABLE` 会报
   relation does not exist，故按「表存在才处理」过滤；缺失的表由
   `pg_standalone_054_sync_schema_with_orm_metadata` 依 ORM 元数据兜底。
"""
from alembic import op

from migrations._legacy_base_guard import (
    base_schema_absent,
    table_exists,
)

revision = 'add_updated_at'
down_revision = '659467a97350'
branch_labels = None
# 该迁移必须作用于 pg_standalone_001 建出的基础 schema；否则空库重放时
# 它先于 001 执行，被空库守卫拦下，updated_at / 触发器永久缺失。
depends_on = ('pg_standalone_001',)

TABLES = [
    'product', 'order', 'stock_in', 'stock_out', 'stock_return',
    'inventory_log', 'case', 'case_stock_in', 'case_stock_out',
    'case_inventory_log', 'permission', 'app_version', 'craft_work',
    'daily_production_record', 'packaging_record', 'order_status_log',
    'customer_access_log', 'modification_log', 'saved_query',
    'approval_request', 'approval_log', 'purchase_order_item',
    'shipment_records', 'purchase_plan_details', 'production_plan_log',
    'staging_purchase_plan', 'order_sync_record',
]


def _existing_tables() -> list[str]:
    return [t for t in TABLES if table_exists(t)]


def upgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    # Create trigger function first (CREATE OR REPLACE is idempotent)
    op.execute("""
        CREATE OR REPLACE FUNCTION trigger_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    # Add updated_at column only if it doesn't already exist
    for table in _existing_tables():
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{table}' AND column_name = 'updated_at'
                ) THEN
                    ALTER TABLE "{table}" ADD COLUMN updated_at TIMESTAMP WITHOUT TIME ZONE;
                END IF;
            END$$;
        """)
    # Create triggers only if they don't already exist
    for table in _existing_tables():
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger WHERE tgname = 'set_updated_at' AND tgrelid = '{table}'::regclass
                ) THEN
                    CREATE TRIGGER set_updated_at
                        BEFORE UPDATE ON "{table}"
                        FOR EACH ROW
                        EXECUTE FUNCTION trigger_set_updated_at();
                END IF;
            END$$;
        """)


def downgrade() -> None:
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    for table in _existing_tables():
        op.execute(f'DROP TRIGGER IF EXISTS set_updated_at ON "{table}"')
    op.execute('DROP FUNCTION IF EXISTS trigger_set_updated_at()')
    for table in _existing_tables():
        op.drop_column(table, 'updated_at')
