"""手动执行未应用的 schema 变更（stamp 前确保 DB 状态正确）"""
from sqlalchemy import text

from fastapi_app.core.database import get_sync_engine

eng = get_sync_engine()
conn = eng.connect()

ddl_statements = [
    # add_missing_perf_idx: 3 个索引（CONCURRENTLY 不能在事务中，所以用普通 CREATE）
    ('idx_stockout_order_stockin', """
        CREATE INDEX IF NOT EXISTS idx_stockout_order_stockin
        ON stock_out (order_id, stockin_id) WHERE stockin_id IS NOT NULL
    """),
    ('idx_inventory_log_product_time', """
        CREATE INDEX IF NOT EXISTS idx_inventory_log_product_time
        ON inventory_log (product_id, change_date DESC)
    """),
    ('idx_order_date_id_desc', """
        CREATE INDEX IF NOT EXISTS idx_order_date_id_desc
        ON "order" (order_date DESC, id DESC) WHERE is_deleted IS NOT TRUE
    """),
    # add_pp_composite_idx: 3 个索引
    ('idx_ppl_month_customer', """
        CREATE INDEX IF NOT EXISTS idx_ppl_month_customer
        ON purchase_plans (plan_month, customer_id)
    """),
    ('idx_ppl_customer_name', """
        CREATE INDEX IF NOT EXISTS idx_ppl_customer_name
        ON purchase_plans (customer_name)
    """),
    ('idx_ppd_product_name', """
        CREATE INDEX IF NOT EXISTS idx_ppd_product_name
        ON purchase_plan_details (product_name)
    """),
    # add_updated_at: 触发器函数（如果不存在）
    ('trigger_set_updated_at fn', """
        CREATE OR REPLACE FUNCTION trigger_set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """),
    # a8f3c2d1e5b7: 缺失的索引
    ('idx_purchase_order_source_order_id', """
        CREATE INDEX IF NOT EXISTS idx_purchase_order_source_order_id
        ON purchase_order (source_order_id)
    """),
]

for name, ddl in ddl_statements:
    try:
        conn.execute(text(ddl))
        conn.commit()
        print(f'OK  | {name}')
    except Exception as e:
        conn.rollback()
        print(f'ERR | {name}: {e}')

conn.close()
