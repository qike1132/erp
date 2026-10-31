"""Align database indexes with ORM declarations (2026-10-31 index audit)

Revision ID: pg_standalone_106_align_indexes_with_orm
Revises: pg_standalone_105_purchase_order_generate_idempotency
Create Date: 2026-10-31

背景（docs/db-index-analysis-2026-10-31.md）
----
2026-10-31 只读体检发现：alembic_version=head 但库结构落后于 ORM 声明——
历史 psql 恢复走「DROP+CREATE 库 + stamp 版本」路径，53 个模型声明的索引
从未落库（幽灵索引，永不生效）。本迁移做三件事：

1. **补建 44 个幽灵索引**（CREATE ... CONCURRENTLY IF NOT EXISTS）：
   DDL 由 SQLAlchemy CreateIndex 从 ORM 模型逐字编译生成，与声明完全一致。
   其中 order 的两个 idx_perf_* 谓词已随本次体检从 ``is_deleted = false``
   修正为 ``IS NOT TRUE``（订单列表查询用 IS NOT TRUE，PG 不做谓词蕴含
   推断，= false 版索引无法服务该查询——模型侧同步修正）。
2. **删除 6 个问题索引**：
   - audit_log 3 个（idx_audit_created_desc / idx_audit_resource_date /
     ix_audit_log_user_id）：纯追加表无 SELECT 读路径（读方仅备份校验走
     pkey），9 天窗口 idx_scan=0，26 万行规模下每次审计 INSERT 白付
     3 次索引维护。模型侧同步删除全部索引声明。
   - ix_purchase_order_source_order_id：与 idx_purchase_order_source_order_id
     同列重复（pg_standalone_054 引入的 bug），保留显式命名版本。
   - idx_purchase_order_item_order：被本次补建的 idx_perf_poi_order_include
     (order_id) INCLUDE (...) 前缀覆盖。
   - idx_material_reg_supplier：列漂移（库内是 supplier_name，模型声明
     supplier_id），删旧建新。
3. stock_in / stock_out 的 idx_perf_*_product_date 声明从模型删除而非落库：
   与库内 ASC 版同列，B-tree 可反向扫描，双向索引是纯冗余。

安全说明
----
全部 DDL 走 CONCURRENTLY（不锁写），必须在事务块外执行（autocommit_block）。
各表当前均为小表（<500 行），CONCURRENTLY 构建秒级完成。
执行前需确认无 INVALID 索引残留（上次 CONCURRENTLY 失败的产物）。
"""
from alembic import context, op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_106_align_indexes_with_orm'
down_revision = 'pg_standalone_105_purchase_order_generate_idempotency'
branch_labels = None
depends_on = None

# 先删（避免新旧并存窗口内的双份写放大），后建。
DROP_STATEMENTS = [
    'DROP INDEX CONCURRENTLY IF EXISTS idx_audit_created_desc',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_audit_resource_date',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_audit_log_user_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_purchase_order_source_order_id',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_purchase_order_item_order',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_supplier',
]

