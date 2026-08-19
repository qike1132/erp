# 后端代码质量审查报告 - B组（生产域 + 库存域）

> 审查时间：2026-08-19
> 审查范围：生产域（物料计算/来料登记/产品清单/生产报表/板房管理/皮套管理/出货计划）+ 库存域（出库管理/数据查询）共 9 个模块 38 个文件
> 技术栈：FastAPI + SQLAlchemy 2.0 + asyncpg + Pydantic 2.13
> 审查方法：批量行数统计 + 正则模式扫描 + 大文件抽样阅读

## 审查概览

| 模块 | 文件数 | 总行数 | 风险等级 | 主要问题数 |
| --- | --- | --- | --- | --- |
| 1. 物料计算器 (bom) | 1 | 434 | 低 | 1 |
| 2. 来料登记 (material_registration) | 4 | 1374 | 低 | 0 |
| 3. 产品清单 (product) | 5 | 762 | 低 | 0 |
| 4. 生产报表 (report) | 6 | 2153 | 低 | 1 |
| 5. 板房管理 (pattern_maker) | 3 | 197 | 低 | 0 |
| 6. 皮套管理 (case) | 2 | 1570 | 中 | 2 |
| 7. 出货计划 (production_plan + staging) | 8 | 1869 | 中 | 2 |
| 8. 出库管理 (stock) | 5 | 2382 | 高 | 4 |
| 9. 数据查询 (storage + numbering + serializers) | 4 | 864 | 中 | 2 |
| **合计** | **38** | **11 625** | — | **14** |

> 风险等级判定标准：高=存在上帝模块/SQL 拼接/重复代码 ≥300 行；中=单文件 >800 行或 f-string SQL；低=职责单一、行数适中、无安全风险。

---

## 一、物料计算器（bom_service）

### 1.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/bom_service.py | 434 |

### 1.2 代码规范
- 全部使用 `async def`（6 个异步函数），1 个同步辅助函数。
- 无 broad-except、无 bare-except、无 `pass` 占位。

### 1.3 注释覆盖率
- 6 处 docstring（`"""`），6 处行内注释；模块顶部有职责说明。
- 关键 SQL 片段有 `# sql-safe` 风格注释。

### 1.4 命名合理性
- 函数命名清晰（如 `calculate_bom`、`_normalize_filling`），私有辅助函数以 `_` 前缀。

### 1.5 圈复杂度
- 单文件 434 行，函数粒度适中，圈复杂度低。

### 1.6 代码重复
- 无明显重复。

### 1.7 潜在缺陷
- **TODO（低风险）**：第 175 行 `# TODO: filling 为 1:1 关系`，标识 filling 字段结构与 fabric/accessory 不一致，待后续重构。仅 1 处。

### 1.8 风险等级评估
**低**。模块职责单一，无安全风险，TODO 不影响当前功能。

---

## 二、来料登记（material_registration）

### 2.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/material_registration_service.py | 640 |
| api/v1/endpoints/material_registration.py | 474 |
| shared_models/material_registration.py | 161 |
| schemas/material_registration.py | 99 |

### 2.2 代码规范
- 15 个 async 函数 + 2 个同步函数，分层清晰（service / endpoint / model / schema）。
- 无 broad-except、无 bare-except。

### 2.3 注释覆盖率
- 34 处 docstring，15 处行内注释；service 顶部有模块说明。
- 第 227 行有重要设计注释：`purchase_order 改用 selectinload 单独加载，避免 FOR UPDATE 锁定采购订单表`，体现并发安全设计考量。

### 2.4 命名合理性
- 命名规范，动词 + 名词结构（`create_registration`、`confirm_registration`）。

### 2.5 圈复杂度
- 单文件最大 640 行，函数粒度合理。

### 2.6 代码重复
- 16 处 `escape_like` 调用，统一使用 `fastapi_app.core.sanitizer.escape_like`，无重复实现。

### 2.7 潜在缺陷
- 无 TODO/FIXME，无 broad-except。
- 1 处 `with_for_update`（第 236 行）用于并发安全，符合预期。

### 2.8 风险等级评估
**低**。分层清晰，并发安全设计良好。

---

## 三、产品清单（product）

### 3.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/product_service.py | 355 |
| services/product_search_service.py | 82 |
| api/v1/endpoints/product.py | 105 |
| shared_models/product.py | 104 |
| schemas/product.py | 116 |

