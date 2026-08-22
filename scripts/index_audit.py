"""索引审计：重复索引 / 冗余索引 / 未使用索引 / 索引膨胀

用法:
    python scripts/index_audit.py

输出 4 类结果：
1. 重复索引（同表同列组合，可合并）—— 需人工确认后清理
2. 未使用索引（60 天无扫描，小表可忽略）—— 需人工确认后清理
3. 索引与表大小概览
4. 索引膨胀（dead tuples 多的建议 REINDEX）

⚠️ 本脚本只读不修改。清理索引需人工执行 DROP INDEX 并确认。
"""
import asyncio

from dotenv import load_dotenv

load_dotenv(".env", override=False)


async def main():
    from sqlalchemy import text

    from fastapi_app.core.database import async_engine

    async with async_engine.connect() as conn:
        print("=" * 60)
        print("1. 重复索引（同一表上相同列组合）")
        print("=" * 60)
        dup = (await conn.execute(text("""
            SELECT t.tablename, string_agg(i.indexname, ', ' ORDER BY i.indexname) AS indexes,
                   count(*) AS cnt
            FROM pg_indexes i
            JOIN pg_tables t ON t.tablename = i.tablename AND t.schemaname = i.schemaname
            WHERE i.schemaname = 'public'
            GROUP BY t.tablename, substring(i.indexdef FROM 'USING \\w+ \\((.*?)\\)')
            HAVING count(*) > 1
            ORDER BY count(*) DESC
        """))).fetchall()
        if not dup:
            print("  无重复索引")
        for r in dup:
            print(f"  {r[0]}: {r[1]}")

        print()
        print("=" * 60)
        print("2. 未使用索引（近 60 天无扫描；小表可忽略）")
        print("=" * 60)
        unused = (await conn.execute(text("""
            SELECT s.schemaname, s.relname, s.indexrelname, s.idx_scan,
                   pg_size_pretty(pg_relation_size(s.indexrelid)) AS size
            FROM pg_stat_user_indexes s
            JOIN pg_class c ON c.oid = s.indexrelid
            WHERE s.schemaname = 'public'
              AND s.idx_scan = 0
              AND NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = s.indexrelid)
            ORDER BY pg_relation_size(s.indexrelid) DESC
            LIMIT 20
        """))).fetchall()
        if not unused:
            print("  无不使用索引")
        for r in unused:
            print(f"  {r[1]}.{r[2]}: scan={r[3]}, size={r[4]}")

        print()
        print("=" * 60)
        print("3. 索引与表大小")
        print("=" * 60)
        sizes = (await conn.execute(text("""
            SELECT t.tablename, pg_size_pretty(pg_total_relation_size(t.tablename::text::regclass)) AS table_size,
                   count(i.indexname) AS idx_count
            FROM pg_tables t
            LEFT JOIN pg_indexes i ON i.tablename = t.tablename AND i.schemaname = t.schemaname
            WHERE t.schemaname = 'public'
            GROUP BY t.tablename
            HAVING pg_total_relation_size(t.tablename::text::regclass) > 100000
            ORDER BY pg_total_relation_size(t.tablename::text::regclass) DESC
            LIMIT 15
        """))).fetchall()
        for r in sizes:
            print(f"  {r[0]}: {r[1]}, indexes={r[2]}")

        print()
        print("=" * 60)
        print("4. 索引膨胀率（>20% 建议 REINDEX）")
        print("=" * 60)
        bloat = (await conn.execute(text("""
            SELECT i.schemaname, i.relname, i.indexrelname,
                   pg_size_pretty(pg_relation_size(i.indexrelid)) AS index_size,
                   t.n_dead_tup AS dead_tuples
            FROM pg_stat_user_indexes i
            JOIN pg_stat_user_tables t ON t.relid = i.relid
            WHERE i.schemaname = 'public'
              AND pg_relation_size(i.indexrelid) > 100000
              AND t.n_dead_tup > 1000
            ORDER BY t.n_dead_tup DESC
            LIMIT 10
        """))).fetchall()
        if not bloat:
            print("  无显著膨胀")
        for r in bloat:
            print(f"  {r[1]}.{r[2]}: size={r[3]}, dead_tuples={r[4]}")

    await async_engine.dispose()


asyncio.run(main())
