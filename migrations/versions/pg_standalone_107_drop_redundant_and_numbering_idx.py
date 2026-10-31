"""Drop prefix-redundant indexes (P2) + add numbering expression indexes (P3)

Revision ID: pg_standalone_107_drop_redundant_and_numbering_idx
Revises: pg_standalone_106_align_indexes_with_orm
Create Date: 2026-11-01

背景（docs/db-index-analysis-2026-10-31.md §4，owner 2026-11-01 授权执行）
----
**P2 前缀冗余清理（30 个 DROP）**：删除列集被同表另一非唯一非部分 B-tree
索引严格前缀覆盖、且 9 天统计窗口零扫描的索引（例外说明：
- approval_request.ix_approval_request_status（134 次在用）与
  order.ix_order_product_id（12 次在用）**保留**——在用不删；
- inventory_log 删的是零扫描的复合版 idx_inventory_log_product_date，
  保留在用的单列版 ix_inventory_log_product_id；
- idx_stockout_order_type 与 INCLUDE 版 idx_stockout_order_stockin_qty
  键列完全相同，删前者保留覆盖版。）
被删索引的模型声明已同步删除；Down 按删除前的原定义逐字重建。

**P3 编号查询族表达式索引（9 个 CREATE）**：取号 read_daily_max /
巡检 numbering_audit_task / 对账 numbering_reconcile 按「日期段等值 +
序号段取 MAX」访问编号列，正则+split_part 表达式无法使用任何普通
B-tree（此前永远顺扫，order 3722 行规模实测 0.35s）。新建部分表达式索引
（谓词与巡检/对账查询逐字一致）；配套 read_daily_max 过滤器静态化
（动态日期正则 PG 不做蕴含推断，无法命中静态谓词索引）。

安全说明
----
全部 DDL 走 CONCURRENTLY（不锁写），各表均为小表，构建秒级完成。
执行前有 INVALID 索引残留守卫（同 106）。
"""
from alembic import context, op
from sqlalchemy import text

from migrations._legacy_base_guard import base_schema_absent

revision = 'pg_standalone_107_drop_redundant_and_numbering_idx'
down_revision = 'pg_standalone_106_align_indexes_with_orm'
branch_labels = None
depends_on = None

DROP_STATEMENTS = [
    'DROP INDEX CONCURRENTLY IF EXISTS ix_case_movement_case_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_case_movement_customer',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_case_movement_direction',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_material_reg_status',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_modification_log_target_type',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_notification_user_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_customer',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_status',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_batch_audit_log_batch_no',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_item_order_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_outsource_process_order_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_outsource_process_status',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_outsource_process_flow_process_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_status_log_target_type',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_order_sync_record_sync_status',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_outsource_process_type_product_id',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_outsource_shipment_status',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_product_create_time',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_pp_plan_date',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_purchase_order_status',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_purchase_order_status_created',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_purchase_order_supplier',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_ppl_plan_month',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_stockin_customer_product',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_stock_in_customer',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_stock_in_product_id',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_stockout_order',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_stockout_order_type',
    'DROP INDEX CONCURRENTLY IF EXISTS ix_sync_retry_queue_status',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_inventory_log_product_date',
]

CREATE_STATEMENTS = [
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_no_date_seq ON "order" (split_part(order_no, \'-\', 2), CAST(split_part(order_no, \'-\', 3) AS BIGINT)) WHERE order_no ~ \'^[A-Z]+-[0-9]{8}-[0-9]+$\'',
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_no_date_seq ON purchase_order (split_part(order_no, '-', 2), CAST(split_part(order_no, '-', 3) AS BIGINT)) WHERE order_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppl_no_date_seq ON purchase_plans (split_part(plan_no, '-', 2), CAST(split_part(plan_no, '-', 3) AS BIGINT)) WHERE plan_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockin_no_date_seq ON stock_in (split_part(stockin_no, '-', 2), CAST(split_part(stockin_no, '-', 3) AS BIGINT)) WHERE stockin_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_case_movement_no_date_seq ON case_movement (split_part(movement_no, '-', 2), CAST(split_part(movement_no, '-', 3) AS BIGINT)) WHERE movement_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_csp_no_date_seq ON customer_sampling_project (split_part(sequence_no, '-', 2), CAST(split_part(sequence_no, '-', 3) AS BIGINT)) WHERE sequence_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_outsource_shipment_no_date_seq ON outsource_shipment (split_part(shipment_no, '-', 2), CAST(split_part(shipment_no, '-', 3) AS BIGINT)) WHERE shipment_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_no_date_seq ON stock_out (split_part(stockout_no, '-', 2), CAST(split_part(stockout_no, '-', 3) AS BIGINT)) WHERE stockout_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockreturn_no_date_seq ON stock_return (split_part(return_no, '-', 2), CAST(split_part(return_no, '-', 3) AS BIGINT)) WHERE return_no ~ '^[A-Z]+-[0-9]{8}-[0-9]+$'",
]

DOWNGRADE_DROPS = [
    'DROP INDEX CONCURRENTLY IF EXISTS idx_order_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_purchase_order_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_ppl_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_stockin_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_case_movement_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_csp_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_outsource_shipment_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_stockout_no_date_seq',
    'DROP INDEX CONCURRENTLY IF EXISTS idx_stockreturn_no_date_seq',
]

DOWNGRADE_RECREATES = [
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_case_movement_case_id ON public.case_movement USING btree (case_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_case_movement_customer ON public.case_movement USING btree (customer)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_case_movement_direction ON public.case_movement USING btree (direction)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_status ON public.material_registration USING btree (status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_modification_log_target_type ON public.modification_log USING btree (target_type)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notification_user_id ON public.notification USING btree (user_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_customer ON public."order" USING btree (customer)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_status ON public."order" USING btree (status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_batch_audit_log_batch_no ON public.order_batch_audit_log USING btree (batch_no)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_item_order_id ON public.order_item USING btree (order_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_outsource_process_order_id ON public.order_outsource_process USING btree (order_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_outsource_process_status ON public.order_outsource_process USING btree (status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_outsource_process_flow_process_id ON public.order_outsource_process_flow USING btree (process_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_status_log_target_type ON public.order_status_log USING btree (target_type)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_order_sync_record_sync_status ON public.order_sync_record USING btree (sync_status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_outsource_process_type_product_id ON public.outsource_process_type USING btree (product_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_outsource_shipment_status ON public.outsource_shipment USING btree (status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_product_create_time ON public.product USING btree (create_time)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pp_plan_date ON public.production_plan USING btree (plan_date)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_status ON public.purchase_order USING btree (status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_status_created ON public.purchase_order USING btree (status, create_time)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_supplier ON public.purchase_order USING btree (supplier_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppl_plan_month ON public.purchase_plans USING btree (plan_month)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockin_customer_product ON public.stock_in USING btree (customer, product_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_stock_in_customer ON public.stock_in USING btree (customer)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_stock_in_product_id ON public.stock_in USING btree (product_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_order ON public.stock_out USING btree (order_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_order_type ON public.stock_out USING btree (order_id, stockin_id)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sync_retry_queue_status ON public.sync_retry_queue USING btree (status)',
    'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_inventory_log_product_date ON public.inventory_log USING btree (product_id, change_date DESC)',
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