### 3.2 代码规范
- 9 个 async 函数，无 broad-except、无 bare-except。

### 3.3 注释覆盖率
- 30 处 docstring，5 处行内注释；覆盖率良好。

### 3.4 命名合理性
- 命名规范，搜索服务单独抽离（`product_search_service.py`）符合单一职责。

### 3.5 圈复杂度
- 单文件最大 355 行，复杂度低。

### 3.6 代码重复
- 无明显重复。

### 3.7 潜在缺陷
- `product_search_service.py` 第 51 行函数内 `from sqlalchemy.orm import selectinload`（局部导入），轻微代码风格问题，但不影响功能。
- 1 处 `Any` 类型（`product_search_service.py`）。

### 3.8 风险等级评估
**低**。模块小巧、职责清晰。

---

## 四、生产报表（report）

### 4.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/report_service.py | 397 |
| api/v1/endpoints/report.py | 196 |
| services/production_summary_service.py | 359 |
| api/v1/endpoints/production_summary.py | 376 |
| services/daily_production_service.py | 569 |
| api/v1/endpoints/daily_production.py | 276 |

### 4.2 代码规范
- 6 个 async 函数 + 2 个同步函数；无 broad-except、无 bare-except。

### 4.3 注释覆盖率
- 30 + 36 + 24 = 90 处 docstring，覆盖率优秀。
- `daily_production_service.py` 23 处行内注释，对状态机/字段映射有详细说明。

### 4.4 命名合理性
- 命名规范，按业务概念划分（`report` / `production_summary` / `daily_production`）。

### 4.5 圈复杂度
- 单文件最大 569 行（daily_production_service.py），复杂度中等。

### 4.6 代码重复
- `report_service.py` 与 `production_summary_service.py` 均使用 `escape_like`（18 + 3 = 21 处），统一来自 sanitizer，无重复实现。

### 4.7 潜在缺陷
- `report_service.py` 第 72、78 行使用 `text(data_sql)` / `text(qty_sql)` 执行原始 SQL，6 处 `# nosec` 标注。SQL 拼接需确认 `data_sql` 来源——若为模块级常量则风险低；若含用户输入需复查。**建议**：补充单元测试覆盖 SQL 注入边界。

### 4.8 风险等级评估
**低**。整体规范，仅 `report_service.py` 原始 SQL 需持续关注。

---

## 五、板房管理（pattern_maker）

### 5.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/pattern_maker_service.py | 70 |
| api/v1/endpoints/pattern_maker.py | 77 |
| shared_models/pattern_maker.py | 50 |

### 5.2 代码规范
- 3 个 async 函数，无任何异常处理（依赖上层）。

### 5.3 注释覆盖率
- 8 处 docstring，覆盖率优秀。

### 5.4 命名合理性
- 命名规范。

### 5.5 圈复杂度
- 单文件最大 77 行，复杂度极低。

### 5.6 代码重复
- 无。

### 5.7 潜在缺陷
- 无。

### 5.8 风险等级评估
**低**。微型模块，质量优秀。

---

## 六、皮套管理（case）

### 6.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/case_service.py | 1077 |
| api/v1/endpoints/case_endpoint.py | 493 |

### 6.2 代码规范
- 25 个 async 函数 + 8 个同步辅助函数；无 broad-except、无 bare-except。
- 全部写操作使用 `with_for_update`（5 处），并发安全设计良好。

### 6.3 注释覆盖率
- 68 处 docstring（service），覆盖率优秀；模块顶部说明并发安全策略。

### 6.4 命名合理性
- 私有辅助函数以 `_` 前缀（`_parse_date`、`_normalize_pagination`、`_apply_date_filter` 等），分层清晰。

### 6.5 圈复杂度
- **中风险**：单文件 1077 行，33 个顶层函数。虽为函数式服务（非上帝类），但函数数量偏多，建议按"库存流水 / 库存汇总 / CRUD"拆分子模块。

### 6.6 代码重复
- 13 处 `escape_like`，统一来源，无重复实现。
- `create_case_stockin` / `create_case_stockout` / `update_case_stockin` / `update_case_stockout` 存在结构相似性，可抽取通用模板。

### 6.7 潜在缺陷
- 无 TODO/FIXME。
- `joinedload` 使用 10 处，需关注 N+1 反例（已用 joinedload 规避）。

