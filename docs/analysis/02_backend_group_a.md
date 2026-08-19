# 后端代码质量审查报告 - A组(采购域+订单域)

> 审查时间：2026-08-18
> 审查范围：采购中心、供应商管理、客户订单、湖北订单、湖北外发、订单查询、订单流水、批次号查询
> 审查方式：批量行数统计 + grep 模式扫描 + 大文件关键片段抽样
> 技术栈：FastAPI + SQLAlchemy 2.0 + asyncpg + Pydantic 2.13

## 审查概览

| 模块 | 文件数 | 总行数 | 风险等级 | 主要问题数 |
|------|--------|--------|----------|------------|
| 一、采购中心 | 14 | 4295 | **中** | 8 |
| 二、供应商管理 | 2 | 439 | **低** | 2 |
| 三、客户订单 | 4 | 1383 | **高** | 9 |
| 四、湖北订单 | (并入客户订单) | - | - | - |
| 五、湖北外发 | 2 | 828 | **中** | 4 |
| 六、订单查询 | 3 | 894 | **中** | 5 |
| 七、订单流水 | 2 | 280 | **低** | 2 |
| 八、批次号查询 | 4 | 1526 | **高** | 7 |
| 辅助服务 | 4 | 425 | **低** | 3 |
| **合计** | **35** | **11070** | — | **40** |

> 说明：湖北订单模块已合并至客户订单（共享 order_crud/order_service），不单独列章节。
> 总行数含 facade re-export 文件（purchase_center_service.py、batch_service.py 等）。

---

## 一、采购中心

### 1.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except | 备注 |
|------|------|------------|------------|------|
| services/purchase_center_service.py | 143 | 5/1 | 2/2 | Facade 重导出 |
| services/purchase_order_crud.py | 399 | 10/2 | 3/3 | 写操作 |
| services/purchase_order_generate.py | 280 | 3/2 | 1/1 | 一键生成 |
| services/purchase_order_query.py | **1298** | 22/27 | 0/0 | 读操作，⚠️大文件 |
| services/purchase_order_service.py | 62 | 0/0 | 0/0 | Facade |
| services/purchase_plan_crud.py | **1225** | 46/17 | 10/10 | ⚠️大文件 |
| services/purchase_plan_service.py | 190 | 1/2 | 3/3 | Facade |
| services/purchase_product_service.py | 287 | 6/1 | 1/1 | 产品/BOM |
| services/purchase_customer_service.py | 94 | 5/0 | 0/0 | 客户管理 |
| services/purchase_history_service.py | 87 | 6/0 | 0/0 | 历史日志 |
| services/purchase_bom_copy_service.py | 142 | 3/0 | 0/0 | BOM 复制 |
| services/purchase_utils.py | 29 | 0/1 | 1/1 | 工具函数 |
| api/v1/endpoints/purchase_plan.py | 481 | 21/1 | 13/25 | 端点 |
| api/v1/endpoints/purchase_center/order_routes.py | **587** | 22/0 | 14/17 | ⚠️大文件 |
| api/v1/endpoints/purchase_center/product_routes.py | 273 | 11/0 | 8/8 | 端点 |
| api/v1/endpoints/purchase_center/customer_routes.py | 176 | 5/0 | 5/5 | 端点 |
| api/v1/endpoints/purchase_center/export_utils.py | 315 | 0/11 | 0/0 | 导出工具 |
| api/v1/endpoints/purchase_center/print_routes.py | 131 | 2/1 | 2/3 | 打印 |
| api/v1/endpoints/purchase_center/misc_routes.py | 49 | 6/0 | 1/1 | 杂项 |
| api/v1/endpoints/purchase_center/schemas.py | 79 | 0/0 | 0/0 | Pydantic 模型 |

### 1.2 代码规范

- ✅ **import 顺序**：所有文件遵循标准库 → 第三方 → 应用内三层分组，符合 PEP8。
- ✅ **snake_case 命名**：函数与变量统一使用 snake_case，符合规范。
- ✅ **模块 docstring**：每个服务文件顶部均有职责说明 docstring，且明确标注拆分来源（"从 purchase_center_service.py 拆分"）。
- ⚠️ **行长度**：purchase_plan.py 端点存在单行 200+ 字符的函数签名（如 line 58 `list_plans`），虽可读但超出 PEP8 79 字符建议。
- ⚠️ **purchase_order_query.py** 内部存在 27 个同步函数 + 22 个异步函数混用，需确认是否为序列化辅助函数（同步）与 DB 查询函数（异步）的合理分层。