CREATE_STATEMENTS = [
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_sync_record_source_order_id ON order_sync_record (source_order_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_permission_parent ON permission (parent_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_product_name_date ON product (create_time DESC, id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_production_plan_customer_name ON production_plan (customer_name)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_production_plan_barcode ON production_plan (barcode)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_staging_purchase_plan_session_id ON staging_purchase_plan (session_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_staging_purchase_plan_upload_batch_id ON staging_purchase_plan (upload_batch_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_case_name_trgm ON "case" USING gin (name gin_trgm_ops)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_case_barcode_trgm ON "case" USING gin (barcode gin_trgm_ops)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_access_log_customer ON customer_access_log (customer_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_access_log_user ON customer_access_log (user_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_modification_log_modifier ON modification_log (modifier_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_modification_log_modify_time ON modification_log (modify_time)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_customer_trgm ON "order" USING gin (customer gin_trgm_ops)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_status_date_covering ON "order" (status, order_date DESC, id) WHERE is_deleted IS NOT TRUE',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_customer_date ON "order" (customer, order_date DESC) WHERE is_deleted IS NOT TRUE',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_locked_by ON "order" (locked_by_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_batch_completed ON "order" (batch_completed_at DESC) WHERE batch_completed_at IS NOT NULL',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_batch_audit_log_created_at ON order_batch_audit_log (created_at)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_status_log_operator ON order_status_log (operator_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_status_log_action_time ON order_status_log (action_time)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_sync_config_updated_by ON order_sync_config (updated_by_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_created_by ON purchase_order (created_by)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_supplier_status ON purchase_order (supplier_id, status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_po_status_date_covering ON purchase_order (status, create_time DESC, id) INCLUDE (order_no, supplier_name, customer_name)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_saved_query_query_type ON saved_query (query_type)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staging_order_product ON staging_order (product_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_staging_order_session_id ON staging_order (session_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_staging_stock_in_session_id ON staging_stock_in (session_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staging_stockin_product ON staging_stock_in (product_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_staging_stockout_product ON staging_stock_out (product_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_csp_sequence_no ON customer_sampling_project (sequence_no)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_status_date ON material_registration (status, registration_date)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_order_no ON material_registration (purchase_order_no)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_purchase_order ON material_registration (purchase_order_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_accessory_supplier ON product_accessory (supplier_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_fabric_supplier ON product_fabric (supplier_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_material_product ON product_material (product_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_material_supplier ON product_material (supplier_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_poi_order_include ON purchase_order_item (order_id) INCLUDE (material_name, quantity, unit_price)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_deduction ON stock_out (product_id, stockout_date DESC) WHERE stockin_id IS NOT NULL',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_approval_log_actor ON approval_log (actor_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_item_order_item ON material_registration_item (order_item_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_supplier ON material_registration (supplier_id)',
]

DOWNGRADE_DROPS = [
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_sync_record_source_order_id',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_permission_parent',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_product_name_date',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_production_plan_customer_name',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_production_plan_barcode',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_staging_purchase_plan_session_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_staging_purchase_plan_upload_batch_id',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_case_name_trgm',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_case_barcode_trgm',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_customer_access_log_customer',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_customer_access_log_user',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_modification_log_modifier',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_modification_log_modify_time',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_order_customer_trgm',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_status_date_covering',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_order_customer_date',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_order_locked_by',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_order_batch_completed',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_batch_audit_log_created_at',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_order_status_log_operator',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_status_log_action_time',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_order_sync_config_updated_by',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_purchase_order_created_by',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_purchase_order_supplier_status',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_po_status_date_covering',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_saved_query_query_type',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_staging_order_product',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_staging_order_session_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_staging_stock_in_session_id',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_staging_stockin_product',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_staging_stockout_product',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_csp_sequence_no',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_status_date',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_order_no',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_purchase_order',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_product_accessory_supplier',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_product_fabric_supplier',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_product_material_product',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_product_material_supplier',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_perf_poi_order_include',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_stockout_deduction',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_approval_log_actor',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_item_order_item',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_supplier',
]

DOWNGRADE_RECREATES = [
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_supplier ON material_registration (supplier_name)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_item_order ON purchase_order_item (order_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_purchase_order_source_order_id ON purchase_order (source_order_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_resource_date ON audit_log (resource_type, created_at DESC)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_created_desc ON audit_log (created_at DESC)',
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


def _fail_if_invalid_indexes() -> None:
    """上次 CONCURRENTLY 被取消会留下 INVALID 索引，先失败提醒人工清理。"""
    conn = op.get_bind()
    rows = conn.execute(text(
        "SELECT count(*) FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "WHERE NOT i.indisvalid AND c.relnamespace = 'public'::regnamespace"
    )).scalar()
    if rows:
        raise RuntimeError(
            "检测到 " + str(rows) + " 个 INVALID 索引（上次 CONCURRENTLY 失败残留），"
            "请先人工 DROP 后重跑本迁移")


def upgrade():
    # 空库守卫：pg_standalone_001 尚未建出基础 schema 时整条增量迁移空转。
    if base_schema_absent():
        return
    if not context.is_offline_mode():
        _fail_if_invalid_indexes()
    _run_concurrently(DROP_STATEMENTS)
    _run_concurrently(CREATE_STATEMENTS)


def downgrade():
    if base_schema_absent():
        return
    _run_concurrently(DOWNGRADE_DROPS)
    _run_concurrently(DOWNGRADE_RECREATES)
