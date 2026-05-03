# ERP 系统代码审核报告 - 第二批：产品与物料链

**审核标准**: shenhecode.mdr 双策略审核（分类清单扫描 + 执行路径追踪）
**审核日期**: 2026-05-03
**审核范围**: 产品清单、物料计算器、来料登记、供应商管理
**代码版本**: new-main @ 561b045

---

## 审核范围统计

| 模块 | 文件数 | 代码行数 | 关键文件 |
|------|--------|---------|---------|
| 产品清单 | 8 | ~2,900 | product_service.py(242), ProductListView.vue(1783) |
| 物料计算器 | 4 | ~1,500 | purchase_product_service.py, MaterialCalculatorView.vue(1135) |
| 来料登记 | 4 | ~1,100 | material_registration_service.py, MaterialView.vue(1448) |
| 供应商管理 | 3 | ~800 | supplier.py(endpoint), SupplierView.vue(685) |
| 共享 | 3 | ~400 | product.py(model), product_material.py, supplier.py(model) |
| **合计** | **22** | **~6,700** | |

---

## 阶段 1：分类清单扫描（广度优先）

### 1. 算法与数据结构

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| ALG-07 | P1 | `product_service.py` | 114-123 | `update_product` 中 `initial_stock` 变更时直接 `product.current_stock += stock_change`，但未检查 current_stock 是否会变为负数。如果用户将 initial_stock 从 100 改为 0，而 current_stock 因出库已降至 50，修改后 current_stock 变为 -50 |
| ALG-08 | P2 | `product_search_service.py` | 57-84 | `search_for_bom_copy_sync` 先查询产品列表，再逐个 `db.query(Product).options(...).get(product.id)` 加载关联数据，N+1 查询问题。应使用 `selectinload` 在首次查询时预加载 |
| ALG-09 | P2 | `product_service.py` | 34-38 | `get_products` 查询所有产品无分页，`@cache_result` 虽有缓存，但首次加载时如果产品数过万会导致大量内存占用和慢查询 |
| ALG-10 | P2 | `MaterialCalculatorView.vue` | script段 | 前端物料计算使用 `purchaseApi.calculate()` 逐产品调用后端，选中N个产品时发N次请求。应提供批量计算接口 |

### 2. 代码结构与模块化

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| STR-07 | P1 | `purchase_product_service.py` | 全文件 | BOM 计算、产品列表、搜索建议、统计等功能混在一个文件中。BOM 计算是核心业务，应独立为 `bom_calculator_service.py` |
| STR-08 | P2 | `ProductListView.vue` | 1783行 | 单文件1783行，包含产品CRUD、图片上传、Excel导入、BOM配置、BOM复制5个独立功能域。应拆分为子组件 |
| STR-09 | P2 | `MaterialView.vue` | 1448行 | 三标签页（概览/进度/历史）在单文件中实现，每个标签页逻辑独立。应拆分为3个子组件 |
| STR-10 | P2 | `product_service.py` | 14-63 | 4个异常类（ProductDeleteError及其子类）定义在服务文件中，应移至 `exceptions.py` 或 `shared/` |

### 3. 命名与语义

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| NAM-05 | P2 | `product_service.py` | 221-227 | `get_product_stock` 返回 `available_stock` 字段直接等于 `current_stock`，但"可用库存"与"当前库存"在业务上应有区别（可用库存应扣除已分配订单量） |
| NAM-06 | P3 | `product_search_service.py` | 44 | `get_result_serializer` 方法名使用"serializer"，在 Python 语境中更常见的是"to_dict"或"format_result" |

### 4. 资源管理

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| RES-06 | P1 | `product_service.py` | 183-197 | `delete_product` 先检查关联（3次COUNT查询），再删除InventoryLog，再删除Product。整个操作无事务保护（未显式使用 begin_nested 或检查 session 事务状态）。如果在删除 InventoryLog 和删除 Product 之间发生异常，数据不一致 |
| RES-07 | P2 | `purchase_product_service.py` | BOM计算 | `calculate_material` 函数使用同步 Session（从 purchase_center_service 传入），在异步上下文中调用可能阻塞事件循环 |

