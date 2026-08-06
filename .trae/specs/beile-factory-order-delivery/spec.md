# 贝乐工厂订单精准交付 Spec

## Why

当前订单系统存在以下问题，导致贝乐工厂无法准确、及时地接收属于本厂的订单信息：

1. **用户无工厂标识**：`User` 模型仅有 `is_super` 和权限多对多关系，无法标识某个用户属于「滨发」还是「贝乐」工厂，导致贝乐人员登录后看到的是全量订单，无法快速定位本厂订单。
2. **订单无工厂筛选**：订单列表页面无「工厂」筛选维度，贝乐人员只能手工翻找，易遗漏。
3. **无主动通知机制**：创建/修改包含贝乐 SKU 的订单时，系统不会主动告知贝乐工厂，贝乐方往往延迟数小时甚至次日才知晓新订单。
4. **订单与工厂的关联是隐式的**：`Product.factory` 字段已存在（滨发/贝乐），但订单到工厂的关联需通过 `OrderItem.product.factory` 间接推导，未在前端列表/筛选/权限层面暴露。

本方案在不破坏现有 `multi-sku-order-aggregation` 架构的前提下，通过最小化改动让贝乐工厂能够「方便、及时、准确」地获取本厂订单。

## What Changes

### 数据模型
- **`User` 表新增 `factory` 字段**：`String(20)`，可空，取值 `滨发`/`贝乐`/`NULL`（NULL 表示跨厂管理员/无工厂绑定）。复用 `Product.factory` 的合法值域。
- **新增 `notification` 表**：承载系统内消息，字段包括 `id`、`user_id`（接收人）、`type`（如 `new_order`/`order_updated`）、`title`、`content`、`related_order_id`、`is_read`、`created_at`。

### 后端逻辑
- **订单创建/修改时派发通知**：在 `batch_create_orders` 与订单更新流程中，遍历 `OrderItem.product.factory`，对每个 `factory=贝乐` 的订单，向所有 `User.factory=贝乐` 的用户插入一条 `notification` 记录。
- **订单列表 API 增加工厂过滤**：`GET /orders` 支持 `factory` 查询参数；当请求用户 `factory` 非空时，**强制**按该工厂过滤（权限隔离，前端传参被忽略）。
- **订单创建信息校验**：提交时校验贝乐相关 SKU 的 `product.factory` 必须有值，否则拒绝并提示「产品 X 未配置工厂，无法分配订单」。
- **订单修改追踪通知**：订单更新接口在保存后，若涉及贝乐 SKU 行变更，向贝乐用户推送 `order_updated` 通知。

### 前端
- **订单列表页新增「工厂」筛选**：管理员可手动选择滨发/贝乐/全部；贝乐用户登录后筛选器锁定为「贝乐」且不可更改。
- **订单列表新增「工厂」列**：从 `items[*].product.factory` 聚合显示。
- **顶部铃铛通知中心**：新增通知图标 + 未读数徽标，点击展开通知列表，支持已读/全部已读。

### 权限隔离
- **贝乐用户（`User.factory=贝乐`）**：订单列表强制仅显示本厂订单；产品/库存等其他模块保持现有权限，不做隔离（按用户决策）。
- **管理员（`User.factory=NULL` 或 `is_super=true`）**：可查看所有工厂订单，可手动筛选。

### 日志与同步
- **操作日志复用 `AuditLog`**：订单创建/修改/查看的关键操作已由现有 `AuditLog` 中间件记录，本方案不重复造轮子，仅在通知派发时补充 `resource_type=notification` 的审计记录。
- **定时任务**：新增轻量定时任务，每 10 分钟扫描 `notification` 表中 `is_read=false` 且超过 30 分钟未读的贝乐相关通知，做一次「未读提醒」聚合（可选，MVP 可先不做）。

### 不做（明确排除）
- **不做邮件/短信/FCM 推送**：MVP 阶段仅做系统内消息，后续按需扩展。
- **不做外部系统数据同步**：贝乐工厂使用本系统，无需对接外部 ERP。
- **不隔离产品/库存等其他模块**：仅订单列表做工厂隔离。
- **不重构订单状态机**：现有 `compute_status_from_stockouts` 等逻辑保持不变。

## Impact

- **Affected specs**:
  - `order_management_update`：订单列表新增工厂筛选与工厂列，与现有抵扣备货功能正交。
  - `multi-sku-order-aggregation`：复用 `OrderItem.product.factory` 关联，不修改聚合逻辑。
  - `beile-factory-product-field`（前序已实施）：`Product.factory` 字段为本方案的基础。

