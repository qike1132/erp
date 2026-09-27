# 多 SKU 订单与采购中心 DTO 治理规格

## 状态

业务规格草案；未修改订单语义。需要业务负责人确认后实施。

## 问题 1：多 SKU 订单

当前 `Order.quantity`、`Order.product_id` 等字段在多 SKU 场景中是首 item 或合计的兼容值。代码中存在 19 处 `TODO(multi-sku-order)`，说明查询、编辑、审批、库存扣减、报表和采购生成仍依赖兼容语义。

### 需要业务确认的问题

1. **编辑**：客户修改数量时，是按订单维度改总数，还是必须指定某个 `OrderItem`？
2. **审批**：审批通过或调整数量时，审批记录应引用订单头还是具体 item？
3. **库存扣减**：多 SKU 订单是否要求所有 item 全部可扣才允许确认，还是允许部分确认？
4. **采购生成**：采购单应按 customer/product/item 哪个粒度合并？
5. **报表口径**：销量统计按 item 数量求和，还是按订单头合计字段？
6. **兼容期**：历史单 SKU 订单是否永远允许读取 `Order.quantity/product_id` 兼容值？

### 目标规格

- `Order` 是聚合根，`OrderItem` 是唯一数量、产品、单价、国家等业务属性来源。
- 查询与写入不得直接读取 `Order.quantity/product_id` 判断多 SKU 语义；统一通过领域服务提供：
  - `order_summary(order)`：返回总数、首产品等兼容视图，仅用于展示和过渡。
  - `editable_items(order)`：返回可编辑 item。
  - `inventory_requirements(order)`：返回按 item 聚合后的扣减需求。
- 审批、出库、采购、报表分别创建显式服务函数，禁止在 SQL 中重复推导多 SKU 逻辑。
- 兼容字段只读，迁移完成前不得继续写入；迁移完成后标注 deprecated 并逐步移除。

### 实施顺序

1. 为订单域补齐多 item 查询与写入测试。
2. 先改读路径：审批详情、报表、采购列表统一读取 item 聚合。
3. 再改写路径：编辑、审批数量调整、库存扣减。
4. 最后清历史字段和 TODO。

## 问题 2：采购中心 DTO 双定义

当前 `fastapi_app/api/v1/endpoints/purchase_center/schemas.py` 与 `fastapi_app/schemas/purchase_center.py` 存在同名或近似 DTO，包括 `CustomerSyncRequest`、`CustomerBatchRequest`、`OneClickGenerateRequest`、`FactorySummarySaveRequest`、`SummaryPrintRequest` 等。

### 目标

- API 请求/响应模型以 `fastapi_app/schemas/purchase_center.py` 为唯一来源。
- endpoint 私有 `schemas.py` 仅保留路由组装所需的别名，且必须从公共 schema re-export，不允许字段重复声明。
- 请求模型使用 `extra="forbid"`，避免未知字段静默丢弃。
- 新增契约测试逐字段比对公共 DTO 与 OpenAPI schema。

### 分批迁移

1. 列出重复类及 endpoint 引用矩阵。
2. 无行为差异的 DTO 先改为 re-export。
3. 字段或校验不一致的 DTO 单独立 ticket，由后端和前端确认目标契约后再迁移。
4. 更新 API 对齐检查脚本和契约快照。

### 已完成的第一步

- 2026-09-27：`CustomerSyncRequest`、`CustomerBatchRequest` 已在 endpoint 私有 schema 中改为从 `fastapi_app/schemas/purchase_center.py` re-export，消除完全重复定义；`fastapi_app/tests/test_purchase_center.py` 通过。

## 问题 3：PrimeVue 首屏体积

当前 `vendor-primevue` chunk 约 672KB，主要由共享组件 `UiDataTable`、`UiAutocomplete`、`UiDateRangePicker`、`UiDrawer` 引入。`UiDataTable` 被 15 个 Vue 文件使用，直接替换组件库会带来大面积表格交互回归。

### 评估结论

- 不建议直接移除 PrimeVue：使用面广，收益主要在包体，回归成本高。
- 可行优化是把 `manualChunks` 中的 `'primevue'` 粗粒度入口，改为按实际组件分包或依赖 Vite 原生动态模块拆分。
- 进一步可选优化：只在需要表格的异步路由加载 `UiDataTable`；为 `UiAutocomplete`、`UiDateRangePicker`、`UiDrawer` 建独立 async import。
- 验收指标：首屏 HTML+JS 传输体积下降，且采购、订单、库存、报表、板房等核心表格页无功能回归。