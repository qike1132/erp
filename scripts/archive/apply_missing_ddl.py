"""手动执行未应用的 schema 变更（stamp 前确保 DB 状态正确）

⚠️ 归档脚本，**模块级即连接数据库并逐条 commit DDL**。为避免「import 即写生产」
在测试收集、工具链导入或误跑时触发，必须先显式传 ``--allow-deprecated-script``；
无该参数时在建立任何连接之前直接退出（2026-11-03 审查 S12 / 历史 High ⑤ 残留）。

正常迁移请用 ``python -m alembic -c migrations/alembic.ini upgrade head``，
本脚本仅用于「stamp 前补齐 DB 已有但迁移未记录的索引」这一历史场景。
"""
import sys

if '--allow-deprecated-script' not in sys.argv:
    sys.exit(
        '拒绝执行：scripts/archive/apply_missing_ddl.py 会在 import 时直接对 '
        'DATABASE_URL 指向的库执行 CREATE INDEX / CREATE FUNCTION。\n'
        '这是归档脚本，正常迁移请用：python -m alembic -c migrations/alembic.ini upgrade head\n'
        '确认要在当前 DATABASE_URL 上执行时，请显式追加 --allow-deprecated-script。'
    )

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
