"""create product aggregate materialized view

Revision ID: pg_standalone_017_product_aggregate_mv
Revises: add_outsource_process_flow
Create Date: 2026-08-21

新增按产品维度的聚合物化视图，服务于产品列表/详情页的
订单数、入库数、出库数统计（原 3 个子查询聚合，数据增长后变慢）：

- mv_product_aggregate: 按 product_id 聚合
  - order_count / order_quantity: 关联订单数、下单件数（多 SKU 模型按 order_item 聚合）
  - stockin_count / stockin_quantity: 入库笔数、入库数量
  - stockout_count / stockout_quantity: 出库笔数、净出库数量（扣除退货）
  - last_order_date / last_stockin_date / last_stockout_date: 最近活动日期（列表排序常用）

刷新策略：与现有 mv_daily_* 一致，由 ARQ 每 5 分钟 CONCURRENTLY 刷新
（需唯一索引，见本迁移）。

注：down_revision 指向当前唯一 head（add_outsource_process_flow），
避免与 016 分支上的 017_add_po_source / 017_pattern_room_v2 产生多 head。
"""
from alembic import op

revision = 'pg_standalone_017_product_aggregate_mv'
down_revision = 'add_outsource_process_flow'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_product_aggregate AS
    WITH product_ids AS (
        SELECT p.id AS product_id
        FROM product p
    )
    SELECT
        pi.product_id,
        COALESCE(o.order_count, 0)        AS order_count,
        COALESCE(o.order_quantity, 0)     AS order_quantity,
        COALESCE(o.last_order_date, NULL) AS last_order_date,
        COALESCE(si.stockin_count, 0)     AS stockin_count,
        COALESCE(si.stockin_quantity, 0)  AS stockin_quantity,
        COALESCE(si.last_stockin_date, NULL) AS last_stockin_date,
        COALESCE(so.stockout_count, 0)    AS stockout_count,
        COALESCE(so.stockout_quantity, 0) AS stockout_quantity,
        COALESCE(so.last_stockout_date, NULL) AS last_stockout_date
    FROM product_ids pi
    LEFT JOIN (
        SELECT oi.product_id,
               COUNT(DISTINCT oi.order_id) AS order_count,
               SUM(oi.quantity)            AS order_quantity,
               MAX(o.order_date)           AS last_order_date
        FROM order_item oi
        JOIN "order" o ON o.id = oi.order_id
        WHERE o.is_deleted IS NOT TRUE
        GROUP BY oi.product_id
    ) o ON o.product_id = pi.product_id
    LEFT JOIN (
        SELECT product_id,
               COUNT(*)           AS stockin_count,
               SUM(quantity)      AS stockin_quantity,
               MAX(stockin_date)  AS last_stockin_date
        FROM stock_in
        GROUP BY product_id
    ) si ON si.product_id = pi.product_id
    LEFT JOIN (
        SELECT product_id,
               COUNT(*)           AS stockout_count,
               SUM(quantity - returned_quantity) AS stockout_quantity,
               MAX(stockout_date) AS last_stockout_date
        FROM stock_out
        WHERE (quantity - returned_quantity) > 0
        GROUP BY product_id
    ) so ON so.product_id = pi.product_id
    WHERE pi.product_id IS NOT NULL;
    """)

    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_product_aggregate_product_id
    ON mv_product_aggregate(product_id);
    """)

    # 列表排序常用：最近出货日期、出库量
    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_mv_product_aggregate_last_stockout
    ON mv_product_aggregate(last_stockout_date DESC NULLS LAST);
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_product_aggregate CASCADE;")
