"""Drop redundant indexes on order table

Revision ID: drop_redundant_order_indexes
Revises: rebuild_po_dedup_index
Create Date: 2026-06-22

背景
----
order 表当前定义了约 25 个索引，存在明显冗余：

- idx_order_customer_product 可被 idx_order_customer_status / idx_order_product_status 覆盖
- idx_order_locked / idx_order_type / idx_order_deleted_by / idx_order_batch_completed_by
  使用频率极低
- idx_order_batch_completed_at 与 idx_order_batch_completed 重复
- idx_order_product_customer_type / idx_order_product_type_country 列过多、场景少
- idx_order_not_deleted_date / idx_order_not_deleted_customer 已被覆盖索引覆盖

操作
----
使用 DROP INDEX CONCURRENTLY 在生产环境安全移除上述索引，
目标是将 order 表索引数量从 25 个降至 15 个左右。

实现说明
--------
`CONCURRENTLY` 必须在事务块外执行，原实现用
`connection.execute(text("COMMIT"))` 绕过事务，在 SQLAlchemy 2.x 下无效
（会以 ActiveSqlTransaction 失败），故改为 `autocommit_block()`。
"""
from alembic import context, op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent

revision = 'drop_redundant_order_indexes'
down_revision = 'rebuild_po_dedup_index'
branch_labels = None
depends_on = None

INDEXES_TO_DROP = [
    'idx_order_customer_product',
    'idx_order_locked',
    'idx_order_type',
    'idx_order_batch_completed_at',
    'idx_order_deleted_by',
    'idx_order_batch_completed_by',
    'idx_order_product_customer_type',
    'idx_order_product_type_country',
    'idx_order_not_deleted_date',
    'idx_order_not_deleted_customer',
]

CREATE_STATEMENTS = [
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_not_deleted_customer ON "order" (customer) WHERE is_deleted IS NOT TRUE',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_not_deleted_date ON "order" (order_date DESC) WHERE is_deleted IS NOT TRUE',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_product_type_country ON "order" (product_id, order_type, country)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_product_customer_type ON "order" (product_id, customer, order_type)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_batch_completed_by ON "order" (batch_completed_by_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_deleted_by ON "order" (deleted_by_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_batch_completed_at ON "order" (batch_completed_at)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_type ON "order" (order_type)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_locked ON "order" (is_locked)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_customer_product ON "order" (customer, product_id)',
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
    _run_concurrently(
        [f'DROP INDEX CONCURRENTLY IF EXISTS {idx}' for idx in INDEXES_TO_DROP])


def downgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    # 判据要求 product / customer 同时缺失，遗留库与已建库一律照常执行。
    if base_schema_absent():
        return
    # 按原定义重建被删除的索引（顺序与删除相反）
    _run_concurrently(CREATE_STATEMENTS)
