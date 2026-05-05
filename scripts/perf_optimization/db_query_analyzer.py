#!/usr/bin/env python3
"""
数据库查询分析脚本

功能：
1. 采集所有关键查询的执行计划
2. 识别缺失索引、顺序扫描、高成本查询
3. 分析表统计信息和索引使用率
4. 生成优化建议

运行方式:
  python scripts/perf_optimization/db_query_analyzer.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from fastapi_app.core.config import settings


CRITICAL_QUERIES = [
    {
        "name": "订单列表(分页+筛选)",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT o.id, o.order_no, o.customer, o.order_date, o.quantity, o.status,
                   o.order_type, o.country, p.id as prod_id, p.name as prod_name
            FROM "order" o
            LEFT JOIN product p ON o.product_id = p.id
            WHERE o.is_deleted IS NOT TRUE
            ORDER BY o.order_date DESC
            LIMIT 50 OFFSET 0
        """,
        "table": "order",
    },
    {
        "name": "订单客户筛选",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT * FROM "order"
            WHERE is_deleted IS NOT TRUE AND customer LIKE '%测试%'
            ORDER BY order_date DESC
            LIMIT 50 OFFSET 0
        """,
        "table": "order",
    },
    {
        "name": "库存列表(分页)",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT p.id, p.name, p.barcode, p.current_stock, p.initial_stock
            FROM product p
            ORDER BY p.name
            LIMIT 50 OFFSET 0
        """,
        "table": "product",
    },
    {
        "name": "入库列表(分页)",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT si.* FROM stock_in si
            ORDER BY si.stockin_date DESC
            LIMIT 50 OFFSET 0
        """,
        "table": "stock_in",
    },
    {
        "name": "出库列表(分页)",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT so.* FROM stock_out so
            ORDER BY so.stockout_date DESC
            LIMIT 50 OFFSET 0
        """,
        "table": "stock_out",
    },
    {
        "name": "采购计划明细(分页)",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT pd.* FROM purchase_plan_details pd
            ORDER BY pd.plan_date DESC
            LIMIT 50 OFFSET 0
        """,
        "table": "purchase_plan_details",
    },
    {
        "name": "订单总数统计",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT COUNT(*) FROM "order" WHERE is_deleted IS NOT TRUE
        """,
        "table": "order",
    },
    {
        "name": "订单按状态分组统计",
        "sql": """
            EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
            SELECT status, COUNT(*) FROM "order"
            WHERE is_deleted IS NOT TRUE
            GROUP BY status
        """,
        "table": "order",
    },
]

TABLE_STATS_QUERY = """
    SELECT
        schemaname,
        relname as table_name,
        n_live_tup as row_count,
        n_dead_tup as dead_tuples,
        last_vacuum,
        last_autovacuum,
        last_analyze,
        last_autoanalyze
    FROM pg_stat_user_tables
    ORDER BY n_live_tup DESC
"""

UNUSED_INDEXES_QUERY = """
    SELECT
        schemaname,
        relname as table_name,
        indexrelname as index_name,
        idx_scan as index_scans,
        idx_tup_read,
        idx_tup_fetch,
        pg_size_pretty(pg_relation_size(indexrelid)) as index_size
    FROM pg_stat_user_indexes
    WHERE idx_scan = 0 AND indexrelname NOT LIKE '%_pkey'
    ORDER BY pg_relation_size(indexrelid) DESC
    LIMIT 20
"""

SEQ_SCAN_QUERY = """
    SELECT
        schemaname,
        relname as table_name,
        seq_scan,
        idx_scan,
        CASE WHEN idx_scan + seq_scan > 0
            THEN round(seq_scan::numeric / (idx_scan + seq_scan) * 100, 2)
            ELSE 0
        END as seq_scan_pct,
        n_live_tup as row_count
    FROM pg_stat_user_tables
    WHERE seq_scan > 0 AND n_live_tup > 1000
    ORDER BY seq_scan DESC
    LIMIT 15
"""

MISSING_INDEX_QUERY = """
    SELECT
        schemaname,
        relname as table_name,
        attname as column_name,
        n_distinct,
        correlation
    FROM pg_stats
    WHERE schemaname = 'public'
      AND n_distinct > 100
      AND abs(correlation) < 0.1
    ORDER BY n_distinct DESC
    LIMIT 20
"""


def _get_sync_url() -> str:
    url = settings.ASYNC_DATABASE_URL.replace("+asyncpg", "+psycopg")
    return url