### 1.3 注释覆盖率

| 文件 | docstring 数 | 注释行 | 估算覆盖率 |
|------|--------------|--------|------------|
| purchase_order_query.py | 12 | 39 | **2.8%** ⚠️偏低 |
| purchase_plan_crud.py | 51 | 32 | 12.6% ✅ |
| purchase_order_crud.py | 5.5 | 13 | 4.1% ⚠️ |
| purchase_order_generate.py | 5 | 18 | 5.4% |
| purchase_product_service.py | 2 | 4 | **2.1%** ⚠️偏低 |
| purchase_center_service.py | 6.5 | 7 | 13.6% ✅ |

**结论**：purchase_order_query.py（1298 行仅 12 个 docstring）和 purchase_product_service.py 注释覆盖率偏低，建议补充关键查询函数的 docstring。

### 1.4 命名合理性

- ✅ 函数命名清晰：`get_plan_list`、`create_purchase_order`、`batch_complete_purchase_orders` 等动词+名词结构。
- ✅ 私有辅助函数以 `_` 前缀：`_fetch_bom_data`、`_parse_source_order_ids`、`_create_material_registration`。
- ✅ 常量大写：`INVENTORY_CACHE_PREFIX`、`SHIPMENT_RECORD_LOOKBACK_MONTHS`。
- ⚠️ `purchase_order_query.py` 内 `_parse_source_order_ids` 与 `purchase_utils.parse_source_order_ids` 同名，虽职责互补但易混淆。

### 1.5 圈复杂度（>10 的函数候选）

基于 if/elif/for/while/and/or 统计估算：

| 文件 | if | elif | for | while | and | or | 估算总复杂度 |
|------|----|------|-----|-------|-----|-----|--------------|
| purchase_order_query.py | 92 | 0 | 54 | 0 | 10 | 108 | **~264** 🔴 |
| purchase_plan_crud.py | 106 | 2 | 44 | 0 | 12 | 26 | **~190** 🔴 |
| purchase_order_crud.py | 33 | 0 | 12 | 0 | 1 | 20 | ~66 🟡 |
| purchase_order_generate.py | 18 | 0 | 18 | 0 | 0 | 24 | ~60 🟡 |

**高风险函数**（建议拆分）：
- `purchase_order_query.py`：22 个 async + 27 个 sync 函数分布在 1298 行，平均每函数 ~27 行，但 `or` 操作符 108 次表明存在大量复合条件查询拼接，单个查询构建函数可能超过 50 行。
- `purchase_plan_crud.py`：46 个 async 函数 / 1225 行，平均 ~26 行/函数，但 `if` 106 次表明业务分支密集，FIFO 分配、暂存区确认、出货重算等函数 likely 圈复杂度 > 15。

### 1.6 代码重复

- ✅ 已通过 facade 模式拆分原始 1922 行 God File（purchase_center_service.py 注释明确记录）。
- ✅ `purchase_utils.py` 提取了 `parse_source_order_ids` 等共享工具。
- ⚠️ `purchase_order_query.py` 与 `order_crud.py` 均各自实现 `_parse_source_order_ids`（前者委托后者），存在薄包装层冗余。
- ⚠️ `purchase_center/order_routes.py` 中 4 处 `try: await db.rollback() except Exception` 防御性 rollback 模式重复（line 147/160/167/173），可提取为 `_safe_rollback(db, context)` 辅助函数。

### 1.7 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| 多 SKU 兼容值 TODO | purchase_order_query.py:185,466,774,871 | `Order.product_id/quantity` 在多 SKU 模型下为首 item 兼容值，4 处 TODO 标记待 spec 改造 | 🟡 中 |
| 防御性 rollback 重复 | order_routes.py:147,160,167,173 | 4 处 `except Exception` 捕获 rollback 失败，虽为防御性设计但吞没异常细节 | 🟢 低 |
| 异步会话独立提交 | purchase_plan_crud.py:131 | `await short_session.commit()` 独立短会话事务，需确认 advisory lock 释放时机 | 🟢 低 |
| Any 类型滥用 | order_routes.py:7 | `from typing import Any` 导入但未在端点层强类型化请求/响应 | 🟢 低 |

### 1.8 风险等级评估

**模块风险：中** 🔶
- 主要风险集中在 purchase_order_query.py（1298 行、注释稀疏、多 SKU TODO 4 处）和 purchase_plan_crud.py（1225 行、高圈复杂度）。
- 无 SQL 注入风险（未发现 text() + f-string 拼接）。
- 异常处理总体规范，防御性 except 均有注释说明。

