# CTE 查询索引建议

> 生成背景：L7 性能门禁（`scripts/prod_audit/layers/l7_performance.py` 的
> `L7-CTE-INDEX-DOC-001`）要求本文件存在；`L7-CTE-INDEX-MISSING-001` 以本文件的
> **结构化清单块**（下方 `prod_audit:cte-index` 标记块）为 CTE 覆盖核对基准：
> `fastapi_app/services/` 下每个含 CTE 查询的源文件都必须在清单块里登记一行，
> 否则报「CTE 查询未登记」。
>
> ⚠️ 标记块是**机器读**的：字段用 `|` 分隔，顺序固定为
> `源文件相对路径 | CTE 名(逗号分隔) | 动作 | 涉及表(逗号分隔)`；
> `动作` 取值 `index`（建议加索引）/ `covered`（现有索引已覆盖）/ `exempt`（无需动作）。
> 改标题、加散文段落不影响核对，但**不要删改标记块内的行**。
>
> 内容基于对 `fastapi_app/services/` 内三处 CTE 文件的实际访问路径与
> `fastapi_app/shared_models/`（ORM `__table_args__`）、`migrations/versions/`
> 现有索引的逐列核对，非占位文档。索引状态核对日期：2026-10-20。

<!-- prod_audit:cte-index:start -->
fastapi_app/services/stock_inventory_service.py | stockin_agg,activity | index | stock_in,stock_out,order,order_item,daily_production_record,inventory_log
fastapi_app/services/report_service.py | page_orders | covered | order,order_item,product
fastapi_app/services/backup/orchestration/drill_validator.py | fk_base,fk_ref | exempt | information_schema
<!-- prod_audit:cte-index:end -->

## 库存结余 CTE（fastapi_app/services/stock_inventory_service.py:523 `_build_inventory_cte_sql`）

访问路径（五段 CTE，`stockin_agg`/`stockout_agg`/`order_agg`/`production_agg`/
`product_stockout_total` FULL OUTER JOIN 后聚合）：

| 表 | 过滤/连接列 | 现有索引 | 结论 |
|---|---|---|---|
| `stock_in` | `product_id`（等值）、`customer`（等值）、`stockin_date`；反连接 `stock_out.stockin_id` | `product_id`、`customer`、`stockin_date` 各自单列 + `idx_stockin_customer_product_date (customer, product_id, stockin_date)` + 覆盖索引 `idx_perf_stockin_product_date (product_id, stockin_date DESC)` | 覆盖足够 |
| `stock_out` | `product_id`、`customer`、`stockin_id IS NULL`；反连接 `stockin_id IS NOT NULL` | `idx_stockout_product_date (product_id, stockout_date)`、`idx_stockout_customer_date`、`idx_perf_stockout_product_date (product_id, stockout_date DESC)` | 覆盖足够（`stockin_id` 侧已由 `idx_stockout_stockin (stockin_id)`、`idx_stockout_no_stockin (product_id, customer) WHERE stockin_id IS NULL`、`idx_stockout_deduction (product_id, stockout_date DESC) WHERE stockin_id IS NOT NULL` 覆盖） |
| `order` / `order_item` | `order.product_id`、`order.customer`、`order_item.order_id` | `idx_perf_order_status_date_covering`、`idx_perf_order_customer_date`（order 侧）；`ix_order_item_order_id (order_id)`、`ix_order_item_order_product (order_id, product_id)`（order_item 侧） | 覆盖足够 |
| `daily_production_record` | `product_id IS NOT NULL`、`department = 'packaging'`、`production_date` | `idx_dpr_product_id`、`idx_dpr_dept_date (department, production_date)` | 覆盖足够 |
| `inventory_log` | `product_id` + `change_type IN (...)` + `change_date` | `idx_inventory_log_product_date (product_id, change_date DESC)` + `change_type` 单列 | ⚠️ 组合过滤（product_id + change_type）时单列索引选择性有限；若该子查询成瓶颈，建议 `CREATE INDEX ON inventory_log (product_id, change_type)`（复合）—— **未建，见下方汇总** |