### 5. 导入与依赖

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| IMP-05 | P2 | `product_search_service.py` | 60 | `from fastapi_app.services.purchase_product_service import _product_has_bom` 导入下划线前缀的私有函数，违反封装原则 |
| IMP-06 | P2 | `product_service.py` | 218 | `from fastapi_app.services.product_search_service import product_search_service` 内联 lazy import，且变量名与模块名相同，易混淆 |
| IMP-07 | P3 | `purchase_center_service.py` | 39-48 | 从 `purchase_product_service` 重导出 `_product_has_bom`（下划线前缀私有函数），进一步破坏封装 |

### 6. 边界与异常

| ID | 严重度 | 文件 | 行号 | 问题描述 |
|----|--------|------|------|---------|
| BND-11 | P1 | `product_service.py` | 114-137 | `update_product` 允许 `name` 参数为空字符串（`if name and name != product.name` 中空字符串跳过检查），但 `create_product` 不允许空名称。更新时可以绕过名称非空校验 |
| BND-12 | P1 | `product_service.py` | 160-197 | `delete_product` 检查关联订单/入库/出库时未考虑已删除的订单（`Order.is_deleted`）。已删除的订单仍会阻止产品删除 |
| BND-13 | P2 | `product_service.py` | 130-137 | `initial_stock` 更新后 `current_stock` 可能变为负数，但无校验。虽然有 InventoryLog 记录变更，但允许负库存与业务规则矛盾 |
| BND-14 | P2 | `material_registration_service.py` | receive方法 | 来料登记的"接收"操作应验证接收数量 <= 未接收数量，但具体实现需要检查是否有此边界校验 |
| BND-15 | P2 | `ProductListView.vue` | script段 | 前端产品删除仅检查后端返回的错误消息，如果后端异常被全局错误处理吞没，用户可能看到"删除成功"但实际失败 |

---

## 阶段 2：执行路径追踪（深度优先）

### 追踪路径 7：产品更新（update_product）

```
API: PUT /api/v1/products/{id}
  -> product_service.update_product(db, product_id, name, barcode, image, initial_stock, price)
    -> [锁] get_product_for_update(db, product_id) -- SELECT FOR UPDATE
    -> [验证] 产品存在 (L109-110)
    -> [验证] 名称唯一性（排除自身）(L112-119)
    -> [更新] barcode, price, image (L121-126)
    -> [计算] initial_stock 变更 -> stock_change = new - old (L128-129)
    -> [更新] product.current_stock += stock_change (L130) **可能为负**
    -> [日志] InventoryLog + db.add (L132-137)
    -> [提交] db.commit (L139)
```

**发现的问题：**
- **P1 ALG-07/BND-13**: `current_stock += stock_change` 后可能为负，无校验。例如 initial_stock 从 100 改为 0，current_stock 当前为 50 -> 结果为 -50
- **P1 BND-11**: 空字符串 name 跳过唯一性检查，但 Product model 可能有 NOT NULL 约束（取决于数据库），绕过业务层校验

### 追踪路径 8：产品删除（delete_product）

```
API: DELETE /api/v1/products/{id}
  -> product_service.delete_product(db, product_id)
    -> [查询] db.get(Product, product_id) -- 无行锁
    -> [检查] 产品存在 (L159-161)
    -> [检查] 关联订单数 (L163-166) -- 未过滤 is_deleted
    -> [检查] 关联入库数 (L168-171)
    -> [检查] 关联出库数 (L173-176)
    -> [删除] InventoryLog (L179-181)
    -> [删除] product (L183)
    -> [提交] db.commit (L184)
```

**发现的问题：**
- **P1 BND-12**: 关联订单检查未排除已删除订单，导致已删除的订单仍阻止产品删除
- **P1 RES-06**: 整个删除操作无显式事务保护，删除 InventoryLog 和删除 Product 之间可能断开
- **P2**: `db.get(Product, product_id)` 无行锁，并发删除+更新同一产品可能导致不一致

### 追踪路径 9：BOM 物料计算（calculate_material）

