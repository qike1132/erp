# 索引审计报告

> 审计日期：2026-08-21 ｜ 数据库：PostgreSQL 18.3 ｜ 工具：`scripts/index_audit.py`

## 一、重复索引（19 组，可安全合并清理）

同一表上相同列组合的重复索引，保留其一即可，建议删除 `ix_*` 系列（旧命名规范遗留）：

| 表 | 重复索引对 | 建议 |
|---|---|---|
| case | `idx_case_barcode` / `ix_case_barcode` | 删 `ix_case_barcode` |
| case | `idx_case_product` / `ix_case_product_id` | 删 `ix_case_product_id` |
| customer_sampling_project | `customer_sampling_project_sequence_no_key` / `idx_csp_sequence_no` | 删 `idx_csp_sequence_no`（保留唯一约束） |
| inventory_log | `idx_inventory_log_product_date` / `idx_inventory_log_product_time` | 需确认列序，保留含日期排序的 |
| material_registration_item | `idx_material_reg_item_reg_id` / `idx_material_reg_item_registration` | 删一个 |
| modification_log | `idx_mod_time` / `ix_modification_log_modify_time` | 删 `ix_modification_log_modify_time` |
| order_batch_audit_log | `idx_batch_audit_time` / `ix_order_batch_audit_log_created_at` | 删 `ix_*` |
| order_status_log | `idx_status_time` / `ix_order_status_log_action_time` | 删 `ix_*` |
| order_sync_record | `idx_sync_order` / `ix_order_sync_record_source_order_id` | 删 `ix_*` |
| product_material | `idx_product_material_product` / `product_material_product_id_key` | 删 `idx_product_material_product`（保留唯一约束） |
| production_plan | `idx_pp_barcode` / `ix_production_plan_barcode` | 删 `ix_*` |
| production_plan | `idx_pp_customer_name` / `ix_production_plan_customer_name` | 删 `ix_*` |
| saved_query | `idx_saved_query_type` / `ix_saved_query_query_type` | 删 `ix_*` |
| staging_order | `idx_staging_session` / `ix_staging_order_session_id` | 删 `ix_*` |
| staging_purchase_plan | `idx_spp_session` / `ix_staging_purchase_plan_session_id` | 删 `ix_*` |
| staging_purchase_plan | `idx_spp_batch` / `ix_staging_purchase_plan_upload_batch_id` | 删 `ix_*` |
| staging_stock_in | `idx_staging_stockin_session` / `ix_staging_stock_in_session_id` | 删 `ix_*` |
| staging_stock_out | `idx_staging_stockout_session` / `ix_staging_stock_out_session_id` | 删 `ix_*` |
| supplier | `idx_supplier_name` / `ix_supplier_name` | 删 `ix_supplier_name` |

## 二、未使用索引（20 个，60 天无扫描）

**高价值清理目标（大索引）**：
- `audit_log.idx_audit_resource_date`（880KB）
- `customer_sampling_project.idx_csp_product_name_trgm`（792KB）
- `audit_log.idx_audit_created_desc` / `idx_audit_not_login` / `idx_audit_action_date`（各 ~500KB）

**注意**：`audit_log` 表有 10 个索引但大量未使用——该表持续增长，建议清理未使用索引以降低写入开销。
`product`/`order` 表的 trgm 索引（模糊搜索）扫描为 0，若业务确无模糊搜索需求可移除；若为低频功能请保留。

## 三、索引/表大小概览

- 最大表 `audit_log`（7.4MB，10 索引）——小库，所有表均在 MB 级
- `order` 表 15 索引、`stock_out` 12、`stock_in` 11、`audit_log` 10——索引数量偏多，但库小影响有限

## 四、索引膨胀

- **无显著膨胀**（无 dead tuples > 1000 的索引），无需 REINDEX

## 五、建议执行顺序

1. **清理重复索引**（低风险、立即可做）：19 组中删 `ix_*` 旧索引，预计减少 ~15 个索引
2. **清理 audit_log 未使用索引**（降写入开销）：确认审计查询无依赖后删 5-6 个
3. **trgm 索引评估**：确认模糊搜索功能使用情况
4. 清理命令示例：
   ```sql
   DROP INDEX CONCURRENTLY IF EXISTS ix_case_barcode;
   DROP INDEX CONCURRENTLY IF EXISTS audit_log.idx_audit_resource_date;  -- 需确认无查询依赖
   ```

> ⚠️ 本报告仅作审计建议，所有删除需人工确认业务查询无依赖后执行。脚本只读不修改。