### 同文件第二个 CTE：客户活跃度（fastapi_app/services/stock_inventory_service.py:744 `activity`）

`UNION ALL` 两路：未软删且 `quantity > 0` 的 `"order"`、以及 `stock_in`，均按
`customer` 聚合。

- `"order"` 侧：`idx_order_customer_status (customer, status)` 可支撑
  `GROUP BY customer`；注意 `is_deleted IS NOT TRUE` 与 partial 索引
  `idx_perf_order_customer_date ... WHERE is_deleted = false` 的谓词**不等价**
  （`IS NOT TRUE` 覆盖 `NULL`），该 partial 索引用不上，属可接受退化。
- `stock_in` 侧：`idx_stockin_customer_product (customer, product_id)` 可支撑
  `GROUP BY customer`。
- 结论：覆盖足够（动作 `covered`）。

## 订单流水 CTE（fastapi_app/services/report_service.py:110 `page_orders`）

`data_sql` 的分页 CTE：`FROM "order" o` → `LEFT JOIN order_item oi ON oi.order_id = o.id`
→ `LEFT JOIN product p ON p.id = COALESCE(oi.product_id, o.product_id)`，
`GROUP BY o.id` + `ORDER BY MAX(o.order_date) DESC`（分页落在订单上）。

| 表 | 过滤/连接列 | 现有索引 | 结论 |
|---|---|---|---|
| `order` | 业务筛选（客户/日期/状态等）、`GROUP BY o.id`、`ORDER BY MAX(o.order_date)` | `idx_perf_order_customer_date (customer, order_date DESC) WHERE is_deleted = false`、`idx_perf_order_status_date_covering`、`idx_order_date_id_desc` | 覆盖足够 |
| `order_item` | `oi.order_id = o.id` | `ix_order_item_order_id (order_id)`、`ix_order_item_order_product (order_id, product_id)` | 覆盖足够 |
| `product` | `p.id`（主键等值） | 主键 | 覆盖足够 |

- 结论：覆盖足够（动作 `covered`）。残留风险：`GROUP BY o.id` 需对命中筛选集
  聚合，随订单量线性增长；当前已有 `LIMIT/OFFSET` 与 `COUNT(*) OVER ()`，
  暂不单列索引建议。

## 外协恢复校验 CTE（fastapi_app/services/backup/orchestration/drill_validator.py:48 `fk_base`）

访问路径：对 `information_schema` 系统视图的元数据查询（`fk_base` CTE 聚合
外键约束信息），非业务表扫描。系统视图自带优化，无需应用侧索引。**结论：无需动作。**

> 注：原文档把该 CTE 记在 `recovery_test_service.py:55`，实际已于 2026-10-15
> 随验证族迁至 `drill_validator.py`（`recovery_test_service.py` 只剩 import 引用）。

## 汇总（潜在动作，按收益排序）

1. ~~`stock_out(stockin_id) WHERE stockin_id IS NOT NULL` 部分索引~~ —— **已落地**：
   ORM 声明 `idx_stockout_stockin`、`idx_stockout_no_stockin`、
   `idx_stockout_deduction`（`fastapi_app/shared_models/stock_out.py:41-59`）。
2. ~~`order_item(order_id)` 显式索引~~ —— **已落地**：`ix_order_item_order_id`
   （ORM `fastapi_app/shared_models/order_item.py:44-46`，迁移 014 建）。
3. `inventory_log(product_id, change_type)` 复合索引 —— 出货流水统计。**未建**，
   待该子查询成为瓶颈时再评估。

> ⚠️ 仍未建索引的条目属**建议**。加索引属生产 DDL：走临时空库 autogenerate 评估
> 写放大，低峰窗口 `CREATE INDEX CONCURRENTLY`，判据见 `migrations/README`。
