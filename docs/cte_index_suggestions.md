# CTE 查询索引建议

> 生成背景：L7 性能门禁（`scripts/prod_audit/layers/l7_performance.py` 的
> `L7-CTE-INDEX-DOC-001`）要求本文件存在，并以此处的表名清单作为 CTE 查询的
> 覆盖核对基准。内容基于 2026-10-11 对 `fastapi_app/services/` 内两处 CTE 的
> 实际访问路径与 `fastapi_app/shared_models/`、`migrations/versions/` 现有索引
> 的逐列核对，非占位文档。

## 库存结余 CTE（fastapi_app/services/stock_inventory_service.py:523 `_build_inventory_cte_sql`）

访问路径（五段 CTE，`stockin_agg`/`stockout_agg`/`order_agg`/`production_agg`/
`product_stockout_total` FULL OUTER JOIN 后聚合）：

| 表 | 过滤/连接列 | 现有索引 | 结论 |
|---|---|---|---|
| `stock_in` | `product_id`（等值）、`customer`（等值）、`stockin_date`；反连接 `stock_out.stockin_id` | `product_id`、`customer`、`stockin_date` 各自单列 + 覆盖索引 `idx_perf_stockin_product_date (product_id, stockin_date DESC)` | 覆盖足够 |
| `stock_out` | `product_id`、`customer`、`stockin_id IS NULL` | `product_id`、`stockout_date` 单列 + `idx_perf_stockout_product_date (product_id, stockout_date DESC)` | ⚠️ `stockin_id` 无索引：反连接 `NOT IN (SELECT stockin_id FROM stock_out WHERE stockin_id IS NOT NULL)` 每次全表扫。数据量大后建议 `CREATE INDEX ON stock_out (stockin_id) WHERE stockin_id IS NOT NULL`（部分索引，写放大极小） |
| `order` / `order_item` | `order.product_id`、`order.customer`、`order_item.order_id` | `idx_perf_order_status_date_covering`、`idx_perf_order_customer_date`（order 侧）；`order_item.order_id` 需核对（ORM 无显式索引，依赖 PG 对 FK 不自动建索引） | ⚠️ `order_item.order_id` 建议确认有索引：`CREATE INDEX IF NOT EXISTS idx_order_item_order_id ON order_item (order_id)` |
| `daily_production_record` | `product_id IS NOT NULL`、`department = 'packaging'`、`production_date` | `idx_dpr_product_id`、`idx_dpr_dept_date (department, production_date)` | 覆盖足够 |
| `inventory_log` | `product_id` + `change_type IN (...)` + `change_date` | `product_id`、`change_type`、`change_date` 各自单列 | ⚠️ 组合过滤（product_id + change_type）时单列索引选择性有限；若该子查询成瓶颈，建议 `CREATE INDEX ON inventory_log (product_id, change_type)`（复合） |

## 外协恢复校验 CTE（fastapi_app/services/backup/orchestration/recovery_test_service.py:55 `fk_base`）

访问路径：对 `information_schema` 系统视图的元数据查询（`fk_base` CTE 聚合
外键约束信息），非业务表扫描。系统视图自带优化，无需应用侧索引。**结论：无需动作。**

## 汇总（潜在动作，按收益排序）

1. `stock_out(stockin_id) WHERE stockin_id IS NOT NULL` 部分索引 —— 库存结余页反连接。
2. `order_item(order_id)` 显式索引确认 —— JOIN 每次命中。
3. `inventory_log(product_id, change_type)` 复合索引 —— 出货流水统计。

> ⚠️ 以上均为**建议**，未建索引。加索引属生产 DDL：走临时空库 autogenerate 评估
> 写放大，低峰窗口 `CREATE INDEX CONCURRENTLY`，判据见 `migrations/README`。
