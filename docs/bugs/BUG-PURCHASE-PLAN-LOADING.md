# BUG-PURCHASE-PLAN-LOADING 修复记录

- **修复时间**: 2026-05-07
- **影响页面**: /purchase-plan 每日计划 + 月度汇总
- **现象**: 页面经常出现"加载中"卡住和"加载失败"

## 根因分析

1. **P0: `_get_shipped_fifo_map` 的 StockOut JOIN 查询无超时保护**
   - 原代码通过 `JOIN Product` + `Product.name IN(product_names)` 过滤出货记录
   - `Product.name` 无索引，product_names 列表较长时触发全表扫描
   - 查询跨越12个月数据无 LIMIT，数据量大时响应极慢
   - 无 statement_timeout，慢查询阻塞数据库连接池

2. **P1: `customer_summary` 调用 `_get_inventory_map`，缓存过期后触发4条复杂SQL**
   - `stock_service.get_inventory` 执行4条聚合SQL，无超时保护
   - 缓存击穿时多个并发请求同时穿透到DB

3. **P1: 前端重试策略过于激进**
   - axios timeout=30s + useQuery retry:2 + executeWithRetry 3次
   - 最坏情况用户等 30s * 3 * 3 = 数分钟
   - 错误状态无重试按钮，用户体验差

## 修复方案

### 后端 (`fastapi_app/services/purchase_plan_service.py`)
1. `_get_shipped_fifo_map` 拆分为外层异常兜底 + 内层 `_fifo_query_with_timeout`
2. 内层用 `asyncio.timeout(10)` 限制总查询时间，超时返回 `{detail_id: 0}` 降级
3. StockOut 查询改用 `product_id IN(...)` 替代 `JOIN Product + Product.name IN(...)`
   - 利用已有索引 `idx_stockout_product_customer_type (product_id, customer, stockin_id)`
   - 仅在 product_id 不可用时降级为原 JOIN 查询
4. 新增 Product.id→name 内存映射，避免 JOIN 开销
5. 所有异常均 catch 并降级返回空映射，不再向上抛出

### 后端 (`fastapi_app/api/v1/endpoints/purchase_plan.py`)
1. `monthly_calendar` 和 `customer_summary` 端点增加 `asyncio.TimeoutError` 专属捕获
2. 超时返回 504 状态码 + 明确提示"请稍后重试"
3. 通用 Exception 兜底，返回 500 + 通用提示

### 前端 (`frontend-vite/src/views/purchase-plan/PurchasePlanView.vue`)
1. useQuery `retry: 2` → `retry: 1`，减少无效重试
2. 新增 `retryDelay: 2000`，避免瞬时重试加重后端负载
3. 加载失败状态增加"重试"按钮，用户可主动刷新
4. 新增 `sError` 变量追踪月度汇总的错误状态

### 前端 (`frontend-vite/src/api/request.ts`)
1. axios `timeout: 30000` → `timeout: 15000`，减少用户等待
2. `MAX_RETRIES: 3` → `MAX_RETRIES: 2`，减少雪崩效应

## 验证结果
- Python 语法校验: PASS
- TypeScript 编译: 无新增错误
- bandit 安全扫描: 0 High/Medium issues
- 代码审查双策略 (分类清单 + 执行路径追踪): PASS