---

## 二、供应商管理

### 2.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except |
|------|------|------------|------------|
| services/purchase_supplier_service.py | 189 | 6/0 | 0/0 |
| api/v1/endpoints/supplier.py | 250 | 8/0 | 4/8 |

### 2.2 代码规范

- ✅ import 顺序规范，snake_case 命名统一。
- ✅ supplier.py 端点缓存键命名清晰：`SUPPLIER_LIST_CACHE_PATTERN`、`SUPPLIER_LIST_CACHE_TTL`。
- ✅ 使用 `escape_like` 防止 LIKE 注入（line 39）。

### 2.3 注释覆盖率

| 文件 | docstring | 注释行 | 覆盖率 |
|------|-----------|--------|--------|
| purchase_supplier_service.py | 2.5 | 7 | 4% ⚠️ |
| supplier.py | — | — | 中等 |

### 2.4 命名合理性

- ✅ `get_supplier_for_update` 明确表达悲观锁语义。
- ✅ `_invalidate_supplier_caches`、`_get_cached_supplier_list` 私有辅助命名清晰。

### 2.5 圈复杂度

| 文件 | if | for | and | or | 估算 |
|------|----|-----|-----|-----|------|
| purchase_supplier_service.py | 14 | 2 | 0 | 13 | ~29 🟡 |
| supplier.py | — | — | — | — | 中等 |

`or` 13 次主要来自多字段搜索条件拼接，单函数复杂度可控。

### 2.6 代码重复

- ✅ 缓存失效逻辑集中至 `_invalidate_supplier_caches`。
- ⚠️ `get_suppliers` 中 `query` 与 `count_query` 双查询构建存在条件重复（search 分支同时修改两个 query）。

### 2.7 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| 无异常处理 | purchase_supplier_service.py | 6 个 async 函数 try/except=0/0，DB 异常未捕获，依赖端点层兜底 | 🟢 低（设计如此） |
| 缓存键一致性 | supplier.py:36 | 注释强调必须包含 CACHE_KEY_PREFIX，表明曾存在键不一致 bug | 🟢 低 |

### 2.8 风险等级评估

**模块风险：低** 🟢
- 文件规模小、职责单一、无 SQL 拼接、异常处理由端点层统一兜底。

---

## 三、客户订单

### 3.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except | 备注 |
|------|------|------------|------------|------|
| services/order_service.py | 56 | 0/0 | 0/0 | Facade |
| services/order_crud.py | **953** | 24/7 | 4/4 | ⚠️大文件 |
| services/order_utils.py | 35 | 2/0 | 0/0 | 工具 |
| api/v1/endpoints/order.py | 339 | 11/0 | 5/9 | 端点 |

### 3.2 代码规范

- ✅ 模块 docstring 详尽，order_crud.py 顶部明确记录多 SKU TODO 改造计划。
- ✅ import 分组清晰，使用 `from fastapi_app.core.exceptions import BusinessError, NotFoundError` 等领域异常。
- ✅ `PermissionDeniedError` 自定义异常类有 docstring。
- ⚠️ order_crud.py line 105 `pass` 在 class 体中（`PermissionDeniedError`），虽为空异常类标准写法但可加 `# noqa`。

### 3.3 注释覆盖率

| 文件 | docstring | 注释行 | 覆盖率 |
|------|-----------|--------|--------|
| order_crud.py | 17 | 50 | 5.4% |
| order_utils.py | 2 | 2 | 17.1% ✅ |
| order_service.py | 1 | 1 | 5.4% |

### 3.4 命名合理性

- ✅ `get_order_by_id`、`_log_background_task_exception`、`compute_order_status_from_db` 命名清晰。
- ✅ 后台任务异常回调 `_log_background_task_exception` 明确表达 fire-and-forget 防静默失败意图。

### 3.5 圈复杂度

| 文件 | if | elif | for | while | and | or | 估算 |
|------|----|------|-----|-------|-----|-----|------|
| order_crud.py | 65 | 1 | 10 | 0 | 9 | 13 | **~98** 🟡 |

24 个 async 函数 / 953 行，平均 ~40 行/函数，部分函数（如 update_order、deduct_order）likely 圈复杂度 > 15。

### 3.6 代码重复

- ✅ 已拆分至 order_utils.py、order_batch_create.py、order_deduction_service.py。
- ⚠️ order_crud.py 顶部 TODO 注释 7-10 行与 line 642/654 重复同一多 SKU 警告。

