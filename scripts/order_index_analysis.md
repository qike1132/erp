# order 表索引分析与优化建议

## 当前索引清单

order 表目前定义了约 25 个索引（含主键、唯一索引、列级索引、复合索引、部分索引、GIN 索引）。

### 列级索引（5 个）
| 列 | 用途 | 建议 |
|---|---|---|
| customer | 客户名称搜索/过滤 | 保留，高频查询条件 |
| order_date | 日期排序/过滤 | 保留，但可被复合索引覆盖 |
| product_id | 产品关联过滤 | 保留，高频外键过滤 |
| status | 状态过滤 | 保留，但多数查询会结合其他列 |
| is_deleted | 软删除过滤 | 保留，部分索引已覆盖未删除数据 |

### 复合/部分索引（19 个）
| 索引名 | 列/条件 | 评估 |
|---|---|---|
| idx_order_customer_status | customer, status | 保留，常见组合过滤 |
| idx_order_product_status | product_id, status | 保留，常见组合过滤 |
| idx_order_status_date | status, order_date | 保留，常见组合过滤 |
| idx_order_customer_product | customer, product_id | **候选移除**，可被 idx_order_customer_status 或 idx_order_product_status 覆盖 |
| idx_order_locked | is_locked | **候选移除**，is_locked 使用频率低 |
| idx_order_type | order_type | **候选移除**，order_type 使用频率低 |
| idx_order_batch_no | batch_no | 保留，批次号查询 |
| idx_order_batch_completed_at | batch_completed_at | **候选移除**，与 idx_order_batch_completed 重复 |
| idx_order_locked_by | locked_by_id | 保留（如果锁定功能常用） |
| idx_order_deleted_by | deleted_by_id | **候选移除**，删除人查询极少 |
| idx_order_batch_completed_by | batch_completed_by_id | **候选移除**，按完成人查询极少 |
| idx_order_product_customer_type | product_id, customer, order_type | **候选移除**，列过多，使用场景少 |
| idx_order_product_type_country | product_id, order_type, country | **候选移除**，列过多，使用场景少 |
| idx_order_customer_trgm | customer GIN trigram | 保留，模糊搜索需要 |
| idx_perf_order_status_date_covering | status, order_date DESC, id WHERE is_deleted=false | 保留，覆盖常见未删除订单查询 |
| idx_perf_order_customer_date | customer, order_date DESC WHERE is_deleted=false | 保留，覆盖客户+日期查询 |
| idx_order_batch_completed | batch_completed_at DESC WHERE NOT NULL | 保留，批次完成查询 |
| idx_order_not_deleted_date | order_date DESC WHERE is_deleted IS NOT TRUE | **候选移除**，可被 idx_perf_order_status_date_covering 覆盖 |
| idx_order_not_deleted_customer | customer WHERE is_deleted IS NOT TRUE | **候选移除**，可被 idx_perf_order_customer_date 覆盖 |

## 候选移除索引（9 个）

以下索引建议通过 `pg_stat_user_indexes` 验证使用次数为 0 或极低后移除：

1. `idx_order_customer_product`
2. `idx_order_locked`
3. `idx_order_type`
4. `idx_order_batch_completed_at`
5. `idx_order_deleted_by`
6. `idx_order_batch_completed_by`
7. `idx_order_product_customer_type`
8. `idx_order_product_type_country`
9. `idx_order_not_deleted_date`
10. `idx_order_not_deleted_customer`

## 实施步骤

1. 在目标环境执行 `order_index_usage.sql` 收集真实使用数据。
2. 对 `idx_scan = 0` 的索引，先使用 `DROP INDEX CONCURRENTLY` 在生产环境移除。
3. 观察 7 天，监控慢查询和性能指标。
4. 确认无影响后，在模型中删除对应 `Index(...)` 定义，并生成 Alembic 迁移。
5. 最终目标：order 表索引数量从 25 个降至 ≤12 个。
