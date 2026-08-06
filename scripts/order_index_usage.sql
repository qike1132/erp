-- 查询 order 表索引使用统计，识别零使用/低使用索引
-- 执行方式：在 PostgreSQL 中运行（如 psql、DBeaver、pgAdmin）
-- 注意：pg_stat_user_indexes 自上次统计重置后累计，生产环境建议观察至少 7 天

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

-- 查看 order 表上所有索引的定义（含部分索引过滤条件）
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'order'
ORDER BY indexname;