### 3.7 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| 多 SKU 兼容值 TODO | order_crud.py:7,642,654 | `order.product_id/quantity/order_type/country` 直接读写，多 SKU 下为首 item 兼容值，**核心业务逻辑风险** | 🔴 高 |
| 多 SKU TODO | order.py:242 | 端点层同样依赖首 item 兼容值 | 🟡 中 |
| 后台任务异常回调 | order_crud.py:97-100 | `_log_background_task_exception` 防止 fire-and-forget 静默失败，设计良好 | ✅ 正面 |
| 领域事件发布失败吞没 | order.py:309 | `except Exception: # defensive: 领域事件发布失败不影响删除操作结果`，可能掩盖事件总线故障 | 🟡 中 |
| 缓存失效时机 | order_crud.py:647-651 | dashboard 缓存失效移至 endpoint 层，注释说明事务提交后失效，需确认一致性 | 🟢 低 |

### 3.8 风险等级评估

**模块风险：高** 🔴
- **核心风险**：order_crud.py 3 处多 SKU TODO 直接读写 `order.product_id/quantity`，在多 SKU 订单模型下为首 item 兼容值，库存抵扣、订单更新等核心业务逻辑可能产生数据错误。
- order.py 端点层领域事件发布失败被防御性吞没，可能影响前端实时刷新。

---

## 四、湖北订单

> 湖北订单模块已合并至客户订单域，共享 `order_crud.py`、`order_service.py`、`order.py` 端点。
> 湖北订单的特殊逻辑（如 `factory='湖北'` 筛选、`beile_unconfirmed` 通知）分布在：
> - `order_crud.py`：`dispatch_beile_unconfirmed_notifications` 调用
> - `order_batch_create.py:271-278`：批量创建时派发湖北未确认提醒
> - `outsource_service.py`：湖北外发工序管理
>
> **风险等级：随客户订单，高** 🔴

---

## 五、湖北外发

### 5.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except |
|------|------|------------|------------|
| services/outsource_service.py | 597 | 18/6 | 1/1 |
| api/v1/endpoints/outsource.py | 231 | 13/0 | 9/9 |

### 5.2 代码规范

- ✅ 模块 docstring 详尽（职责、SKU 工序预设、返单自动带出、进度看板）。
- ✅ 权限注释清晰：`outsource_view`、`outsource_manage`。
- ✅ 序列化辅助函数 `_fmt_dt`、`_serialize_process_type`、`_serialize_order_process` 命名规范。

### 5.3 注释覆盖率

| 文件 | docstring | 注释行 | 覆盖率 |
|------|-----------|--------|--------|
| outsource_service.py | 16.5 | 14 | 8.3% ✅ |

### 5.4 命名合理性

- ✅ `auto_generate_for_order`、`_fmt_dt`、`_serialize_process_type` 命名清晰。
- ✅ `_fmt_dt` 处理 naive UTC datetime 的边界情况有 docstring 说明。

### 5.5 圈复杂度

| 文件 | if | elif | for | while | and | or | 估算 |
|------|----|------|-----|-------|-----|-----|------|
| outsource_service.py | 57 | 2 | 14 | 0 | 2 | 18 | **~93** 🟡 |

18 个 async 函数 / 597 行，平均 ~33 行/函数，看板聚合与状态流转函数 likely 圈复杂度 > 10。

### 5.6 代码重复

- ✅ 序列化逻辑集中至 `_serialize_*` 函数。
- ⚠️ outsource.py 端点 9 个 try/except 模式与 order.py 端点相似，可考虑提取统一异常处理装饰器。

### 5.7 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| 返单自动带出失败 | order_crud.py:644-645 | `auto_generate_for_order` 失败不影响订单创建（注释说明），但可能掩盖外发工序配置错误 | 🟡 中 |
| 状态流转校验 | outsource_service.py | 需确认 `can_transition` 状态机校验是否覆盖所有状态流转路径 | 🟢 低 |

### 5.8 风险等级评估

**模块风险：中** 🔶
- 文件规模适中，异常处理规范，主要风险在于返单自动带出的容错设计可能掩盖配置错误。

---

## 六、订单查询

### 6.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except |
|------|------|------------|------------|
| services/order_batch_service.py | 419 | 12/3 | 2/2 |
| services/order_batch_create.py | 270 | 1/0 | 8/10 |
| api/v1/endpoints/order_batch.py | 205 | 8/0 | 0/0 |

### 6.2 代码规范

- ✅ order_batch_service.py 顶部 TODO 注释详细说明 event_bus 未迁移至 domain_events 的原因（WebSocket + FCM 实时推送能力）。
- ✅ order_batch_create.py docstring 明确说明多 SKU 按 customer 聚合策略。
- ✅ `_SavepointRollbackSignalError` 自定义信号异常有 docstring。

