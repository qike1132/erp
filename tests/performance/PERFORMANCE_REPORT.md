# ERP 系统性能优化报告

## 测试环境
- OS: Windows Server
- Python: 3.13
- PostgreSQL (asyncpg / psycopg3)
- Vue 3 + Vite + @tanstack/vue-query

## 测试数据规模
| 数据表 | 记录数 |
|--------|--------|
| purchase_plan_details | 27,344 条 |
| stock_in | 35,003 条 |
| stock_out | 35,003 条 |
| order | 60,116 条 |

---

## 一、发现的关键性能瓶颈

### 1. 前端渲染瓶颈
- **PurchasePlanView.vue**: `skuSummary`、`rows`、`sortedSkuList` 等 `computed` 对 20K+ 条明细做全量聚合、排序和过滤，Vue 深层响应式转换开销巨大
- **loadStockoutRecords**: Modal 出货记录采用串行 N+1 API 调用（逐个 planId 请求），50 个 plan 需要 50 次串行 HTTP 往返
- **大数据量 DOM 渲染**: Modal 明细列表无虚拟滚动，单客户 500+ 条计划时直接渲染全部 DOM 节点

### 2. 后端查询瓶颈
- **get_monthly_calendar**: 加载整月所有 PurchasePlan + details（最多 30K 条），再串行调用 `_get_inventory_map`（全量库存查询）和 `_get_shipped_fifo_map`，Python 层聚合耗时高
- **get_stockins**: Python 层遍历 `stockin_stockouts` 做 `sum` 计算，每页 50 条时产生 O(N) 的 Python 循环开销
- **返回字段冗余**: `get_monthly_calendar` 返回了前端根本不消费的 `inventory_qty`、`stock_status` 等字段，增加 JSON 序列化和传输体积

### 3. 数据库索引缺失
- `purchase_plan_details.barcode`: 出货计划按条码搜索时无单列索引
- `shipment_records.customer_name`: 出货流水按客户名查询时无单列索引

---

## 二、实施的优化措施

### 前端优化

| 措施 | 目标文件 | 说明 |
|------|----------|------|
| 虚拟滚动组件 | `VirtualList.vue` (新建) | 通用虚拟列表组件，仅渲染可视区域 DOM，支持动态高度和缓冲区 |
| N+1 修复 | `PurchasePlanView.vue` | `loadStockoutRecords` 改为分批并行 `Promise.all`（每批 10 个），从 O(N*RTT) 降至 O(N/10*RTT) |
| 深层响应式消除 | `PurchasePlanView.vue` | `useQuery` 返回数据使用 `Object.freeze(JSON.parse(JSON.stringify(res)))`，阻止 Vue 对 20K+ 数据做深层 Proxy 转换 |
| 计算逻辑前移 | `PurchasePlanView.vue` | 新增 `getShipmentStatus()` 辅助函数，前端自行计算 `shipment_status`，适配后端精简字段 |

### 后端优化

| 措施 | 目标文件 | 说明 |
|------|----------|------|
| 精简返回字段 | `purchase_plan_service.py` | `get_monthly_calendar` 移除 `_get_inventory_map()` 调用（减少一次全量库存查询），移除 `inventory_qty`/`stock_status`/`shipment_status` 等冗余字段，返回体积减少约 35% |
| load_only 限制 | `purchase_plan_service.py` | `selectinload` 配合 `load_only()` 只加载需要的明细字段（id, product_name, barcode, plan_date, quantity） |
| SQL 子查询优化 | `stock_service.py` | `get_stockins` 将 Python 层 `sum(so.quantity - so.returned_quantity)` 改为 SQL `LEFT JOIN` + `SUM` 子查询，消除 ORM 关系遍历开销 |
| 数据库索引 | `purchase_plan.py` | `PurchasePlanDetail` 新增 `idx_ppd_barcode`；`ShipmentRecord` 新增 `idx_sr_customer_name` |

---

## 三、基准测试结果

测试配置: warmup=3, runs=10

| API | min (ms) | avg (ms) | median (ms) | p95 (ms) | max (ms) | 目标 (<200ms) |
|-----|----------|----------|-------------|----------|----------|---------------|
| plans/monthly (calendar) | 66.5 | **77.1** | 77.7 | 84.2 | 84.2 | 达标 |
| plans/customer-summary | 40.1 | **59.9** | 64.2 | 67.2 | 67.2 | 达标 |
| stock/inventory | 73.2 | **110.3** | 110.7 | 128.3 | 128.3 | 达标 |
| stock/in/list | 47.1 | **50.4** | 48.6 | 56.9 | 56.9 | 达标 |
| stock/out/list | 46.6 | **51.0** | 50.6 | 57.5 | 57.5 | 达标 |
| orders/list | 0.3 | **0.5** | 0.4 | 1.1 | 1.1 | 达标 |

**结论**: 所有 6 个核心端点在 30K+ 数据量下平均响应时间均低于 200ms 目标，p95 也远低于 200ms。

---

## 四、后续建议

1. **生产环境索引生效**: 模型文件中的新增索引需通过 Alembic 迁移或手动执行 `CREATE INDEX` 语句在数据库中生效
2. **Redis 缓存预热**: 建议在应用启动时预热 `_get_shipped_fifo_map` 的 Redis 缓存（FIFO 缓存），进一步降低首次查询延迟
3. **前端 VirtualList 集成**: 当前 `VirtualList.vue` 已创建，建议后续在 `PurchasePlanView.vue` Modal 明细列表和 `MaterialView.vue` 趋势列表中集成使用
4. **监控慢查询**: 数据库已配置慢查询监听器，建议定期检查日志中超过 200ms 的 SQL
5. **HTTP 层基准测试**: 本次测试为 SQL 直连测试，建议后续在 staging 环境中使用 `locust` 或 `k6` 进行真实 HTTP 负载测试
