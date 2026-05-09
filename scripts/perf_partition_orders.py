"""
订单表按年度声明式分区迁移

将 orders 表转为按 order_date 年度范围分区，
适用于订单量超过百万的场景。

注意：
- 此迁移会锁表，需在维护窗口执行
- 需先创建分区表，再迁移数据
- 执行前需确保有完整备份

用法:
  python scripts/perf_partition_orders.py --dry-run  # 预览
  python scripts/perf_partition_orders.py --execute   # 执行
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from fastapi_app.core.database import _init_async_engine, _AsyncSessionLocal

PARTITION_YEARS = [2024, 2025, 2026, 2027, 2028]


async def create_partitions(session, dry_run=True):
    for year in PARTITION_YEARS:
        start = f"{year}-01-01"
        end = f"{year + 1}-01-01"
        ddl = f"""
            CREATE TABLE IF NOT EXISTS orders_{year}
            PARTITION OF orders
            FOR VALUES FROM ('{start}') TO ('{end}')
        """
        if dry_run:
            print(f"  [DRY-RUN] {ddl.strip()}")
        else:
            t0 = time.perf_counter()
            await session.execute(text(ddl))
            await session.commit()
            print(f"  ✓ orders_{year} ({(time.perf_counter()-t0)*1000:.0f}ms)")

    default_ddl = """
        CREATE TABLE IF NOT EXISTS orders_default
        PARTITION OF orders DEFAULT
    """
    if dry_run:
        print(f"  [DRY-RUN] {default_ddl.strip()}")
    else:
        await session.execute(text(default_ddl))
        await session.commit()
        print("  ✓ orders_default")


async def verify_partitions(session):
    result = await session.execute(text("""
        SELECT inhrelid::regclass AS partition,
               pg_get_expr(pt.relpartbound, pt.oid) AS boundary
        FROM pg_inherits i
        JOIN pg_class pt ON pt.oid = i.inhrelid
        WHERE i.inhparent = 'orders'::regclass
        ORDER BY partition
    """))
    rows = result.fetchall()
    if not rows:
        print("  未找到分区（orders 表可能尚未分区）")
    for row in rows:
        print(f"  {row.partition}: {row.boundary}")


async def main():
    parser = argparse.ArgumentParser(description="订单表分区迁移")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true", help="实际执行（非预览）")
    args = parser.parse_args()

    dry_run = not args.execute

    _init_async_engine()
    print(f"订单表分区迁移 - {'预览模式' if dry_run else '执行模式'}")

    async with _AsyncSessionLocal() as session:
        print("\n=== 创建年度分区 ===")
        await create_partitions(session, dry_run)

        print("\n=== 验证分区 ===")
        await verify_partitions(session)

        if not dry_run:
            print("\n=== 分区统计 ===")
            result = await session.execute(text("""
                SELECT relname, n_live_tup
                FROM pg_stat_user_tables
                WHERE relname LIKE 'orders_%'
                ORDER BY relname
            """))
            for row in result.fetchall():
                print(f"  {row.relname}: {row.n_live_tup} 行")


if __name__ == "__main__":
    asyncio.run(main())
