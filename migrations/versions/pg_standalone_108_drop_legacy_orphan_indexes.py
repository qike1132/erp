"""Drop legacy-orphan indexes so migration-chain end state matches ORM (CI check)

Revision ID: pg_standalone_108_drop_legacy_orphan_indexes
Revises: pg_standalone_107_drop_redundant_and_numbering_idx
Create Date: 2026-11-01

背景（2026-11-01 CI Verify Alembic migrations 失败的收口）
----
``alembic check``（模型 metadata vs 迁移链终态）在 CI 空库上检出 10 个
remove_index：这些索引由历史迁移（012/054 建表期 audit_log 索引、
001 的 staging 表列级索引、perf_idx_001 的 idx_perf_*）在**空库全链重放**
时建出，但其 ORM 声明已随 pg_standalone_106/107 的索引治理**有意删除**
（体检报告 docs/db-index-analysis-2026-10-31.md）：

- audit_log 7 个：纯追加表无 SELECT 读路径（读方仅备份校验走 pkey）；
- ix_staging_stock_out_session_id：与显式命名的 idx_staging_stockout_session
  同列双声明（列级 index=True 的重复声明缺陷）；
- idx_perf_{stockin,stockout}_product_date：与库内 ASC 版同列，B-tree
  可反向扫描，双向索引是纯冗余。

生产库上这 10 个**全部不存在**（历史 psql 恢复快照未含），因此本迁移
在生产为幂等 no-op；在 CI 空库重放路径上删除它们，使迁移链终态与
模型声明一致（check 绿）。Down 按历史迁移原定义逐字重建。

安全说明
----
DROP 全部 CONCURRENTLY IF EXISTS（事务外执行，不存在则 no-op）。
"""
from alembic import context, op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_108_drop_legacy_orphan_indexes'
down_revision = 'pg_standalone_107_drop_redundant_and_numbering_idx'
branch_labels = None
depends_on = None

DROP_STATEMENTS = [
    'DROP INDEX CONCURRENTLY IF EXISTS idx_audit_user_action',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_audit_resource',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_audit_action_date',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_audit_not_login',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_audit_log_action',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_audit_log_created_at',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_audit_log_resource_type',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_staging_stock_out_session_id',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockin_product_date',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_stockout_product_date',
]

DOWNGRADE_RECREATES = [
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_user_action ON audit_log (user_id, action)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_resource ON audit_log (resource_type, resource_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_action_date ON audit_log (action, created_at)',
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_not_login ON audit_log (created_at DESC) WHERE action != 'LOGIN'",
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_action ON audit_log (action)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_resource_type ON audit_log (resource_type)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_staging_stock_out_session_id ON staging_stock_out (session_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockin_product_date ON stock_in (product_id, stockin_date DESC)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockout_product_date ON stock_out (product_id, stockout_date DESC)',
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
    if base_schema_absent():
        return
    _run_concurrently(DROP_STATEMENTS)


def downgrade():
    if base_schema_absent():
        return
    _run_concurrently(DOWNGRADE_RECREATES)
