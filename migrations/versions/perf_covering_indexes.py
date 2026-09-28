"""Add performance covering indexes

Revision ID: perf_idx_001
Revises: 659467a97350
Create Date: 2026-05-05

说明
----
本迁移用 `CREATE INDEX CONCURRENTLY` 建覆盖索引（对应 ORM 中
`idx_perf_*` 系列 Index 声明），必须在事务块外执行，故统一走
`autocommit_block()`；原实现用 `connection.execute(text("COMMIT"))`
绕过事务，在 SQLAlchemy 2.x 下无效（会以 ActiveSqlTransaction 失败）。

原 DDL 另有三处目标错误，导致即使执行也不会成功，此处一并修正：

* `orders` -> `"order"`（表名字面量写错，且 `order` 是保留字需加引号）
* `order(customer_name)` -> `order(customer)`
* `stock_in/stock_out(... , date DESC)` -> `stockin_date` / `stockout_date`

另删去 `idx_perf_po_status_date_covering`：该索引在任何环境都不存在，
且 ORM 元数据未声明它，保留会与 `alembic check` 门禁冲突。
"""
from alembic import context, op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent

revision = 'perf_idx_001'
down_revision = '659467a97350'
branch_labels = None
depends_on = None

INDEXES_UP = [
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_status_date_covering
        ON "order" (status, order_date DESC, id)
        WHERE is_deleted = false
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_customer_date
        ON "order" (customer, order_date DESC)
        WHERE is_deleted = false
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockin_product_date
        ON stock_in (product_id, stockin_date DESC)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockout_product_date
        ON stock_out (product_id, stockout_date DESC)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_poi_order_include
        ON purchase_order_item (order_id)
        INCLUDE (material_name, quantity, unit_price)
    """,
    """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_product_name_date
        ON product (create_time DESC, id)
    """,
]

INDEXES_DOWN = [
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_product_name_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_poi_order_include",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockout_product_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockin_product_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_customer_date",
    "DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_status_date_covering",
]


def _run_concurrently(statements) -> None:
    """CONCURRENTLY 语句必须在事务外执行（offline 模式直接输出 SQL）。"""
    if context.is_offline_mode():
        for ddl in statements:
            op.execute(text(ddl))
        return
    with op.get_context().autocommit_block():
        for ddl in statements:
            op.execute(text(ddl))


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    _run_concurrently(INDEXES_UP)


def downgrade():
    if base_schema_absent():
        return
    _run_concurrently(INDEXES_DOWN)
