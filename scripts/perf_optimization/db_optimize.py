#!/usr/bin/env python3
"""
数据库性能优化 - 索引添加 + 查询重写 + 配置优化

运行: python scripts/perf_optimization/db_optimize.py [--apply]
  不带 --apply: 仅输出将要执行的SQL（干跑模式）
  带 --apply: 实际执行
"""
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from fastapi_app.core.config import settings

# ==================== 索引优化 ====================
INDEXES = [
    # 订单表 - 覆盖20K数据量的常见查询模式
    {"name":"idx_order_not_deleted_date","table":"\"order\"","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_not_deleted_date ON \"order\" (order_date DESC) WHERE is_deleted IS NOT TRUE","reason":"软删除过滤+日期排序分页，覆盖订单列表最常见查询"},
    {"name":"idx_order_status_not_deleted","table":"\"order\"","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_status_not_deleted ON \"order\" (status, order_date DESC) WHERE is_deleted IS NOT TRUE","reason":"状态筛选+日期排序，覆盖订单筛选查询"},
    {"name":"idx_order_customer_not_deleted","table":"\"order\"","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_customer_not_deleted ON \"order\" (customer, order_date DESC) WHERE is_deleted IS NOT TRUE","reason":"客户筛选+日期排序"},
    {"name":"idx_order_product_not_deleted","table":"\"order\"","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_product_not_deleted ON \"order\" (product_id, order_date DESC) WHERE is_deleted IS NOT TRUE","reason":"产品筛选+日期排序"},

    # 入库表
    {"name":"idx_stockin_date_desc","table":"stock_in","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockin_date_desc ON stock_in (stockin_date DESC)","reason":"入库列表按日期倒序分页"},
    {"name":"idx_stockin_product_date","table":"stock_in","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockin_product_date ON stock_in (product_id, stockin_date DESC)","reason":"按产品筛选入库记录"},

    # 出库表
    {"name":"idx_stockout_date_desc","table":"stock_out","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_date_desc ON stock_out (stockout_date DESC)","reason":"出库列表按日期倒序分页"},
    {"name":"idx_stockout_order_id","table":"stock_out","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_order_id ON stock_out (order_id) WHERE order_id IS NOT NULL","reason":"订单关联出库记录查询"},
    {"name":"idx_stockout_product_date","table":"stock_out","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stockout_product_date ON stock_out (product_id, stockout_date DESC)","reason":"按产品筛选出库记录"},

    # 产品表
    {"name":"idx_product_name_trgm","table":"product","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_name_trgm ON product USING gin (name gin_trgm_ops)","reason":"产品名模糊查询走GIN索引(需pg_trgm扩展)"},
    {"name":"idx_product_active","table":"product","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_product_active ON product (name) WHERE is_active IS NOT FALSE","reason":"活跃产品列表查询"},

    # 采购计划明细
    {"name":"idx_ppd_plan_date_desc","table":"purchase_plan_details","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppd_plan_date_desc ON purchase_plan_details (plan_date DESC)","reason":"采购明细按日期倒序分页"},
    {"name":"idx_ppd_product_id","table":"purchase_plan_details","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppd_product_id ON purchase_plan_details (product_id)","reason":"按产品筛选采购明细"},
    {"name":"idx_ppd_plan_id_date","table":"purchase_plan_details","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ppd_plan_id_date ON purchase_plan_details (plan_id, plan_date DESC)","reason":"按计划ID+日期筛选"},

    # 客户表
    {"name":"idx_customer_active","table":"customer","sql":"CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_customer_active ON customer (name) WHERE status = 'active'","reason":"活跃客户列表"},
]

# ==================== PostgreSQL 配置优化建议 ====================
PG_CONFIG_RECOMMENDATIONS = """
-- PostgreSQL 性能配置建议 (postgresql.conf)
-- 适用于 20K+ 数据量、并发50+ 场景

-- 连接池
shared_buffers = '256MB'          -- 建议为物理内存的 25%
work_mem = '16MB'                 -- 排序/哈希操作内存
maintenance_work_mem = '128MB'    -- VACUUM/CREATE INDEX 内存

-- 查询规划
effective_cache_size = '768MB'    -- 建议为物理内存的 75%
random_page_cost = 1.1            -- SSD环境降低随机页成本
default_statistics_target = 200   -- 提高统计信息精度

-- WAL/检查点
wal_buffers = '16MB'
min_wal_size = '80MB'
max_wal_size = '1GB'
checkpoint_completion_target = 0.9

-- 并行查询 (4核+)
max_parallel_workers_per_gather = 2
max_parallel_workers = 4

-- 查询缓存 (pg_prewarm扩展)
-- shared_preload_libraries = 'pg_prewarm,pg_stat_statements'
-- pg_prewarm.autoprewarm = true

-- 自动清理
autovacuum_max_workers = 3
autovacuum_naptime = '30s'
log_autovacuum_min_duration = '500ms'
"""

# ==================== 查询重写建议 ====================
QUERY_REWRITE_TIPS = """
=== 查询重写建议 ===

1. [COUNT优化] 避免 SELECT COUNT(*) 做总数统计
   改用: 使用 approximate count via pg_class.reltuples
   SELECT reltuples::bigint FROM pg_class WHERE relname = 'order';

2. [LIKE优化] 避免 customer LIKE '%keyword%' 全表扫描
   改用: pg_trgm GIN索引 + customer ILIKE 'keyword%' (前缀匹配走索引)
   或: 全文搜索

3. [JOIN优化] 避免 joinedload 导致的笛卡尔积
   改用: selectinload 对一对多, joinedload 对多对一
   当前 order_service.get_orders 使用了 selectinload(Order.order_stockouts)
   当出库记录多时改用: subqueryload 或分步查询

4. [分页优化] OFFSET 深翻页性能问题
   当 OFFSET > 10000 时，改用 keyset pagination:
   WHERE order_date < :last_date ORDER BY order_date DESC LIMIT 50
   (无需计算和跳过前N行)

5. [批量查询] 避免 N+1 问题
   使用 contains_eager + 预加载替代循环中单条查询
"""

def main():
    import psycopg
    apply = "--apply" in sys.argv
    url = settings.ASYNC_DATABASE_URL.replace("+asyncpg", "+psycopg")

    print("=" * 80)
    print("  ERP 数据库性能优化")
    print(f"  模式: {'执行' if apply else '干跑(仅输出SQL)'}")
    print("=" * 80)

    print(f"\n--- 索引优化 ({len(INDEXES)} 个) ---\n")
    conn = psycopg.connect(url, autocommit=True)
    try:
        with conn.cursor() as cur:
            # 确保 pg_trgm 扩展
            if apply:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                print("  [OK] pg_trgm 扩展已确保\n")

            for idx in INDEXES:
                cur.execute("SELECT 1 FROM pg_indexes WHERE indexname=%s AND schemaname='public'", (idx["name"],))
                exists = cur.fetchone()
                if exists:
                    print(f"  [跳过] {idx['name']} 已存在")
                    continue
                print(f"  {idx['name']}: {idx['reason']}")
                print(f"    SQL: {idx['sql'][:100]}...")
                if apply:
                    try:
                        cur.execute(idx["sql"])
                        print("    [OK] 创建成功")
                    except Exception as e:
                        print(f"    [错误] {e}")
                else:
                    print("    [干跑] 未执行")
    finally:
        conn.close()

    print("\n" + PG_CONFIG_RECOMMENDATIONS)
    print(QUERY_REWRITE_TIPS)

    if not apply:
        print("\n提示: 添加 --apply 参数执行索引创建")

if __name__ == "__main__":
    main()
