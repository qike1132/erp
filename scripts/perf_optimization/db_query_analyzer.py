#!/usr/bin/env python3
"""
数据库查询分析脚本
分析执行计划、缺失索引、顺序扫描比例、死元组。

运行: python scripts/perf_optimization/db_query_analyzer.py
"""
import json
import os
import sys
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)
from fastapi_app.core.config import settings

CRITICAL_QUERIES = [
    {"name":"订单列表分页","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT o.id,o.order_no,o.customer,o.status FROM \"order\" o WHERE o.is_deleted IS NOT TRUE ORDER BY o.order_date DESC LIMIT 50 OFFSET 0","table":"order"},
    {"name":"订单客户LIKE筛选","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT * FROM \"order\" WHERE is_deleted IS NOT TRUE AND customer LIKE '%%测试%%' ORDER BY order_date DESC LIMIT 50","table":"order"},
    {"name":"订单状态分组统计","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT status,COUNT(*) FROM \"order\" WHERE is_deleted IS NOT TRUE GROUP BY status","table":"order"},
    {"name":"库存列表分页","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT p.id,p.name,p.barcode,p.current_stock FROM product p ORDER BY p.name LIMIT 50 OFFSET 0","table":"product"},
    {"name":"入库列表分页","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT si.* FROM stock_in si ORDER BY si.stockin_date DESC LIMIT 50 OFFSET 0","table":"stock_in"},
    {"name":"出库列表分页","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT so.* FROM stock_out so ORDER BY so.stockout_date DESC LIMIT 50 OFFSET 0","table":"stock_out"},
    {"name":"采购计划明细分页","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT pd.* FROM purchase_plan_details pd ORDER BY pd.plan_date DESC LIMIT 50 OFFSET 0","table":"purchase_plan_details"},
    {"name":"订单总数COUNT","sql":"EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT COUNT(*) FROM \"order\" WHERE is_deleted IS NOT TRUE","table":"order"},
]

def run():
    import psycopg
    url = settings.ASYNC_DATABASE_URL.replace("+asyncpg","+psycopg")
    print("="*80)
    print("  ERP 数据库查询分析")
    print("="*80)
    results = {"timestamp":datetime.now().isoformat(),"query_plans":[],"table_stats":[],"recommendations":[]}
    conn = psycopg.connect(url, autocommit=True)
    try:
        with conn.cursor() as cur:
            print("\n--- 表统计信息 ---")
            cur.execute("SELECT relname,n_live_tup,n_dead_tup,last_vacuum,last_autovacuum FROM pg_stat_user_tables ORDER BY n_live_tup DESC")
            for r in cur.fetchall():
                print(f"  {r[0]}: {r[1]:,} 行, 死元组={r[2]:,}")
                results["table_stats"].append({"table":r[0],"rows":r[1],"dead_tuples":r[2]})
                if r[2] and r[1] and r[2] > r[1]*0.1:
                    results["recommendations"].append(f"表 {r[0]} 死元组比例过高，建议 VACUUM ANALYZE")

        with conn.cursor() as cur:
            print("\n--- 顺序扫描比例 (大表) ---")
            cur.execute("SELECT relname,seq_scan,idx_scan,CASE WHEN idx_scan+seq_scan>0 THEN round(seq_scan::numeric/(idx_scan+seq_scan)*100,2) ELSE 0 END as pct,n_live_tup FROM pg_stat_user_tables WHERE seq_scan>0 AND n_live_tup>1000 ORDER BY seq_scan DESC LIMIT 10")
            for r in cur.fetchall():
                print(f"  {r[0]}: seq={r[1]} idx={r[2]} 顺序扫描比例={r[3]}% 行数={r[4]}")
                if float(r[3])>30: results["recommendations"].append(f"表 {r[0]} 顺序扫描比例 {r[3]}% 过高，建议添加索引")

        with conn.cursor() as cur:
            print("\n--- 未使用索引 ---")
            cur.execute("SELECT relname,indexrelname,idx_scan,pg_size_pretty(pg_relation_size(indexrelid)) FROM pg_stat_user_indexes WHERE idx_scan=0 AND indexrelname NOT LIKE '%%_pkey' ORDER BY pg_relation_size(indexrelid) DESC LIMIT 10")
            for r in cur.fetchall(): print(f"  {r[0]}.{r[1]}: 扫描={r[2]} 大小={r[3]}")

        with conn.cursor() as cur:
            print("\n--- 高离散度低相关性列(索引候选) ---")
            cur.execute("SELECT relname,attname,n_distinct,correlation FROM pg_stats WHERE schemaname='public' AND n_distinct>100 AND abs(correlation)<0.1 ORDER BY n_distinct DESC LIMIT 15")
            for r in cur.fetchall(): print(f"  {r[0]}.{r[1]}: n_distinct={r[2]} correlation={r[3]}")

        print("\n--- 关键查询执行计划 ---")
        for q in CRITICAL_QUERIES:
            print(f"\n  [{q['name']}]")
            try:
                with conn.cursor() as cur:
                    cur.execute(q["sql"])
                    plan = cur.fetchone()
                    if plan:
                        p = plan[0]
                        results["query_plans"].append({"name":q["name"],"plan":p})
                        if isinstance(p,list) and p:
                            top = p[0].get("Plan",{})
                            ms = top.get("Actual Total Time",0)
                            print(f"    执行时间: {ms:.2f}ms")
                            if ms>100: results["recommendations"].append(f"查询 '{q['name']}' 耗时 {ms:.0f}ms 超阈值")
            except Exception as e:
                print(f"    [错误] {e}")
    finally:
        conn.close()

    print("\n"+"="*80)
    print("  优化建议")
    print("="*80)
    for i,r in enumerate(results["recommendations"],1): print(f"  {i}. {r}")
    if not results["recommendations"]: print("  无紧急建议")

    path = os.path.join(project_root,"tests","performance","reports",f"db_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,"w",encoding="utf-8") as f: json.dump(results,f,ensure_ascii=False,indent=2,default=str)
    print(f"\n报告: {path}")

if __name__=="__main__": run()
