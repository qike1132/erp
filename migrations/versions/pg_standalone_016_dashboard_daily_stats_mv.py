"""create dashboard daily stats materialized views

Revision ID: pg_standalone_016_dashboard_daily_stats_mv
Revises: pg_standalone_015_pattern_room
Create Date: 2026-07-20

新增仪表盘每日统计物化视图，用于降低仪表盘和日报类聚合查询的 DB 压力：
- mv_daily_order_quantity: 每日订单商品件数
- mv_daily_stockin_quantity: 每日备货数量
- mv_daily_stockout_quantity: 每日出货数量（不含退货）

刷新策略由 Celery beat 每 5 分钟执行 CONCURRENTLY 刷新（需唯一索引支持）。
"""
from alembic import op


revision = 'pg_standalone_016_dashboard_daily_stats_mv'
down_revision = 'pg_standalone_015_pattern_room'
branch_labels = None
depends_on = None


def upgrade():
    # 订单每日件数（order_item 多 SKU 模型）
    op.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_order_quantity AS
    SELECT DATE(o.order_date) AS stat_date,
           COALESCE(SUM(oi.quantity), 0) AS total_quantity,
           COUNT(DISTINCT o.id) AS record_count
    FROM "order" o
    LEFT JOIN order_item oi ON oi.order_id = o.id
    WHERE o.is_deleted IS NOT TRUE
    GROUP BY DATE(o.order_date);
    """)
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_order_quantity_date
    ON mv_daily_order_quantity(stat_date);
    """)

    # 入库每日数量
    op.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_stockin_quantity AS
    SELECT DATE(stockin_date) AS stat_date,
           COALESCE(SUM(quantity), 0) AS total_quantity,
           COUNT(*) AS record_count
    FROM stock_in
    GROUP BY DATE(stockin_date);
    """)
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_stockin_quantity_date
    ON mv_daily_stockin_quantity(stat_date);
    """)

    # 出库每日数量（扣减退货）
    op.execute("""
    CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_stockout_quantity AS
    SELECT DATE(stockout_date) AS stat_date,
           COALESCE(SUM(quantity - returned_quantity), 0) AS total_quantity,
           COUNT(*) AS record_count
    FROM stock_out
    WHERE (quantity - returned_quantity) > 0
    GROUP BY DATE(stockout_date);
    """)
    op.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_daily_stockout_quantity_date
    ON mv_daily_stockout_quantity(stat_date);
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_daily_stockout_quantity CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_daily_stockin_quantity CASCADE;")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_daily_order_quantity CASCADE;")
