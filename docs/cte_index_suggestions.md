# CTE 查询索引建议文档

> 来源：`.codeartsdoer/specs/code_quality_opt/tasks.md` P0-3  
> 关联代码：`fastapi_app/services/stock_service.py` `_build_inventory_cte_sql`  
> 状态：**待 DBA 评审签字**（研发不直接在生产库执行 DDL）

## 1. 背景

`stock_service._build_inventory_cte_sql` 构造的库存聚合 CTE 查询，通过 UNION ALL 合并 `stock_in`、`stock_out`、`order`、`daily_production_record` 多表数据，按 `product_id` / `customer` 聚合。该查询是出库管理模块的核心，需确认索引覆盖以保证生产规模下 P95 ≤ 500ms。

## 2. 验证步骤（DBA 在 staging 库执行）

### 2.1 数据集准备
在 staging 库导入接近生产规模数据：
- `order` 表：≥ 100 万条
- `stock_in` 表：≥ 50 万条
- `stock_out` 表：≥ 50 万条
- `product` 表：≥ 1 万条

### 2.2 执行 EXPLAIN ANALYZE

对以下查询执行 `EXPLAIN (ANALYZE, BUFFERS)`：

```sql
-- 库存聚合 CTE 主查询（由 _build_inventory_cte_sql 生成）
EXPLAIN (ANALYZE, BUFFERS)
SELECT si.product_id, si.customer,
       SUM(si.quantity - COALESCE(sub.consumed, 0)) AS stockin_qty
FROM stock_in si
LEFT JOIN (
    SELECT stockin_id, SUM(quantity - returned_quantity) AS consumed
    FROM stock_out WHERE stockin_id IS NOT NULL
    GROUP BY stockin_id
) sub ON sub.stockin_id = si.id
WHERE 1=1
GROUP BY si.product_id, si.customer;
```

### 2.3 关键检查项
- [ ] `stock_in` 扫描为 **Index Scan** 而非 Seq Scan
- [ ] `stock_out` 扫描为 **Index Scan**
- [ ] `order` 扫描为 **Index Scan**
- [ ] JOIN 操作使用 Hash Join 或 Merge Join（非 Nested Loop）
- [ ] CTE 查询 P95 ≤ 500ms

## 3. 现有索引清单（需 DBA 确认）

| 表 | 列 | 索引类型 | 用途 |
|----|----|---------|------|
| stock_in | product_id | B-Tree | 按 product_id 聚合 |
| stock_in | customer | B-Tree | 按 customer 筛选 |
| stock_out | stockin_id | B-Tree | JOIN stock_in |
| stock_out | order_id | B-Tree | 关联订单 |
| stock_out | product_id | B-Tree | 按 product_id 聚合 |
| stock_out | customer | B-Tree | 按 customer 筛选 |
| order | product_id | B-Tree | 按 product_id 聚合 |
| order | customer | B-Tree | 按 customer 筛选 |
| order | order_type | B-Tree | 按 order_type 筛选 |
| daily_production_record | product_id | B-Tree | 按 product_id 聚合 |
| product | id | B-Tree (PK) | 主键查询 |

## 4. 建议新增索引（若 EXPLAIN 发现 Seq Scan）

```sql
-- 复合索引：覆盖 stock_in 常用筛选+聚合模式
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stock_in_product_customer
    ON stock_in (product_id, customer);

-- 复合索引：覆盖 stock_out 按 stockin_id 聚合
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_stock_out_stockin_qty
    ON stock_out (stockin_id)
    WHERE stockin_id IS NOT NULL;

-- 复合索引：覆盖 order 按 product_id + customer + order_type
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_product_customer_type
    ON "order" (product_id, customer, order_type);
```

> 注意：`CREATE INDEX CONCURRENTLY` 不阻塞读写，可在维护窗口外执行，但仍建议 DBA 评估。

## 5. 验证结果记录

| 项 | 治理前 | 治理后 | 通过 |
|----|--------|--------|------|
| stock_in 扫描类型 | （待填） | （待填） | ☐ |
| stock_out 扫描类型 | （待填） | （待填） | ☐ |
| order 扫描类型 | （待填） | （待填） | ☐ |
| CTE P95 响应时间 | （待填）ms | （待填）ms | ☐ |

## 6. DBA 评审签字

- 评审人：_______________
- 评审日期：_______________
- 结论：☐ 通过  ☐ 驳回（原因：_______________）
- 索引调整执行窗口：_______________

---

> 研发侧已完成：CTE 查询使用绑定参数（非字符串拼接），`# nosec B608` 标注合规，ruff S608 已豁免并注释说明。索引层面需 DBA 在 staging 库验证后决定是否新增。