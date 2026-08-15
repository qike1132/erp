-- ============================================================
-- 来料登记模块性能优化 DDL
-- 
-- 用途：为 material_registration 表的模糊搜索字段创建 pg_trgm 索引
-- 效果：supplier_name / purchase_order_no 的 ILIKE '%keyword%' 查询
--       从全表扫描变为 GIN 索引扫描，查询时间可缩短 10-100 倍
--
-- 前置条件：需要安装 pg_trgm 扩展
--   CREATE EXTENSION IF NOT EXISTS pg_trgm;
--
-- 执行方式：
--   psql -U <user> -d <database> -f apply_material_trgm_indexes.sql
-- ============================================================

-- 1. 确保 pg_trgm 扩展已启用
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 创建 supplier_name 的 trigram GIN 索引（加速供应商名称模糊搜索）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_supplier_trgm
    ON material_registration USING gin (supplier_name gin_trgm_ops);

-- 3. 创建 purchase_order_no 的 trigram GIN 索引（加速订单号模糊搜索）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_material_reg_order_no_trgm
    ON material_registration USING gin (purchase_order_no gin_trgm_ops);

-- 4. 创建 purchase_order.customer_name 的 trigram GIN 索引（加速客户名称模糊搜索）
--    注意：这是跨表索引，在 purchase_order 表上创建
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_purchase_order_customer_trgm
    ON purchase_order USING gin (customer_name gin_trgm_ops);

-- 5. 为 material_registration_item 的 material_name 创建索引（历史查询/联想建议加速）
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_mat_reg_item_name_trgm
    ON material_registration_item USING gin (material_name gin_trgm_ops);

-- 验证索引是否创建成功
-- SELECT indexname, indexdef FROM pg_indexes 
-- WHERE tablename IN ('material_registration', 'purchase_order', 'material_registration_item')
--   AND indexname LIKE '%trgm%';
