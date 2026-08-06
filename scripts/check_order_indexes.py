"""查询 order 表索引使用统计（pg_stat_user_indexes）并输出报告。"""
import asyncio
import csv
import os
from pathlib import Path

import asyncpg


async def main():
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    user = os.getenv("DB_USER", "erp_app")
    password = os.getenv("DB_PASSWORD", "110110")
    database = os.getenv("DB_NAME", "erp_system")

    conn = await asyncpg.connect(
        host=host, port=port, user=user, password=password, database=database
    )
    try:
        rows = await conn.fetch(
            """
            SELECT
                i.indexrelname AS index_name,
                i.idx_scan,
                i.idx_tup_read,
                i.idx_tup_fetch,
                pg_size_pretty(pg_relation_size(i.indexrelid)) AS index_size,
                array_to_string(array_agg(a.attname ORDER BY x.n), ', ') AS columns
            FROM pg_stat_user_indexes i
            JOIN pg_index idx ON idx.indexrelid = i.indexrelid
            JOIN pg_class c ON c.oid = idx.indrelid
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(idx.indkey)
            JOIN generate_subscripts(idx.indkey, 1) AS x(n) ON a.attnum = idx.indkey[x.n]
            WHERE i.relname = 'order'
            GROUP BY i.indexrelid, i.indexrelname, i.idx_scan, i.idx_tup_read, i.idx_tup_fetch
            ORDER BY i.idx_scan ASC, i.indexrelname ASC;
            """
        )
    finally:
        await conn.close()

    out_path = Path("d:/erp_system/scripts/order_index_usage.csv")
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["index_name", "idx_scan", "idx_tup_read", "idx_tup_fetch", "index_size", "columns"],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))

    print(f"报告已写入 {out_path}，共 {len(rows)} 个索引")
    zero_use = [r["index_name"] for r in rows if r["idx_scan"] == 0]
    print(f"零使用索引数量: {len(zero_use)}")
    for name in zero_use:
        print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(main())