### 6.3 注释覆盖率

| 文件 | docstring | 注释行 | 覆盖率 |
|------|-----------|--------|--------|
| order_batch_service.py | 1.5 | 21 | **1.1%** ⚠️偏低 |
| order_batch_create.py | 3 | 23 | 3.3% ⚠️ |

### 6.4 命名合理性

- ✅ `_write_audit_log`、`get_whitelist`、`batch_create_orders` 命名清晰。
- ✅ `_get_redis_client` 私有辅助函数命名规范。

### 6.5 圈复杂度

| 文件 | if | elif | for | while | and | or | 估算 |
|------|----|------|-----|-------|-----|-----|------|
| order_batch_service.py | 36 | 0 | 7 | 0 | 3 | 6 | ~52 🟡 |
| order_batch_create.py | 7 | 0 | 8 | 0 | 3 | 4 | ~22 ✅ |

### 6.6 代码重复

- ✅ 批量创建逻辑已拆分至 order_batch_create.py。
- ⚠️ order_batch_create.py:270-293 异常处理分层（`_SavepointRollbackSignalError` → `ValueError/TypeError/OSError` → `SQLAlchemyError`）设计良好但复杂，需确保所有异常路径都正确回滚。

### 6.7 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| 多 SKU keyword 搜索 TODO | order_batch_service.py:3 | JOIN Product, Order.product_id == Product.id 按首 item 过滤，多 SKU 下无法匹配非首 item | 🟡 中 |
| 通知派发失败吞没 | order_batch_create.py:274 | `except Exception as notify_err` 捕获湖北未确认提醒派发失败，记录 warning 但继续 | 🟢 低 |
| savepoint 回滚信号 | order_batch_create.py:280 | `pass` 吞没 `_SavepointRollbackSignalError`，虽为设计意图但需确认 savepoint 已自动回滚 | 🟢 低 |
| Redis 客户端获取 | order_batch_service.py:32-38 | `_get_redis_client` 失败返回 None，调用方需 None 检查 | 🟢 低 |
| event_bus 迁移阻塞 | order_batch_service.py:16-20 | 注释说明 event_bus 未迁移至 domain_events 的技术原因，存在架构债务 | 🟡 中 |

### 6.8 风险等级评估

**模块风险：中** 🔶
- 多 SKU keyword 搜索 TODO 与 event_bus 架构债务是主要风险。
- 批量创建异常处理分层设计良好但复杂。

---

## 七、订单流水

### 7.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except |
|------|------|------------|------------|
| services/order_deduction_service.py | 111 | 1/0 | 1/2 |
| services/order_purchase_sync.py | 169 | 3/0 | 1/1 |

### 7.2 代码规范

- ✅ order_deduction_service.py docstring 明确说明拆分目的（消除循环依赖）。
- ✅ order_purchase_sync.py docstring 详尽（核心设计、创建/删除/更新同步）。
- ✅ 使用 `Decimal` 处理金额（order_purchase_sync.py:16）。

### 7.3 注释覆盖率

| 文件 | docstring | 注释行 | 覆盖率 |
|------|-----------|--------|--------|
| order_deduction_service.py | 2 | 6 | 5.4% |
| order_purchase_sync.py | 4 | 7 | 7.1% ✅ |

### 7.4 命名合理性

- ✅ `process_order_deduction`、`sync_order_create` 命名清晰。
- ✅ `sync_order_create` 参数明确：`order_id, order_no, customer, product_id, product_name, quantity`。

### 7.5 圈复杂度

| 文件 | if | for | and | or | 估算 |
|------|----|-----|-----|-----|------|
| order_deduction_service.py | 7 | 1 | 3 | 0 | ~11 ✅ |
| order_purchase_sync.py | 10 | 6 | 7 | 0 | ~23 ✅ |

### 7.6 代码重复

- ✅ order_deduction_service.py 消除了 order_service ↔ batch_service 循环依赖。
- ✅ FIFO 抵扣逻辑集中。

### 7.7 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| 同步跳过逻辑 | order_purchase_sync.py:43-45 | 已存在关联采购订单时跳过同步，需确认幂等性 | 🟢 低 |
| 延迟导入 | order_purchase_sync.py:48 | `from fastapi_app.shared_models import ProductMaterial` 函数内导入，可能为避免循环依赖 | 🟢 低 |

### 7.8 风险等级评估