### 6.8 风险等级评估
**中**。单文件超 1000 行，函数数量偏多，建议拆分。

---

## 七、出货计划（production_plan + staging）

### 7.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/production_plan_service.py | 331 |
| api/v1/endpoints/production_plan.py | 336 |
| shared_models/production_plan.py | 120 |
| services/plan_utils.py | 44 |
| services/staging_service.py | 848 |
| services/staging_utils.py | 28 |
| api/v1/endpoints/staging_order.py | 86 |
| shared_models/staging_order.py | 76 |

### 7.2 代码规范
- `staging_service.py`：28 async + 8 sync 函数；1 处 broad-except（第 813 行，附 `# defensive: 单个事件发布失败不影响确认结果` 注释，合理）。
- `production_plan_service.py`：16 async + 2 sync，无异常处理。

### 7.3 注释覆盖率
- `staging_service.py` 仅 6 处 docstring 但 9 处行内注释，docstring 覆盖率偏低。
- `production_plan_service.py` 38 处 docstring，覆盖良好。

### 7.4 命名合理性
- 命名规范，`_build_order_entity` / `_build_stockin_entity` / `_build_stockout_entity` 体现工厂模式。

### 7.5 圈复杂度
- **中风险**：`staging_service.py` 848 行，36 个顶层函数，包含 orders/stockins/stockouts 三套近乎对称的 CRUD + import + confirm 流程，存在明显结构重复。

### 7.6 代码重复
- **中风险**：`staging_service.py` 中 `get_staging_orders` / `get_staging_stockins` / `get_staging_stockouts`、`clear_staging_*_by_session`、`confirm_staging_*` 三组函数结构高度相似，估算重复代码 200~300 行。**建议**：抽取泛型 `_generic_confirm_staging` / `_generic_clear_staging` 模板。

### 7.7 潜在缺陷
- `staging_service.py` 第 84 行 `_parse_deduct_flag(deduct_flag: Any, qty: int)` 使用 `Any` 类型，类型安全较弱。
- 第 316 行 `pass` 占位（`_stockout_extra_updates` 中 quantity 字段无操作），属设计预留 hook，非缺陷。
- 1 处 broad-except 已注释说明，可接受。

### 7.8 风险等级评估
**中**。staging_service 存在结构重复，建议泛型重构。

---

## 八、出库管理（stock）

### 8.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/stock_service.py | 1428 |
| api/v1/endpoints/stock.py | 445 |
| services/inventory_service.py | 73 |
| services/fifo_allocation.py | 325 |
| schemas/stock.py | 111 |

### 8.2 代码规范
- `stock_service.py`：36 async + 10 sync 函数；1 处 broad-except（第 536 行，附 `# defensive: 单个事件发布失败不影响主操作`，合理）。
- `fifo_allocation.py`：1 处 broad-except（第 93 行，附 `# defensive: FIFO查询异常时抛出明确异常`，合理）。
- 无 bare-except、无 except+pass。

### 8.3 注释覆盖率
- `stock_service.py` 86 处 docstring + 56 处行内注释，覆盖率优秀。
- 模块顶部 47 行安全边界说明（SQL 条件片段常量 `_CUST_CLAUSE` 等），明确"片段为字面量，值走绑定参数"，安全审查友好。

### 8.4 命名合理性
- 命名规范，私有辅助函数丰富（`_build_inventory_filter_params` / `_build_inventory_cte_sql` / `_format_inventory_rows` / `_empty_inventory_response` 等），体现拆分意识。

### 8.5 圈复杂度
- **高风险**：单文件 1428 行，46 个顶层函数。虽为函数式服务（非 class），但函数数量过多，包含 stockin/stockout/stockreturn/inventory/batch 五大业务方向，职责过宽。
- 注释说明"核心 CRUD 已统一至 `fastapi_app.shared.stock_crud_service`"，本服务为异步适配 + 事件发布层，但适配层仍 1428 行，说明拆分不彻底。

### 8.6 代码重复
- `batch_create_stockins` / `batch_create_stockouts` 存在结构相似性。
- 7 处 `escape_like`，统一来源。