- **Affected code**:
  - 后端模型：[shared_models/user.py](file:///d:/erp_system/fastapi_app/shared_models/user.py)（加 factory）、新增 [shared_models/notification.py](file:///d:/erp_system/fastapi_app/shared_models/notification.py)
  - 后端服务：[services/order_batch_create.py](file:///d:/erp_system/fastapi_app/services/order_batch_create.py)（通知派发）、订单更新服务、订单列表查询服务（工厂过滤）
  - 后端 API：[api/v1/endpoints/order.py](file:///d:/erp_system/fastapi_app/api/v1/endpoints/order.py)（工厂查询参数）、新增通知 API
  - 前端：订单列表页（工厂筛选 + 工厂列）、顶部导航（通知铃铛）、新增通知 API 客户端
  - 迁移：新增 `add_user_factory_and_notification.py` Alembic 脚本

## ADDED Requirements

### Requirement: 用户工厂标识

系统 SHALL 允许为每个用户分配一个工厂标识（滨发/贝乐/无），用于订单权限隔离与通知派发。

#### Scenario: 管理员为用户分配工厂
- **WHEN** 管理员在用户编辑页面将某用户的工厂设为「贝乐」
- **THEN** 该用户 `User.factory` 更新为「贝乐」，保存成功

#### Scenario: 未分配工厂的用户
- **WHEN** 用户记录的 `factory` 字段为 NULL
- **THEN** 该用户被视为跨厂管理员，可查看所有工厂的订单

### Requirement: 系统内消息通知

系统 SHALL 在创建或修改包含贝乐工厂 SKU 的订单时，向所有 `factory=贝乐` 的用户派发一条系统内消息。

#### Scenario: 创建包含贝乐 SKU 的订单
- **GIVEN** 系统中存在 2 名 `factory=贝乐` 的用户
- **WHEN** 操作员提交一个订单，其某个 `OrderItem.product.factory=贝乐`
- **THEN** 系统为这 2 名贝乐用户各插入 1 条 `type=new_order` 的 `notification` 记录，`related_order_id` 指向新订单，`is_read=false`
- **AND** 通知内容包含订单号、客户名、贝乐相关 SKU 名称与数量

#### Scenario: 修改贝乐相关订单
- **WHEN** 操作员修改一个包含贝乐 SKU 的订单（数量变更、新增/删除 SKU 行等）
- **THEN** 系统向贝乐用户派发 `type=order_updated` 通知，内容包含变更摘要

#### Scenario: 订单不含贝乐 SKU
- **WHEN** 操作员提交一个所有 SKU 均为「滨发」的订单
- **THEN** 系统不向贝乐用户派发任何通知

### Requirement: 通知中心

系统 SHALL 在前端顶部导航提供通知铃铛入口，展示当前用户的未读消息。

#### Scenario: 贝乐用户查看未读通知
- **GIVEN** 贝乐用户有 3 条未读通知
- **WHEN** 用户点击顶部铃铛图标
- **THEN** 展开通知列表，显示 3 条未读消息（标题、摘要、时间），铃铛图标显示数字「3」

#### Scenario: 标记通知已读
- **WHEN** 用户点击某条通知或「全部已读」按钮
- **THEN** 对应通知 `is_read=true`，铃铛未读数相应减少

### Requirement: 订单工厂筛选与隔离

系统 SHALL 在订单列表页提供工厂筛选能力，并根据当前用户的工厂标识强制隔离。

#### Scenario: 管理员筛选贝乐订单
- **GIVEN** 当前用户 `factory=NULL`（管理员）
- **WHEN** 用户在筛选器选择「贝乐」
- **THEN** 订单列表仅显示包含贝乐 SKU 的订单

#### Scenario: 贝乐用户被强制隔离
- **GIVEN** 当前用户 `factory=贝乐`
- **WHEN** 用户打开订单列表页
- **THEN** 筛选器锁定为「贝乐」且不可更改，列表仅显示贝乐相关订单，即使前端尝试传 `factory=滨发` 也被后端强制覆盖为「贝乐」

### Requirement: 订单创建工厂校验

系统 SHALL 在订单创建时校验每个 SKU 的 `product.factory` 必须有值。

#### Scenario: SKU 缺少工厂配置
- **WHEN** 操作员提交一个订单，其中某 SKU 的 `product.factory` 为 NULL
- **THEN** 系统拒绝创建，返回错误「产品 {name} 未配置工厂，无法分配订单，请先在产品管理中补充工厂字段」

## MODIFIED Requirements

### Requirement: 订单列表展示

在现有订单列表基础上，新增「工厂」列，由 `OrderItem.product.factory` 聚合得出。一个订单包含多厂 SKU 时，显示为「贝乐, 滨发」等逗号分隔形式。

#### Scenario: 订单含多厂 SKU
- **WHEN** 一个订单包含 1 个滨发 SKU 和 1 个贝乐 SKU
- **THEN** 订单列表「工厂」列显示「滨发, 贝乐」

#### Scenario: 订单 SKU 工厂未配置
- **WHEN** 订单的某个 SKU `product.factory` 为 NULL
- **THEN** 工厂列显示「-」或「未配置」

## REMOVED Requirements

### Requirement: 邮件/短信/FCM 通知
**Reason**: MVP 阶段优先实现系统内消息，避免引入 SMTP、短信服务商、FCM 配置等外部依赖。用户决策已确认仅做系统内消息。
**Migration**: 后续如需扩展，可在通知派发点增加 `channel` 分发器，复用现有 `DeviceToken` 表做 FCM 推送，邮件/短信按需新增 provider。

### Requirement: 外部系统数据同步
**Reason**: 贝乐工厂使用本系统，无独立外部 ERP，无需 API/Webhook 同步。用户决策已确认仅本系统内可见性。
**Migration**: 无。