**模块风险：低** 🟢
- 文件规模小、职责单一、圈复杂度低、无 SQL 拼接。

---

## 八、批次号查询

### 8.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except | 备注 |
|------|------|------------|------------|------|
| services/batch_service.py | 79 | 4/0 | 0/0 | Facade |
| services/batch_import_service.py | **1201** | 27/11 | 35/35 | ⚠️大文件 |
| services/batch_pipeline.py | 102 | 7/2 | 1/1 | Pipeline 基类 |
| api/v1/endpoints/batch.py | 144 | 8/0 | 0/0 | 端点 |

### 8.2 代码规范

- ✅ batch_service.py facade docstring 明确记录拆分职责。
- ✅ batch_pipeline.py 提供统一 Pipeline 基类抽象（parse → validate → persist 三阶段）。
- ✅ batch.py 端点 docstring 详尽（Args/Returns/Raises）。
- ⚠️ batch_import_service.py 35 个 try/except 块，异常处理密度最高，需确认每个 except 块的必要性。

### 8.3 注释覆盖率

| 文件 | docstring | 注释行 | 覆盖率 |
|------|-----------|--------|--------|
| batch_import_service.py | 27 | 35 | 6.7% ✅ |
| batch_service.py | 5 | 4 | 19% ✅ |
| batch_pipeline.py | 6.5 | 5 | 19.1% ✅ |

### 8.4 命名合理性

- ✅ `parse_excel_file_async`、`import_orders_from_data`、`process_order_import` 命名清晰。
- ✅ `BatchImportResult` dataclass 定义规范。
- ✅ `MAX_BATCH_UPLOAD_SIZE` 常量防 OOM 攻击。

### 8.5 圈复杂度

| 文件 | if | elif | for | while | and | or | 估算 |
|------|----|------|-----|-------|-----|-----|------|
| batch_import_service.py | 102 | 5 | 14 | 0 | 6 | 77 | **~204** 🔴 |

27 个 async + 11 个 sync 函数 / 1201 行，平均 ~32 行/函数。`or` 77 次表明大量条件分支，单个导入函数（如 `import_orders_from_data`）likely 圈复杂度 > 20。

### 8.6 代码重复

- ✅ batch_pipeline.py 提供统一基类，但 batch_import_service.py 27 个 async 函数未继承使用，存在架构债务。
- ⚠️ batch_import_service.py 内 35 个 try/except 块，部分异常处理模式重复（如 `except ValueError: return False`）。

### 8.7 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| 异常处理密度过高 | batch_import_service.py | 35 个 try/except，部分 except 可能吞没关键异常 | 🔴 高 |
| Pipeline 基类未应用 | batch_pipeline.py vs batch_import_service.py | 基类已定义但 27 个导入函数未继承，存在架构债务 | 🟡 中 |
| 悲观锁更新库存 | batch_import_service.py:275 | `get_product_for_update` 加锁后 `locked_product.current_stock += qty`，需确认锁释放时机 | 🟢 低 |
| 产品查找降级 | batch_import_service.py:247-248 | `product = product_map.get(...)` 两次查找（lower + 原始），可能掩盖数据不一致 | 🟢 低 |
| 临时文件清理 | batch_import_service.py | `cleanup_temp_file` 需确认在异常路径下也调用 | 🟡 中 |
| Excel 解析异常 | batch_import_service.py:58-60 | `_sync_parse` 内 `import math` 延迟导入，Polars 引擎降级逻辑需确认 | 🟢 低 |
| datetime 时区处理 | batch_import_service.py:265 | `datetime.now(UTC).replace(tzinfo=None)` 去 tzinfo，需确认数据库列类型一致性 | 🟡 中 |

### 8.8 风险等级评估

**模块风险：高** 🔴
- batch_import_service.py（1201 行、35 个 try/except、圈复杂度估算 ~204）是最高风险文件。
- Pipeline 基类未实际应用，架构债务明显。

---

## 九、辅助服务

### 9.1 文件清单与规模

| 文件 | 行数 | async/sync | try/except |
|------|------|------------|------------|
| services/base_search_service.py | 162 | 3/12 | 0/0 |
| services/enhanced_pagination.py | 114 | 3/1 | 1/1 |
| services/purchase_utils.py | 29 | 0/1 | 1/1 |
| services/order_utils.py | 35 | 2/0 | 0/0 |

### 9.2 代码规范

- ✅ base_search_service.py 通用搜索基类设计良好（Generic[T], ABC）。
- ✅ enhanced_pagination.py keyset 分页 + count 优化，OFFSET_THRESHOLD = 2000。
- ✅ 使用 `escape_like` 防 LIKE 注入。

