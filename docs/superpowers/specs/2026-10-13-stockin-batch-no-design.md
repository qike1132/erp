# 备货记录批次号 — 设计（/batch 页订单/备货统一按订单处理）

- 日期：2026-10-13
- 状态：待评审
- 相关页面：`/batch`（批次查询）
- 相关文件：`frontend-vite/src/views/batch/*`、`fastapi_app/services/order_batch_service.py`、`fastapi_app/shared_models/stock_in.py`

## 1. 背景与目标

`/batch` 页把「订单(Order)」和「备货(StockIn)」两路记录 union 后按客户分组展示。当前只有**订单 chip** 有批次号输入框和「完成」按钮；**备货 chip 只读**（后端 `StockIn` 没有批次字段，序列化时 `batch_no` 恒为 `None`）。

目标：**在这个路由里不再区分订单/备货，所有记录一律按订单处理** —— 每条记录（无论来源）都能填批次号、都能点「完成」，且共用同一套批次号。

用户确认的取舍：
- 批次号是**同一套**（订单与备货共用一个批次号空间）。
- 「完成」时**备货记录本身也要被标记为批次完成**（给 `StockIn` 加完成字段）。

## 2. 范围

**做**
- `stock_in` 表新增批次相关列（对齐 Order）。
- 后端：备货序列化带上批次字段；保存批次号支持备货；`complete_batch` 同时完成备货；按批次号筛选时订单+备货一起出。
- 前端：所有 chip 渲染批次号输入框 + 完成按钮；保存调用带 `record_type`。
- 迁移 + 回归测试。

**不做**
- 不改 `/order-batch/orders`、`/order-batch/history`（批次页未使用，保持订单专属）。
- 不引入 `StockIn` 的 `sync_same_batch`（备货无此语义）。
- 不做备货的「锁定(is_locked)」概念（沿用 `None`）。

## 3. 数据模型

`stock_in` 新增三列，逐字段对齐 `order`（见 [order.py:80-86](../../../fastapi_app/shared_models/order.py)）：

| 列 | 类型 | 说明 |
|---|---|---|
| `batch_no` | `String(100)`，nullable | 批次号 |
| `batch_completed_at` | `DateTime`，nullable | 批次完成时间 |
| `batch_completed_by_id` | `Integer`，FK `user.id ON DELETE SET NULL`，nullable | 完成操作人 |

索引：`idx_stockin_batch_no`（对齐 `idx_order_batch_no`）。

Alembic：新增一个迁移（**单 head**）。生成方式遵循仓库铁律 —— **不对生产库 autogenerate**；在**临时空库** `upgrade head` 后改模型再 autogenerate，判据同 CI（空库 `upgrade head` + `alembic check`）。迁移只做结构变更，不夹带业务逻辑。

## 4. 后端（`order_batch_service.py`）

### 4.1 序列化
`_serialize_batch_stockins`：把写死的 `batch_no=None` / `batch_completed_at=None` / `is_locked=None` 改为读真实列；`status` 在 `batch_completed_at` 非空时返回 `'批次已完成'`（否则 `None`），使 chip 能像订单一样显示完成态。`is_locked` 维持 `None`。

### 4.2 保存批次号（API 形态 A）
沿用 `PUT /order-batch/orders/{record_id}/batch-no`，请求体新增 `record_type`（`'order' | 'stockin'`，**默认 `'order'`，向后兼容**）。

`update_batch_no(db, *, record_id, record_type, batch_no, sync_same_batch, user)`：
- `record_type == 'order'`：原逻辑不变。
- `record_type == 'stockin'`：`SELECT ... FOR UPDATE` 锁定 `StockIn.id == record_id`，写 `batch_no`，审计（detail 标注 `record_type=stockin`）+ 发 `batch_no_updated` 事件。不处理 `sync_same_batch`。
- 记录不存在 → `ValueError`（同订单路径）。

> 端点参数名从 `order_id` 泛化为 `record_id`（路径不变，避免破坏其它调用方）。

### 4.3 完成批次
`complete_batch(db, *, batch_no, user)`：
- 订单：原逻辑（仅「已出货」订单可完成，未出货计入 `failed_orders`）。
- **新增**：把 `batch_no` 下 `batch_completed_at IS NULL` 的备货一并标记 `batch_completed_at=now`、`batch_completed_by_id=user.id`（备货无出货状态，**无条件完成**）。
- 审计 `batch_complete` 与 `batch_completed` 事件带上备货计数（如 `completed_stockins`）。
- 若订单与备货都为空 → 仍抛 `ValueError`。

### 4.4 按批次筛选
`_build_batch_stockin_branch`：补 `if batch_no: where(StockIn.batch_no == batch_no)`（原来备货分支不按批次号过滤），使「按批次号筛选」订单+备货一起返回。

## 5. 前端（`BatchGroupList.vue` + 类型/接口）

- 去掉 `<template v-if="order.record_type !== 'stockin'">` —— **所有 chip** 都渲染批次号输入框；「完成」按钮沿用现状的显示条件 `v-if="order.batch_no"`（即批次号非空才出现），对订单与备货一致。
- 编辑态 key 由 `order.id` 改为 **`record_type + ':' + order.id` 复合**（订单/备货 id 可能撞号，防串扰；与 `:key` 的复合键一致）。
- 保存时按记录类型调用：`orderBatchApi.updateBatchNo(order.id, { batch_no, record_type })`。
- `BatchNoUpdatePayload` 增加可选 `record_type`（默认 `'order'`）。
- chip 完成态配色沿用现有 `chipStatusClass`（备货完成时 `status='批次已完成'` → 走 `bt-chip--completed`）。

## 6. 边界与风险

- **id 撞号**：订单与备货来自不同表，`id` 可能相同 → 前端一切按记录定位处（`:key`、编辑态、保存）都用 `record_type:id` 复合键。
- **完成前置**：订单需「已出货」；备货无条件完成（无状态）。混合批次完成时，未出货订单进 `failed_orders`，备货照常完成。
- **迁移**：必须临时空库生成；新增列全部 nullable，对存量数据安全（老备货 `batch_no` 为 NULL）。
- **并发**：保存走行级锁（`FOR UPDATE`），与订单路径一致。

## 7. 测试

- 后端：
  - `update_batch_no(record_type='stockin')` 正确写 `StockIn.batch_no`；不存在则报错。
  - `complete_batch` 同时完成该批次备货并计数；订单未出货仍进 `failed_orders`。
  - `_serialize_batch_stockins` 返回真实 `batch_no`/完成态。
  - `_build_batch_stockin_branch` 带 `batch_no` 过滤。
  - 迁移安全（空库 `upgrade head` + `check`；无破坏性 DDL）。
- 前端：
  - 备货 chip 渲染输入框 + 完成按钮。
  - 保存调用带 `record_type='stockin'`。
  - 订单/备货 id 撞号时编辑互不串扰。

## 8. 交付

- 一次任务、一个提交（迁移 + 后端 + 前端 + 测试）；评审按仓库规矩攒到推送前一次。
- 部署：迁移先上（nullable，安全），再上前端。
