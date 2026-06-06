-- ============================================================
-- pg_stat_statements 扩展启用与慢查询监控配置
-- 在 PostgreSQL 中执行（需要 superuser 权限）
-- ============================================================

-- 1. 启用 pg_stat_statements 扩展
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- 2. 确保 postgresql.conf 中有以下配置（需重启 PostgreSQL）
-- 在 postgresql.auto.conf 中设置（无需手动编辑 postgresql.conf）：
-- ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
-- ALTER SYSTEM SET pg_stat_statements.max = 10000;
-- ALTER SYSTEM SET pg_stat_statements.track = 'top';       -- 仅追踪顶层查询
-- ALTER SYSTEM SET pg_stat_statements.track_utility = off;  -- 不追踪工具命令（如 VACUUM）
-- ALTER SYSTEM SET pg_stat_statements.save = on;            -- 重启后保留统计

-- 3. 查询 Top 20 慢查询（按总执行时间排序）
-- 平均执行时间超过阈值（OLTP: 0.1s, 报表: 1s）的查询
SELECT
  queryid,
  calls,
  round(total_exec_time::numeric, 2) AS total_ms,
  round(mean_exec_time::numeric, 2) AS avg_ms,
  round(max_exec_time::numeric, 2) AS max_ms,
  round((100 * total_exec_time / SUM(total_exec_time) OVER ())::numeric, 2) AS pct_total,
  query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'erp_system')
ORDER BY total_exec_time DESC
LIMIT 20;

-- 4. 识别未使用索引（索引存在但扫描次数为0）
SELECT
  schemaname || '.' || relname AS table_name,
  indexrelname AS index_name,
  idx_scan AS index_scans,
  pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
  'DROP INDEX CONCURRENTLY ' || indexrelname || ';' AS drop_cmd
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND indexrelname NOT LIKE '%_pkey'
  AND indexrelname NOT LIKE '%_trgm'       -- GIN trgm 索引不适用 idx_scan 统计
  AND schemaname = 'public'
ORDER BY pg_relation_size(indexrelid) DESC;

-- 5. 识别冗余索引（同表同列的索引，较小者可删除）
SELECT
  pg_size_pretty(pg_relation_size(a.indexrelid)) AS size_a,
  a.indexrelname AS index_a,
  pg_size_pretty(pg_relation_size(b.indexrelid)) AS size_b,
  b.indexrelname AS index_b,
  a.relname AS table_name
FROM pg_stat_user_indexes a
JOIN pg_stat_user_indexes b ON a.relid = b.relid AND a.indexrelid < b.indexrelid
WHERE a.schemaname = 'public'
  AND pg_relation_size(a.indexrelid) > pg_relation_size(b.indexrelid)
ORDER BY pg_relation_size(a.indexrelid) - pg_relation_size(b.indexrelid) DESC;

-- 6. 重置统计（在基准测试前执行）
-- SELECT pg_stat_statements_reset();