### 9.3 注释覆盖率

| 文件 | docstring | 注释行 | 覆盖率 |
|------|-----------|--------|--------|
| base_search_service.py | 11 | 2 | 20.4% ✅ |
| enhanced_pagination.py | 4 | 3 | 10.5% ✅ |
| purchase_utils.py | 2 | 0 | 20.7% ✅ |
| order_utils.py | 2 | 2 | 17.1% ✅ |

### 9.4 潜在缺陷

| 缺陷类型 | 位置 | 描述 | 严重度 |
|----------|------|------|--------|
| Any 类型滥用 | enhanced_pagination.py:52,53,107,113,114 | `cursor_column: Any`、`cursor_value: Any` 应使用泛型或具体类型 | 🟡 中 |
| Any 类型滥用 | base_search_service.py:84,104,129,143,153,164 | `status_filter: Any \| None` 应使用泛型 T 或具体类型 | 🟡 中 |
| broad except | enhanced_pagination.py:40 | `except Exception` 捕获近似计数失败，降级精确计数，有注释说明 | 🟢 低 |

### 9.5 风险等级评估

**模块风险：低** 🟢
- 文件规模小、注释覆盖率高、设计良好。主要问题是 Any 类型滥用，建议引入泛型约束。

---

## 十、风险等级汇总

| 模块 | 风险等级 | 关键缺陷数 | Top 3 问题 |
|------|----------|------------|------------|
| 一、采购中心 | 🟡 中 | 8 | purchase_order_query.py 注释稀疏(2.8%)、多 SKU TODO 4 处、purchase_plan_crud.py 高圈复杂度 |
| 二、供应商管理 | 🟢 低 | 2 | 注释覆盖率偏低、query/count_query 条件重复 |
| 三、客户订单 | 🔴 高 | 9 | **多 SKU TODO 3 处直接读写 order.product_id/quantity**、领域事件发布失败吞没、order_crud.py 953 行 |
| 四、湖北订单 | 🔴 高 | (并入客户订单) | 随客户订单 |
| 五、湖北外发 | 🟡 中 | 4 | 返单自动带出容错可能掩盖配置错误、outsource_service.py 597 行 |
| 六、订单查询 | 🟡 中 | 5 | 多 SKU keyword 搜索 TODO、event_bus 架构债务、order_batch_service.py 注释稀疏(1.1%) |
| 七、订单流水 | 🟢 低 | 2 | 同步跳过幂等性、延迟导入 |
| 八、批次号查询 | 🔴 高 | 7 | **batch_import_service.py 35 个 try/except**、Pipeline 基类未应用、圈复杂度 ~204 |
| 辅助服务 | 🟢 低 | 3 | Any 类型滥用 |

---

## 十一、高风险模块详细说明

### 11.1 客户订单模块（高风险）

**核心风险：多 SKU 订单模型兼容值**

`order_crud.py` 顶部 TODO 注释（line 7-10）明确记录：
```
TODO(multi-sku-order): 本模块多处直接读写 order.product_id/order.quantity/order.order_type/
order.country（update/delete/deduct 等函数）。多 SKU 模型下这些为首 item 兼容值，
完整改造涉及业务语义变更（如多 item 下修改/扣减/删除影响哪个 item），风险高，
待后续 spec 改造为遍历 order.items。当前依赖 Task 3 设置的兼容值。
```

**影响范围**：
- `order_crud.py:642,654`：update/deduct 函数直接读写 `order.quantity`、`order.product_id`
- `order.py:242`：端点层读取 `order.quantity/order_type/country` 按首 item 兼容
- `purchase_order_query.py:185,466,774,871`：采购订单查询 4 处依赖首 item 兼容值
- `order_batch_service.py:3`：keyword 搜索 JOIN Product 按首 item 过滤

**建议**：
1. 优先级 P0：在多 SKU 订单上线前完成 spec 改造，遍历 `order.items` 替代首 item 兼容值。
2. 优先级 P1：添加运行时断言或日志，当 `len(order.items) > 1` 时警告首 item 兼容值可能不正确。
3. 优先级 P2：order.py:309 领域事件发布失败吞没，建议增加告警机制而非仅 warning 日志。

### 11.2 批次号查询模块（高风险）

**核心风险：batch_import_service.py 异常处理密度过高**

- 1201 行、35 个 try/except 块，平均每 34 行一个异常处理。
- 部分异常处理可能吞没关键错误（如 `except ValueError: return False` 在数据验证失败时静默返回）。
- `batch_pipeline.py` 已定义统一 Pipeline 基类（parse → validate → persist），但 27 个导入函数未继承使用，架构债务明显。