async def run_analysis():
    import psycopg

    url = _get_sync_url()
    print("=" * 80)
    print("  ERP 数据库查询分析")
    print(f"  数据库: {url.split('@')[-1] if '@' in url else url}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    results = {
        "timestamp": datetime.now().isoformat(),
        "query_plans": [],
        "table_stats": [],
        "unused_indexes": [],
        "seq_scans": [],
        "missing_index_candidates": [],
        "recommendations": [],
    }

    conn = psycopg.connect(url)
    try:
        # 1. 表统计信息
        print("\n--- 表统计信息 ---")
        with conn.cursor() as cur:
            cur.execute(TABLE_STATS_QUERY)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            for row in rows:
                info = dict(zip(cols, row))
                results["table_stats"].append(info)
                print(
                    f"  {info['table_name']}: {info['row_count']:,} 行, "
                    f"死元组: {info['dead_tuples']:,}"
                )
                if info["dead_tuples"] and info["row_count"] and info["dead_tuples"] > info["row_count"] * 0.1:
                    results["recommendations"].append(
                        f"表 {info['table_name']} 死元组比例过高({info['dead_tuples']}/{info['row_count']})，"
                        f"建议执行 VACUUM ANALYZE"
                    )

        # 2. 未使用的索引
        print("\n--- 未使用的索引 ---")
        with conn.cursor() as cur:
            cur.execute(UNUSED_INDEXES_QUERY)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            for row in rows:
                info = dict(zip(cols, row))
                results["unused_indexes"].append(info)
                print(f"  {info['table_name']}.{info['index_name']}: 扫描次数={info['index_scans']}, 大小={info['index_size']}")

        # 3. 顺序扫描
        print("\n--- 顺序扫描比例 ---")
        with conn.cursor() as cur:
            cur.execute(SEQ_SCAN_QUERY)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            for row in rows:
                info = dict(zip(cols, row))
                results["seq_scans"].append(info)
                print(
                    f"  {info['table_name']}: 顺序扫描={info['seq_scan']}, "
                    f"索引扫描={info['idx_scan']}, "
                    f"顺序扫描比例={info['seq_scan_pct']}%"
                )
                if float(info["seq_scan_pct"]) > 30:
                    results["recommendations"].append(
                        f"表 {info['table_name']} 顺序扫描比例过高({info['seq_scan_pct']}%)，"
                        f"建议添加索引或更新统计信息"
                    )

        # 4. 缺失索引候选
        print("\n--- 缺失索引候选 (高离散度+低相关性) ---")
        with conn.cursor() as cur:
            cur.execute(MISSING_INDEX_QUERY)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            for row in rows:
                info = dict(zip(cols, row))
                results["missing_index_candidates"].append(info)
                print(
                    f"  {info['table_name']}.{info['column_name']}: "
                    f"n_distinct={info['n_distinct']}, correlation={info['correlation']}"
                )

        # 5. 关键查询执行计划
        print("\n--- 关键查询执行计划 ---")
        for q in CRITICAL_QUERIES:
            print(f"\n  [{q['name']}]")
            try:
                with conn.cursor() as cur:
                    cur.execute(q["sql"])
                    plan = cur.fetchone()
                    if plan:
                        plan_json = plan[0]
                        results["query_plans"].append(
                            {"name": q["name"], "table": q["table"], "plan": plan_json}
                        )
                        if isinstance(plan_json, list) and len(plan_json) > 0:
                            top = plan_json[0].get("Plan", {})
                            actual_time = top.get("Actual Total Time", 0)
                            node_type = top.get("Node Type", "")
                            print(f"    执行时间: {actual_time:.2f}ms, 节点类型: {node_type}")

                            if actual_time > 100:
                                results["recommendations"].append(
                                    f"查询 '{q['name']}' 执行时间 {actual_time:.0f}ms 超过100ms阈值，"
                                    f"建议优化或添加索引"
                                )

                            def _check_seq_scan(plan_node: dict, path: str = ""):
                                if plan_node.get("Node Type") == "Seq Scan":
                                    table = plan_node.get("Relation Name", "?")
                                    rows = plan_node.get("Actual Rows", 0)
                                    if rows > 1000:
                                        results["recommendations"].append(
                                            f"查询 '{q['name']}' 存在大表顺序扫描({table}, {rows}行)，"
                                            f"建议添加索引"
                                        )
                                for child in plan_node.get("Plans", []):
                                    _check_seq_scan(child, path + "/" + plan_node.get("Node Type", ""))

                            _check_seq_scan(top)
            except Exception as e:
                print(f"    [错误] {e}")
                results["query_plans"].append({"name": q["name"], "error": str(e)})

    finally:
        conn.close()

    # 6. 输出优化建议
    print("\n" + "=" * 80)
    print("  优化建议")
    print("=" * 80)
    if results["recommendations"]:
        for i, rec in enumerate(results["recommendations"], 1):
            print(f"  {i}. {rec}")
    else:
        print("  无紧急优化建议")

    report_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "tests",
        "performance",
        "reports",
        f"db_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    asyncio.run(run_analysis())
