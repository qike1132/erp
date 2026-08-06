# 多 SKU 订单聚合生成 Spec

## Why

`/customer-order` 页面用户在录入环节可一次性向暂存列表添加多个 SKU，但提交后系统会**为每个 SKU 生成一条独立的主订单**（独立 `order_no`），同一客户的多个 SKU 散落在多条主订单中。这与用户期望"一个主订单包含所有 SKU"不符。

**诊断结论（已通过代码调查确认）**：

- 这是**未实现**而非"BUG"。当前 `Order` 模型本身是单 SKU 粒度：`product_id` 为单字段非空外键（[shared_models/order.py:47-96](file:///d:/erp_system/fastapi_app/shared_models/order.py)），**全项目不存在 `OrderItem`/`OrderDetail` 子表**。
- 前端 `submitAll()` 将扁平暂存数组直接 `map` 成 `{ orders: [...] }` 调用 `POST /aux/batch-submit-orders`（[useOrderActions.ts:43-97](file:///d:/erp_system/frontend-vite/src/views/customer-order/composables/useOrderActions.ts)），**前端无任何聚合**。
- 后端 `batch_create_orders` 在循环 `for order_data in orders_data:` 内为每个 SKU 创建独立 `Order` + 独立 `order_no` + 独立 `InventoryLog`（[order_batch_create.py:51,99,101-124](file:///d:/erp_system/fastapi_app/services/order_batch_create.py)），**后端也无聚合逻辑**。
- 同一客户的多个 SKU 提交后产生 N 条主订单，业务无法以"一单"维度跟踪。

**用户决策（已通过 AskUserQuestion 确认）**：
1. 聚合维度：**按客户聚合**（同一客户暂存列表中的所有 SKU 聚合为一个主订单，跨 `normal`/`custom` 类型合并）
2. 实施范围：**完全重构为 OrderItem 模型**（ERP 行业标准做法，符合第三范式）

## What Changes

### 数据模型
- **新增 `order_item` 表**：承载 SKU 级字段（`product_id`, `quantity`, `order_type`, `country`, `deduct_stock`, `deduct_quantity`, `note`, 冗余 `product_name`/`product_barcode`），通过 `order_id` 外键关联主订单
- **修改 `Order` 主表**：移除 SKU 级字段（`product_id`, `quantity`, `deduct_stock`, `deduct_quantity`, `country`, `order_type`, `product_name`, `product_barcode`）；保留 `id`, `order_no`, `customer`, `status`, `batch_no`, `order_date`, `note`, `created_at`, `updated_at`, `version`；新增 `items` relationship
- **移除 `Order.product_id` 的 NOT NULL 约束** 并最终删除该列（**BREAKING**）

### 后端逻辑
- **修改 `batch_create_orders`**：按 `customer` 分组输入 payload，每组生成 1 个 `Order`（1 个 `order_no`）+ N 个 `OrderItem`；库存扣减、`InventoryLog` 按 `OrderItem` 粒度生成
- **修改 `Order` CRUD/schema**：`OrderSchema` 嵌套 `items: list[OrderItemSchema]`；查询订单时 `selectinload(Order.items)`
- **修改所有依赖 `Order.product_id`/`Order.quantity` 的下游**：库存扣减、出货生成、采购计划联动、报表统计、仪表盘聚合——改为遍历 `Order.items`
- **新增数据迁移**：把现有单 SKU `Order` 转换为 `Order` + 1 `OrderItem`，保留历史数据可读性

### 前端
- **订单列表**：一行一主订单，可展开查看多 SKU 明细
- **订单详情**：显示多 SKU 列表
- **录入表单不变**：仍以单 SKU 粒度添加到暂存列表，聚合在后端完成

### 不在范围内
- 不修改录入表单 UI（仍逐个 SKU 添加到暂存）
- 不修改 `staging_order` 表结构（前端实际未通过 `/staging-orders/confirm` 路径，仅走 `/aux/batch-submit-orders`）
- 不修复 `order_type` 取值在前端 (`normal`) vs 后端 (`regular`) 的既有不一致（独立问题）

## Impact

### Affected specs
- `order_management_update`（订单管理需求基线，本 spec 修改其订单生成语义）

### Affected code（关键文件，非穷举）
- [fastapi_app/shared_models/order.py](file:///d:/erp_system/fastapi_app/shared_models/order.py) — 模型拆分
- `fastapi_app/shared_models/order_item.py` — 新增模型
- `fastapi_app/shared_models/__init__.py` — 导出 `OrderItem`
- `fastapi_app/alembic/versions/` — 新增 migration（建表 + 数据回填 + 删列）
- [fastapi_app/services/order_batch_create.py](file:///d:/erp_system/fastapi_app/services/order_batch_create.py) — 聚合创建逻辑
- [fastapi_app/services/auxiliary_service.py](file:///d:/erp_system/fastapi_app/services/auxiliary_service.py) — 编排层
- [fastapi_app/services/order_service.py](file:///d:/erp_system/fastapi_app/services/order_service.py) — CRUD
- [fastapi_app/services/stock_service.py](file:///d:/erp_system/fastapi_app/services/stock_service.py) — 库存扣减
- [fastapi_app/services/report_service.py](file:///d:/erp_system/fastapi_app/services/report_service.py) — 报表聚合
- [fastapi_app/services/dashboard_service.py](file:///d:/erp_system/fastapi_app/services/dashboard_service.py) — 仪表盘统计
- [fastapi_app/api/v1/endpoints/auxiliary.py](file:///d:/erp_system/fastapi_app/api/v1/endpoints/auxiliary.py) — Schema 与响应
- [fastapi_app/api/v1/endpoints/orders.py](file:///d:/erp_system/fastapi_app/api/v1/endpoints/orders.py) — 订单 API
- `fastapi_app/schemas/order.py` — 嵌套 schema
- `frontend-vite/src/views/customer-order/` — 列表/详情 UI 适配
- `frontend-vite/src/api/order.ts` — 类型定义
- `frontend-vite/src/views/customer-order/composables/useOrderList.ts` — 查询适配

## ADDED Requirements

### Requirement: 多 SKU 主订单聚合生成

系统 SHALL 在用户提交暂存列表时，按 `customer` 字段对 `BatchOrderItem` 列表分组，每组生成 **1 个主订单**（1 个 `order_no`）+ N 个 `OrderItem` 明细，确保同一客户的多个 SKU 在数据层归属同一主订单。

#### Scenario: 同一客户提交多个 SKU

- **WHEN** 用户在 `/customer-order` 暂存列表中添加 3 个 SKU（客户均为"客户A"，2 个 `normal` 类型 + 1 个 `custom` 类型），点击"提交订单"
- **THEN** 后端接收 `POST /aux/batch-submit-orders`，body 含 3 个 `BatchOrderItem`
- **AND** 系统按 `customer='客户A'` 分组为 1 组
- **AND** 创建 1 条 `Order`（1 个 `order_no`，`customer='客户A'`）
- **AND** 创建 3 条 `OrderItem`，分别关联到该 `Order.id`，各自携带 `product_id`/`quantity`/`order_type`/`country`/`deduct_stock`/`deduct_quantity`/`note`
- **AND** 生成 3 条 `InventoryLog`（每个 `OrderItem` 一条），均关联到同一 `order_id`
- **AND** 返回响应中 `created_count == 1`，包含主订单号与所有 SKU 明细

#### Scenario: 多客户混合提交

- **WHEN** 暂存列表含客户A 的 2 个 SKU + 客户B 的 1 个 SKU
- **THEN** 系统创建 2 条 `Order`（客户A 1 条含 2 个 `OrderItem`，客户B 1 条含 1 个 `OrderItem`）
- **AND** 返回 `created_count == 2`

#### Scenario: 单 SKU 提交仍生效

- **WHEN** 暂存列表仅含 1 个 SKU
- **THEN** 创建 1 条 `Order` + 1 条 `OrderItem`，行为与重构前等价

### Requirement: OrderItem 数据模型

系统 SHALL 新增 `order_item` 表，字段包括：`id`、`order_id`（FK→`order.id`，NOT NULL，索引）、`product_id`（FK→`product.id`，NOT NULL）、`product_name`（冗余字符串）、`product_barcode`（冗余字符串）、`quantity`（NOT NULL，1-9999999）、`order_type`（`normal`/`custom`）、`country`（可空，`custom` 类型必填）、`deduct_stock`（bool，default False）、`deduct_quantity`（int，default 0）、`note`（可空）、`created_at`、`updated_at`。

#### Scenario: 主从关系完整性

- **WHEN** 任意 `OrderItem` 被创建
- **THEN** 其 `order_id` MUST 引用已存在的 `Order.id`
- **AND** 删除 `Order` 时通过 `ON DELETE CASCADE` 自动删除关联 `OrderItem`

### Requirement: 历史数据迁移

系统 SHALL 在 Alembic migration 中将现有单 SKU `Order` 数据无损转换为新模型：每条历史 `Order` 生成 1 条 `OrderItem`，字段映射 `Order.product_id`→`OrderItem.product_id`、`Order.quantity`→`OrderItem.quantity`、`Order.order_type`→`OrderItem.order_type`、`Order.country`→`OrderItem.country`、`Order.deduct_stock`→`OrderItem.deduct_stock`、`Order.deduct_quantity`→`OrderItem.deduct_quantity`、`Order.product_name`→`OrderItem.product_name`、`Order.product_barcode`→`OrderItem.product_barcode`，然后从 `Order` 删除上述列。

#### Scenario: 迁移可逆性

- **WHEN** 执行 `alembic upgrade head`
- **THEN** 所有历史订单的 SKU 信息完整保留在 `order_item` 表
- **AND** `alembic downgrade -1` 能恢复原 `Order` 表结构（从 `order_item` 回填字段后删表）

## MODIFIED Requirements

### Requirement: 订单批量创建接口

`POST /aux/batch-submit-orders` 的请求体 schema 不变（仍接收 `orders: list[BatchOrderItem]`），但响应 schema SHALL 返回主订单粒度的结果（含 `order_no` 与嵌套 `items` 列表），`created_count` 为主订单数（非 SKU 数）。

#### Scenario: 响应结构

- **WHEN** 任意批量提交成功
- **THEN** 响应 `created_count` 反映主订单数
- **AND** 每个主订单对象含 `items: list[OrderItemSchema]` 字段
- **AND** 失败明细仍按 `BatchOrderItem` 索引返回

### Requirement: 库存扣减按 OrderItem 粒度

库存扣减 SHALL 按 `OrderItem` 粒度执行：每个 `OrderItem` 触发一次库存变更与 `InventoryLog` 写入，多条 `OrderItem` 共享同一 `order_id`。

#### Scenario: 同主订单多 SKU 抵扣

- **WHEN** 主订单含 3 个 `OrderItem`，其中 2 个 `deduct_stock=True`
- **THEN** 系统为 2 个抵扣项分别扣减库存并写 `InventoryLog`
- **AND** 第 3 个非抵扣项不触发库存变更

### Requirement: 订单列表与详情展示

前端订单列表 SHALL 一行展示一个主订单（含 `order_no`、`customer`、`order_date`、`status`、SKU 数量徽标），点击展开后显示所有 `OrderItem` 明细。订单详情页 SHALL 列出所有 SKU 明细。

#### Scenario: 列表展开

- **WHEN** 用户点击订单列表中某行的展开按钮
- **THEN** 展开区显示该主订单下所有 `OrderItem`（产品名、规格、数量、类型、国家、抵扣信息、备注）

## REMOVED Requirements

### Requirement: Order 表的 SKU 级字段

**Reason**: `Order.product_id`、`Order.quantity`、`Order.deduct_stock`、`Order.deduct_quantity`、`Order.country`、`Order.order_type`、`Order.product_name`、`Order.product_barcode` 字段下移到 `OrderItem`，主表不再承载 SKU 信息。

**Migration**: Alembic migration 在数据回填后删除上述列；所有读/写代码改为访问 `Order.items[i].<field>`。**BREAKING**：任何直接访问 `Order.product_id` 的旧代码将在迁移后报错，必须在迁移前完成代码改造。