**建议**：
1. 优先级 P0：审计 35 个 except 块，确认每个异常处理是否记录日志或返回错误信息，避免静默吞没。
2. 优先级 P1：将 batch_import_service.py 中的导入函数逐步迁移至继承 `BatchImportPipeline` 基类。
3. 优先级 P2：拆分 batch_import_service.py 为 `order_import.py`、`stockin_import.py`、`stockout_import.py`、`product_import.py` 等子模块，每个 < 300 行。

### 11.3 采购中心模块（中风险）

**主要风险：大文件圈复杂度高**

- `purchase_order_query.py`（1298 行，22 async + 27 sync 函数）：`or` 操作符 108 次，查询条件拼接复杂。
- `purchase_plan_crud.py`（1225 行，46 async 函数）：`if` 106 次，业务分支密集。

**建议**：
1. 优先级 P1：purchase_order_query.py 按查询类型拆分为 `list_query.py`、`detail_query.py`、`summary_query.py`、`export_query.py`。
2. 优先级 P2：purchase_plan_crud.py 按业务操作拆分为 `plan_crud.py`、`staging.py`、`shipment_recalc.py`、`fifo.py`。
3. 优先级 P2：补充 purchase_order_query.py 关键查询函数 docstring（当前覆盖率 2.8%）。

---

## 十二、改进建议优先级矩阵

| 优先级 | 模块 | 改进项 | 预期收益 |
|--------|------|--------|----------|
| P0 | 客户订单 | 完成多 SKU spec 改造，消除首 item 兼容值 | 消除核心业务逻辑数据错误风险 |
| P0 | 批次号查询 | 审计 batch_import_service.py 35 个 except 块 | 防止关键异常静默吞没 |
| P1 | 批次号查询 | 迁移导入函数至 BatchImportPipeline 基类 | 统一异常处理、减少重复代码 |
| P1 | 采购中心 | 拆分 purchase_order_query.py（1298 行） | 降低单文件圈复杂度 |
| P1 | 订单查询 | 评估 event_bus → domain_events 迁移可行性 | 消除架构债务 |
| P2 | 采购中心 | 拆分 purchase_plan_crud.py（1225 行） | 降低单文件圈复杂度 |
| P2 | 客户订单 | 领域事件发布失败增加告警机制 | 防止事件总线故障被掩盖 |
| P2 | 辅助服务 | enhanced_pagination/base_search_service Any 类型改泛型 | 提升类型安全 |
| P3 | 采购中心 | 补充 purchase_order_query.py docstring | 提升可维护性 |
| P3 | 供应商管理 | 补充 purchase_supplier_service.py docstring | 提升可维护性 |

---

## 十三、审查方法论说明

### 13.1 高效分析策略

为避免逐行读取所有文件导致超时，本次审查采用：
1. **bash 批量统计**：`Get-Content | Measure-Object -Line` 统计所有目标文件行数。
2. **grep 批量搜索**：搜索 bare except、TODO/FIXME、SQL 拼接、Any 类型、pass in except 等关键模式。
3. **大文件抽样**：仅对 >500 行的 5 个大文件（purchase_order_query.py、purchase_plan_crud.py、batch_import_service.py、order_crud.py、outsource_service.py）读取前 50 行 + grep 定位问题行 ±10 行上下文。
4. **圈复杂度估算**：基于 if/elif/for/while/and/or 操作符计数估算，未使用 AST 精确计算。

### 13.2 审查覆盖度

- **文件覆盖**：35 个文件全部统计行数和函数数。
- **模式覆盖**：8 类关键问题模式全部 grep 扫描。
- **代码抽样**：5 个大文件 + 8 个中小文件关键片段读取，约覆盖 30% 代码量。
- **未覆盖**：端点层部分文件（如 purchase_center/product_routes.py、customer_routes.py）未深入读取，基于统计指标推断风险。

### 13.3 局限性

1. 圈复杂度为估算值，未使用 mccabe 等工具精确计算。
2. 代码重复率基于人工识别，未使用 pylint/simian 等工具。
3. 部分潜在缺陷（如并发安全、事务边界）需结合运行时行为分析，静态扫描覆盖有限。
4. SQL 注入风险扫描仅覆盖 `text() + f-string` 模式，未覆盖 ORM `filter()` 动态拼接。

---

> 报告生成完毕。如需深入分析特定文件或缺陷，请指定文件路径和关注点。