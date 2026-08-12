"""诊断 DB 中各 head 迁移对应的 schema 元素"""
from fastapi_app.core.database import get_sync_engine
from sqlalchemy import text

eng = get_sync_engine()
conn = eng.connect()

checks = [
    # 1. add_country_table: creates 'country' table
    ('add_country_table', "country table",
     "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='country'"),
    # 2. add_missing_perf_idx: creates 3 indexes (CONCURRENTLY IF NOT EXISTS)
    ('add_missing_perf_idx', 'idx_stockout_order_stockin',
     "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_stockout_order_stockin'"),
    ('add_missing_perf_idx', 'idx_inventory_log_product_time',
     "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_inventory_log_product_time'"),
    ('add_missing_perf_idx', 'idx_order_date_id_desc',
     "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_order_date_id_desc'"),
    # 3. add_order_batch_fields: columns + table + inserts
    ('add_order_batch_fields', 'order.batch_completed_at',
     "SELECT 1 FROM information_schema.columns WHERE table_name='order' AND column_name='batch_completed_at'"),
    ('add_order_batch_fields', 'order_batch_audit_log table',
     "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='order_batch_audit_log'"),
    ('add_order_batch_fields', 'order_batch_manage permission',
     "SELECT 1 FROM permission WHERE code='order_batch_manage'"),
    # 4. add_order_type_country_stockin: stock_in columns
    ('add_order_type_country_stockin', 'stock_in.order_type',
     "SELECT 1 FROM information_schema.columns WHERE table_name='stock_in' AND column_name='order_type'"),
    ('add_order_type_country_stockin', 'stock_in.country',
     "SELECT 1 FROM information_schema.columns WHERE table_name='stock_in' AND column_name='country'"),
    # 5. add_pp_composite_idx: 3 indexes
    ('add_pp_composite_idx', 'idx_ppl_month_customer',
     "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_ppl_month_customer'"),
    ('add_pp_composite_idx', 'idx_ppl_customer_name',
     "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_ppl_customer_name'"),
    ('add_pp_composite_idx', 'idx_ppd_product_name',
     "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_ppd_product_name'"),
    # 6. add_stock_return: column + table
    ('add_stock_return', 'stock_out.returned_quantity',
     "SELECT 1 FROM information_schema.columns WHERE table_name='stock_out' AND column_name='returned_quantity'"),
    ('add_stock_return', 'stock_return table',
     "SELECT 1 FROM pg_tables WHERE schemaname='public' AND tablename='stock_return'"),
    # 7. add_updated_at: triggers + columns
    ('add_updated_at', 'order.updated_at',
     "SELECT 1 FROM information_schema.columns WHERE table_name='order' AND column_name='updated_at'"),
    ('add_updated_at', 'product.updated_at',
     "SELECT 1 FROM information_schema.columns WHERE table_name='product' AND column_name='updated_at'"),
    ('add_updated_at', 'set_updated_at trigger fn',
     "SELECT 1 FROM pg_proc WHERE proname='trigger_set_updated_at'"),
    # 8. a8f3c2d1e5b7: order.status nullable + index
    ('a8f3c2d1e5b7', 'order.status is nullable',
     "SELECT 1 FROM information_schema.columns WHERE table_name='order' AND column_name='status' AND is_nullable='YES'"),
    ('a8f3c2d1e5b7', 'idx_purchase_order_source_order_id',
     "SELECT 1 FROM pg_indexes WHERE schemaname='public' AND indexname='idx_purchase_order_source_order_id'"),
    # 9. merge_all_heads: noop
    ('merge_all_heads', 'noop', None),
    # 10. pg_standalone_003: perf indexes
    ('pg_standalone_003', 'noop (perf indexes)', None),
]

current = ''
print(f'{"STATE":<4} | {"HEAD":<28} | {"ELEMENT":<35}')
print('-' * 90)
for head, name, sql in checks:
    if head != current:
        current = head
    if sql is None:
        # noop migration
        print(f'{"N/A":<4} | {head:<28} | {name:<35} (noop, no DB check needed)')
        continue
    try:
        result = conn.execute(text(sql)).fetchone()
        state = 'YES' if result else 'NO '
        print(f'{state:<4} | {head:<28} | {name:<35}')
    except Exception as e:
        print(f'ERR | {head:<28} | {name:<35} | {e}')

conn.close()