### 8.7 潜在缺陷
- **高风险-原始 SQL 拼接**：9 处 `text(...)`，其中 6 处 `text(f'...')` f-string 拼接（第 903、1111、1125、1136、1228-1231 行），均附 `# nosec B608` 或 `# sql-safe` 注释。第 1228-1231 行 `_fetch_inventory` 中 stockin_sql / stockout_sql / order_sql / country_sql 拼接条件片段为模块级常量（`_CUST_CLAUSE` 等），值通过绑定参数传递，**当前安全**。但 f-string + text() 模式易在后续维护中误注入，**建议**：迁移至 SQLAlchemy ORM 表达式或使用 `sqlalchemy.sql.text` + `bindparams`。
- **TODO（中风险）**：2 处 `TODO(multi-sku-order)`（第 491、1407 行），标识多 SKU 订单模型下 `order.product_id` / `order.quantity` / `order.order_type` 兼容值处理待重构。涉及库存计算正确性，需优先排期。
- 9 处 `with_for_update`，并发安全设计良好。
- 10 处 `selectinload/joinedload`，N+1 防护良好。

### 8.8 风险等级评估
**高**。单文件 1428 行，函数 46 个，含 6 处 f-string SQL 拼接 + 2 处多 SKU TODO。建议：
1. 按业务方向拆分为 `stockin_service` / `stockout_service` / `stockreturn_service` / `inventory_query_service` / `stock_batch_service`。
2. 将 f-string SQL 迁移至 ORM 表达式。
3. 优先排期 multi-sku-order TODO。

---

## 九、数据查询（storage + numbering + serializers）

### 9.1 文件清单与规模

| 文件 | 行数 |
| --- | --- |
| services/storage_service.py | 433 |
| services/numbering.py | 168 |
| services/serializers/order_serializer.py | 259 |
| services/serializers/__init__.py | 4 |

### 9.2 代码规范
- `storage_service.py`：12 async + 10 sync 函数；**6 处 broad-except**（第 102、106、204、232、258、295 行），均附 `# broad-except: 服务层容错，记录异常并返回安全默认值` 注释。
- `numbering.py`：8 async 函数，1 处 `with_for_update`（第 108 行，序号生成并发安全）。
- `order_serializer.py`：纯序列化逻辑，无异常处理。

### 9.3 注释覆盖率
- `storage_service.py` 44 处 docstring + 12 处行内注释，覆盖率优秀。
- `numbering.py` 22 处 docstring，每个编号生成函数均有格式说明（如 `PO-YYYYMMDD-XXXX`）。
- `order_serializer.py` 12 处 docstring + 10 处行内注释。

### 9.4 命名合理性
- 命名规范，`numbering.py` 函数名清晰表达编号类型（`generate_order_number` / `generate_stockin_number` / `generate_stockout_number` 等）。

### 9.5 圈复杂度
- 单文件最大 433 行，复杂度低。

### 9.6 代码重复
- 无明显重复。

### 9.7 潜在缺陷
- **中风险-broad-except 集中**：`storage_service.py` 6 处 broad-except 集中在容错路径，注释说明返回安全默认值。需确认"安全默认值"不会掩盖数据损坏（如返回空列表 vs 抛出 500）。**建议**：补充监控告警，broad-except 触发时上报 Sentry/日志指标。
- `numbering.py` 第 85、126、131、136、141、147、153、158、163 行 docstring 中 `XXXX` 占位符描述，非缺陷。

### 9.8 风险等级评估
**中**。broad-except 集中需监控告警机制配套。

---

## 风险等级汇总

| 模块 | 风险等级 | 关键缺陷数 | Top 3 问题 |
| --- | --- | --- | --- |
| 1. 物料计算器 | 低 | 1 | TODO(filling 1:1 重构) |
| 2. 来料登记 | 低 | 0 | — |
| 3. 产品清单 | 低 | 0 | 局部 import 风格问题 |
| 4. 生产报表 | 低 | 1 | report_service 原始 SQL 需注入测试 |
| 5. 板房管理 | 低 | 0 | — |
| 6. 皮套管理 | 中 | 2 | 单文件 1077 行；CRUD 结构相似 |
| 7. 出货计划 | 中 | 2 | staging 三套 CRUD 重复 200~300 行；Any 类型 |
| 8. 出库管理 | 高 | 4 | 单文件 1428 行；6 处 f-string SQL；2 处 multi-sku TODO；batch 重复 |
| 9. 数据查询 | 中 | 2 | 6 处 broad-except 需告警；序号生成器集中 |
| **合计** | — | **14** | — |

