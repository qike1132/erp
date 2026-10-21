"""
性能优化索引迁移 - 为大数据量表添加覆盖索引和复合索引

运行:
  alembic upgrade head
  # 或单独执行
  python scripts/perf_add_indexes.py
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from fastapi_app.core.database import _AsyncSessionLocal, _init_async_engine

INDEXES = [
    ("orders", "idx_perf_order_status_date_covering", """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_status_date_covering
        ON orders (status, order_date DESC, id)
        WHERE is_deleted = false
    """),
    ("orders", "idx_perf_order_customer_date", """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_order_customer_date
        ON orders (customer_name, order_date DESC)
        WHERE is_deleted = false
    """),
    ("stock_in", "idx_perf_stockin_product_date", """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockin_product_date
        ON stock_in (product_id, date DESC)
    """),
    ("stock_out", "idx_perf_stockout_product_date", """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_stockout_product_date
        ON stock_out (product_id, date DESC)
    """),
    ("purchase_order", "idx_perf_po_status_date_covering", """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_po_status_date_covering
        ON purchase_order (status, order_date DESC, id)
    """),
    ("purchase_order_item", "idx_perf_poi_order_include", """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_poi_order_include
        ON purchase_order_item (order_id)
        INCLUDE (material_name, quantity, unit_price)
    """),
    ("product", "idx_perf_product_name_date", """
        CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_perf_product_name_date
        ON product (create_time DESC, id)
    """),
]


async def main():
    # 危险写护栏（审查 H13）：CREATE INDEX CONCURRENTLY 是直接落生产库的 DDL。
    from _prod_write_guard import require_prod_write_consent
    require_prod_write_consent(
        '创建性能索引（CREATE INDEX CONCURRENTLY ×7）',
        hint='DDL 写生产库；CONCURRENTLY 不锁写但仍占 IO，建议低峰执行。',
    )
    _init_async_engine()
    async with _AsyncSessionLocal() as session:
        for _table, idx_name, ddl in INDEXES:
            t0 = time.perf_counter()
            try:
                await session.execute(text(ddl))
                await session.commit()
                elapsed = (time.perf_counter() - t0) * 1000
                print(f"✓ {idx_name} ({elapsed:.0f}ms)")
            except Exception as e:
                await session.rollback()
                if "already exists" in str(e):
                    print(f"= {idx_name} (已存在)")
                else:
                    print(f"✗ {idx_name}: {e}")

        print("\n验证索引:")
        for _table, idx_name, _ in INDEXES:
            r = await session.execute(text("""
                SELECT indexname, idx_scan, idx_tup_read, idx_tup_fetch
                FROM pg_stat_user_indexes
                WHERE indexname = :name
            """), {"name": idx_name})
            row = r.first()
            if row:
                print(f"  {row.indexname}: scans={row.idx_scan}, read={row.idx_tup_read}, fetch={row.idx_tup_fetch}")
            else:
                print(f"  {idx_name}: 未找到")


if __name__ == "__main__":
    asyncio.run(main())