```
API: POST /api/v1/purchase-center/product/calculate
  -> purchase_product_service.calculate_material(db, product_id, quantity)
    -> [查询] 获取产品及其 BOM 关联数据
    -> [计算] 按物料类别（面料/填充/辅料/包装）逐项计算
    -> [汇总] 返回 {materials, total_cost, categories}
```

**发现的问题：**
- **P2 RES-07**: 使用同步 Session，在异步路由中可能阻塞事件循环
- **P2**: 未校验 quantity > 0，传入负数或0可能导致计算结果异常

---

## 问题汇总表

### P1 - 严重级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-07/BND-13 | `product_service.py` | 130 | initial_stock 变更后 current_stock 可能为负 | 添加 `if product.current_stock < 0: raise ValueError` |
| BND-11 | `product_service.py` | 112 | 空字符串 name 绕过唯一性检查 | 改为 `if name is not None and name.strip()` |
| BND-12 | `product_service.py` | 163-166 | 删除检查未排除已删除订单 | 添加 `.where(Order.is_deleted == False)` 条件 |
| RES-06 | `product_service.py` | 183-197 | 删除操作缺乏事务保护 | 使用 savepoint 或确保 session 在事务中 |
| STR-07 | `purchase_product_service.py` | 全文件 | BOM 计算与其他功能混合 | 拆分 BOM 计算为独立模块 |

### P2 - 中等级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| ALG-08 | `product_search_service.py` | 57-84 | N+1 查询 | 使用 selectinload 预加载 |
| ALG-09 | `product_service.py` | 34-38 | 无分页的全量查询 | 添加分页参数 |
| ALG-10 | MaterialCalculatorView.vue | script段 | 逐产品N次请求 | 提供批量计算接口 |
| STR-08 | ProductListView.vue | 全文件 | 1783行单文件 | 拆分为子组件 |
| STR-09 | MaterialView.vue | 全文件 | 1448行单文件 | 拆分为子组件 |
| NAM-05 | `product_service.py` | 221-227 | available_stock 等于 current_stock | 重新定义"可用库存"业务含义 |
| RES-07 | `purchase_product_service.py` | BOM计算 | 同步 Session 阻塞事件循环 | 迁移为异步或使用 run_in_executor |
| IMP-05 | `product_search_service.py` | 60 | 导入私有函数 | 重构为公开接口 |
| BND-14 | `material_registration_service.py` | receive方法 | 接收数量边界校验可能缺失 | 验证接收数量 <= 未接收数量 |

### P3 - 轻微级

| ID | 文件 | 行号 | 问题 | 修复建议 |
|----|------|------|------|---------|
| NAM-06 | `product_search_service.py` | 44 | serializer 命名不规范 | 改为 to_dict_formatter |
| IMP-06 | `product_service.py` | 218 | 变量名与模块名相同 | 使用别名导入 |
| IMP-07 | `purchase_center_service.py` | 39-48 | 重导出私有函数 | 提供公开接口 |
| STR-10 | `product_service.py` | 14-63 | 异常类定义在服务文件 | 移至 exceptions.py |
| BND-15 | ProductListView.vue | script段 | 前端删除错误处理不完善 | 检查后端响应 success 字段 |

---

## 跨模块交互风险

### 风险 4：产品删除与关联数据一致性

```
产品删除检查 -> Order/StockIn/StockOut 关联检查
  -> 如果有已删除订单(is_deleted=True)仍阻止删除
  -> 如果删除成功但缓存未失效，其他模块可能引用已删除产品
```

### 风险 5：BOM 计算与采购中心同步

```
物料计算器 -> calculate_material -> 返回物料需求
采购中心 -> create_purchase_order -> 使用 BOM 数据创建采购项
  -> 如果 BOM 在计算和创建之间被修改，采购项数据可能过时
```

---

## 审核结论

| 严重度 | 数量 |
|--------|------|
| P0 | 0 |
| P1 | 5 |
| P2 | 9 |
| P3 | 5 |
| **总计** | **19** |

**判定：Approve with Comments**

无 P0 阻塞问题。5个 P1 问题建议在当前迭代修复，最关键的是：
- 产品更新后 current_stock 可能为负（ALG-07/BND-13）
- 产品删除检查未排除已删除订单（BND-12）