---

## 高风险模块详细说明

### 8. 出库管理（stock_service.py）— 高风险

**问题 1：上帝模块（1428 行 / 46 函数）**

虽为函数式服务（非 class），但单文件聚合了 stockin / stockout / stockreturn / inventory / batch 五大业务方向，函数数量过多。模块顶部注释声称"核心 CRUD 已统一至 `fastapi_app.shared.stock_crud_service`，本服务负责异步适配层"，但适配层仍 1428 行，说明拆分不彻底。

**重构建议**：
- `stockin_service.py`：create/update/delete/get/batch_create_stockins
- `stockout_service.py`：create/update/delete/get/batch_create_stockouts + _recalc_shipment_order_statuses
- `stockreturn_service.py`：create/delete/get + recalc_order_status_after_return
- `inventory_query_service.py`：get_inventory / get_inventory_paginated + 所有 `_build_inventory_*` / `_fetch_inventory` / `_run_sql` 辅助函数
- `stock_event_service.py`：_publish_shipment_completed_events + 事件发布

**问题 2：f-string SQL 拼接（6 处）**

第 903、1111、1125、1136、1228-1231 行使用 `text(f'...')` 拼接 SQL。当前条件片段（`_CUST_CLAUSE`、`_SI_CUST` 等）为模块级常量，值通过绑定参数传递，**当前安全**，均附 `# nosec B608` / `# sql-safe` 注释。但 f-string + text() 模式易在后续维护中误注入。

**建议**：迁移至 SQLAlchemy ORM 表达式，或使用 `text().bindparams()` 显式绑定。

**问题 3：multi-sku-order TODO（2 处）**

- 第 491 行：`stock_out.order.order_type/country 在多 SKU 下为首 item 兼容值`
- 第 1407 行：`此处按 Order.order_type 分组 sum(Order.quantity) 在多 SKU 下结果错误`

涉及库存计算正确性，**建议优先排期**。

**问题 4：并发安全设计良好（正面）**

- 9 处 `with_for_update` 行级锁
- 10 处 `selectinload/joinedload` N+1 防护
- 7 处 `escape_like` 防 LIKE 注入
- 1 处 broad-except 已注释说明

---

## 整体改进建议（按优先级）

| 优先级 | 模块 | 建议 | 预期收益 |
| --- | --- | --- | --- |
| P0 | stock | 排期 multi-sku-order TODO（2 处） | 修复库存计算正确性 |
| P1 | stock | 拆分 stock_service.py 为 5 个子模块 | 单文件 < 400 行，可维护性提升 |
| P1 | stock | f-string SQL 迁移至 ORM 表达式 | 消除注入风险，移除 nosec |
| P2 | staging | 抽取 `_generic_confirm_staging` / `_generic_clear_staging` 泛型模板 | 消除 200~300 行重复 |
| P2 | case | 拆分 case_service.py 按"流水/汇总/CRUD" | 单文件 < 500 行 |
| P3 | storage | broad-except 配套监控告警 | 异常可观测性 |
| P3 | report | report_service 原始 SQL 补充注入测试 | 安全回归保障 |
| P4 | bom | 排期 filling 1:1 重构 TODO | 数据模型一致性 |

---

## 正面发现

1. **并发安全设计统一**：B 组共 17 处 `with_for_update` 行级锁，覆盖所有写操作；case_service 模块顶部明确说明并发安全策略。
2. **N+1 防护良好**：64 处 `selectinload/joinedload`，查询性能有保障。
3. **LIKE 注入防护统一**：59 处 `escape_like` 调用，统一来自 `fastapi_app.core.sanitizer`，无重复实现。
4. **broad-except 全部有注释**：9 处 broad-except 均附 `# defensive` / `# broad-except` 注释说明容错理由，无 bare-except、无 except+pass。
5. **docstring 覆盖率高**：500 处 docstring / 188 处行内注释，关键模块（stock_service 86 处、case_service 68 处）覆盖优秀。
6. **SQL 安全边界文档化**：stock_service.py 顶部 47 行注释明确 SQL 条件片段的安全边界，便于安全审查。
7. **分层清晰**：service / endpoint / model / schema 四层分离，命名规范（snake_case，私有 `_` 前缀）。