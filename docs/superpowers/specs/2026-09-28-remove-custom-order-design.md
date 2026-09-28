# 移除「定制订单」与「国家」功能 — 设计文档

- 日期：2026-09-28
- 状态：待评审
- 范围：`/customer-order`、`/stock` 两个视图，以及支撑它们的后端与数据库

## 1. 目标

把「定制订单」这一订单类型从 ERP 中彻底移除：

- `/customer-order` 只能录入常规订单，不再有「订单类型」选择，也不再有「国家」输入。
- `/stock` 不再出现定制订单相关的列、筛选、统计与出库校验。
- 数据库层面删除 `order_type` / `country` 两列，以及定制订单专用的 `country` 主数据表。

「国家」是定制订单的专属维度（定制订单必须填国家、出库按国家校验库存、库存页按国家分行统计），因此随定制订单一并移除。

## 2. 现状核查（2026-09-28，只读副本 `localhost:5433`）

副本最后回放时间 2026-09-28 11:22 UTC，与主库同步。

| 表 | 定制(custom) 记录 | 备注 |
|---|---|---|
| `order` | 0 | 共 4 条，全部为 regular（含 2 条软删） |
| `order_item` | 0 | 共 2 条，全部为 regular |
| `stock_in` | — | 表为空 |
| `staging_order` | — | 表为空 |
| `staging_stock_out` | — | 表为空 |
| `country` | 2 行 | 纯定制订单用主数据，无业务引用 |

**结论：删除 `order_type` / `country` 列与 `country` 表不会丢失任何业务数据。**

数据库迁移版本：`alembic_version = pg_standalone_053_po_item_loss_rate`；仓库中文件头为 `pg_standalone_054_sync_schema_with_orm_metadata`（`revision='pg_standalone_054'`，`down_revision='pg_standalone_053_po_item_loss_rate'`），尚未执行。新迁移接在 `054` 之后。

## 3. 范围

### 删除

- 订单类型概念：`order_type`（`regular` / `custom`，含历史别名 `normal`）
- 国家概念：`country` 字段、`country` 表及其全部管理入口

### 不删除（保持不动）

- 常规订单主流程（录入、列表、编辑、审批、出库、抵扣）
- 备货（stockin）主流程
- 其它模块：purchase、pattern-room、supplier、case、shipment 等
- 移动端：`frontend-vite/src/mobile` 不含定制订单/国家逻辑，不受影响

## 4. 数据模型变更

### 4.1 ORM 模型

| 文件 | 变更 |
|---|---|
| `fastapi_app/shared_models/order.py` | 删 `order_type`、`country` 字段及 `to_dict()` 中的对应键 |
| `fastapi_app/shared_models/order_item.py` | 同上 |
| `fastapi_app/shared_models/stock_in.py` | 同上 |
| `fastapi_app/shared_models/staging_order.py` | 同上 |
| `fastapi_app/shared_models/staging_stock_out.py` | 同上 |
| `fastapi_app/shared_models/country.py` | **删除文件** |
| `fastapi_app/shared_models/__init__.py` | 移除 `Country` 导出 |

### 4.2 迁移

新增 `migrations/versions/pg_standalone_055_remove_custom_order_country.py`：

- `revision = 'pg_standalone_055_remove_custom_order_country'`
- `down_revision = 'pg_standalone_054'`

`upgrade()`：

- `DROP INDEX idx_order_custom_type`（已核实存在的定制订单专用部分索引：
  `CREATE INDEX idx_order_custom_type ON "order" (product_id, customer, country) WHERE order_type = 'custom'`）
- `ALTER TABLE "order" DROP COLUMN order_type, DROP COLUMN country`
- `ALTER TABLE order_item DROP COLUMN order_type, DROP COLUMN country`
- `ALTER TABLE stock_in DROP COLUMN order_type, DROP COLUMN country`
- `ALTER TABLE staging_order DROP COLUMN order_type, DROP COLUMN country`
- `ALTER TABLE staging_stock_out DROP COLUMN order_type, DROP COLUMN country`
- `DROP TABLE country`

`downgrade()`：

- 重建五张表的 `order_type`（`String(20)`，`server_default='regular'`）与 `country`（`String(100)`，nullable）
- 重建 `country` 表：`id` Integer PK autoincrement、`name` String(100) unique not null（照 `add_country_table.py`）
- 重建 `idx_order_custom_type`

约定：沿用本仓库既有迁移的空库守卫模式，在 `upgrade()` / `downgrade()` 开头调用
`migrations._legacy_base_guard.base_schema_absent()` 并在基础 schema 缺失时直接 `return`。

说明：downgrade 可恢复**结构**，不能恢复数据。由于 custom 数据为 0，实际无数据损失。

## 5. 后端变更

### 5.1 Schema 层

| 文件 | 变更 |
|---|---|
| `fastapi_app/schemas/order.py` | 删 `order_type` / `country` 字段与三处 `order_type == 'custom' and not country` 校验 |
| `fastapi_app/schemas/stock.py` | 删 `order_type`、`country` 字段 |
| `fastapi_app/schemas/staging.py` | 删 `order_type`、`country` 字段 |

### 5.2 服务层

| 文件 | 变更 |
|---|---|
| `fastapi_app/services/inventory_service.py` | 删 `REGULAR_ORDER_TYPE_ALIASES`、`normalize_order_type()`；`calculate_available_shipment_quantity()` 去掉 `order_type` / `country` 参数与类型分支 |
| `fastapi_app/services/stock_out_service.py` | 去掉「定制订单必须填写国家名称」校验（2 处）与相关参数透传 |
| `fastapi_app/services/order/commands.py` | 去掉定制订单国家校验 |
| `fastapi_app/services/staging/stockout.py` | 去掉 `order_type` / `country` 处理 |
| `fastapi_app/services/auxiliary_service.py` | 删 `get_country_by_name` / `get_country_by_id` / `create_country` / `delete_country` |
| `fastapi_app/services/batch_import_service.py` | 去掉「国家」列解析与 `order_type = 'custom' if country else 'regular'` 推导 |
| `fastapi_app/services/batch_import_core.py` | 同上 |
| `fastapi_app/services/batch_import_parser.py` | 删 `_parse_country_value()` |
| `fastapi_app/services/approval_service.py` | 去掉对 `order_type` / `country` 的引用 |
| `fastapi_app/shared/shipment_calc.py` | 去掉 `order_type` / `country` 输出与 `'normal'` 历史别名分支 |
| `utils/report_exporter.py` | 去掉 `country_orders` 列 |

### 5.3 库存聚合（重点）

`fastapi_app/services/stock_inventory_service.py`：

- `get_inventory_paginated()` 去掉 `country` 参数与缓存 key 中的 `country` 段
- `_build_inventory_cte_sql()` 剥离 `country_data` / `available_stock_by_country` 聚合
- `_format_inventory_rows()` 去掉 `country_orders`、`custom_order_qty`、`custom_stockout_qty`、`all_countries`
- 重算口径：`总订单 = 订单余量 + 备货量`（原为 `常规余量 + 定制余量 + 备货量`）
- `get_inventory()` 同步去掉 `all_countries`
- `get_stockins()` / `get_stockouts()` 去掉 `order_type` 筛选参数，以及缓存 key 中的 `ot:` 段

### 5.4 接口层

| 文件 | 变更 |
|---|---|
| `fastapi_app/api/v1/endpoints/auxiliary.py` | 删 `/aux/countries` 的 GET / POST / DELETE；`available-shipment` 去掉 `order_type` / `country` 查询参数与请求体字段及校验 |
| `fastapi_app/api/v1/endpoints/stock.py` | 去掉 `order_custom_quantity` 与 `order_type` 筛选参数 |

## 6. 前端变更

### 6.1 customer-order

| 文件 | 变更 |
|---|---|
| `views/customer-order/components/OrderInputPanel.vue` | 删「订单类型」选择、「国家」下拉、「新增国家」按钮 |
| `views/customer-order/components/CountryDialog.vue` | **删除文件** |
| `views/customer-order/components/EditOrderModal.vue` | 删国家行与表格列 |
| `views/customer-order/composables/useOrderForm.ts` | 删 `orderType` / `isCustomOrder` / `orderTypeOptions` / `country` / `countryStore` / `countryDialogVisible` / `openCountryDialog` / `saveCountry` / 国家互斥 `watch` / 缺项校验中的「国家」 |
| `views/customer-order/composables/useOrderList.ts` | 删订单类型筛选项 |
| `views/customer-order/composables/useOrderImport.ts` | 删 `order_type` 字段 |
| `views/customer-order/composables/types.ts` | `StagedItem` / `FormState` 删 `orderType`、`country`；`OrderRecord` 删 `order_type`、`country` |
| `views/customer-order/CustomerOrderView.vue` | 去掉 `orderTypeOptions` / `countryOptions` / 国家弹窗的绑定与事件 |

### 6.2 stock

| 文件 | 变更 |
|---|---|
| `views/stock/StockOutTab.vue` | 删订单类型选择、国家下拉、定制库存充足性校验 |
| `views/stock/components/StockOutInputForm.vue` | 删国家下拉 |
| `views/stock/components/StockOutEditStagedDialog.vue` | 删国家下拉 |
| `views/stock/components/StockOutDetailDialog.vue` | 删国家展示行 |
| `views/stock/components/StockOutRecords.vue` | 删订单类型筛选项 |
| `views/stock/components/StockWarningDialog.vue` | **删除文件**（定制库存不足告警） |
| `views/stock/composables/useStockWarning.ts` | 删按国家校验逻辑 |
| `views/stock/InventoryTab.vue` | 删国家筛选、`定制订单` 列、`_custom_details` / `_country_available` 计算与定制相关统计 |
| `views/stock/components/InventoryStatRow.vue` | 删「定制订单」统计卡；`总订单` 重算为 `订单 + 备货` |

### 6.3 共享

| 文件 | 变更 |
|---|---|
| `stores/country.ts` | **删除文件** |
| `api/country.ts` | **删除文件** |
| `api/index.ts` | 移除 `countryApi` 导出 |
| `api/stock.ts` | `availableShipment` 签名去掉 `orderType` / `country` |
| `api/auxiliary.ts` | 去掉 `order_type` / `country` 入参 |
| `api/material.ts` | 去掉 `order_type` / `country` 入参 |
| `types/index.ts` | 删 `custom_stockout_qty` / `custom_order_qty` / `_custom_details` / `_country_available` / `country_orders` / `available_stock_by_country` / 各处 `order_type` 与 `country` |

### 6.4 前端测试

| 文件 | 变更 |
|---|---|
| `test/countrySidebarStore.test.ts` | **删除文件** |
| `test/useStockWarning.test.ts` | 改写：去掉 `country_orders` 用例 |
| `test/customerOrder*.test.ts`、`test/OrderInputPanel.quantityReset.test.ts`、`test/CustomerOrderView.skuExpand.test.ts`、`test/useOutsourceProcess.test.ts` | 去掉 `orderType` / `country` 字段与断言 |

## 7. 行为变化

- 新建订单 / 备货不再有订单类型与国家，一律按常规处理。
- 出库可出货量回到「客户 + 产品」维度，不再按国家隔离。
- `/stock` 库存页不再有「定制订单」列、国家筛选与「定制订单」统计卡；`总订单 = 订单 + 备货`。
- **Excel 批量导入**：模板若仍带「国家」列，**静默忽略**（不解析、不报错）。导入模板与文档同步移除该列。
- 存量 regular 订单不受影响。

## 8. 落地顺序（方案 A）

一次性改完，按层分 commit，迁移单独放最后一个 commit：

1. DB 模型字段删除
2. 后端 schema / service / endpoint 删除
3. 前端删除
4. 测试同步
5. 迁移文件（单独 commit）
6. 跑迁移 + 全量测试 + 前端构建 + 点验

分 commit 的目的：代码问题与迁移问题可分别回滚。

## 9. 验证

1. **后端测试**：`pytest`，重点 `tests/test_order.py`、`tests/test_stock.py`、`tests/test_batch_stockout.py`、`tests/test_multi_sku_inventory_stats.py`、`fastapi_app/tests/test_auxiliary*.py`、`fastapi_app/tests/services/test_auxiliary_service.py`
2. **迁移**：按项目备份机制先备份 → `alembic upgrade head` → 确认 5 列与 `country` 表已删 → `alembic downgrade -1` → 确认结构重建 → 再 `upgrade` 到 head
3. **前端**：`vitest` 全量 + `vue-tsc` 类型检查 + `npm run build`
4. **手动点验**：`/customer-order` 录入订单（无类型/国家）、列表与编辑；`/stock` 出库（无国家）、库存页（无定制列/筛选/统计卡）

## 10. 风险与注意事项

- `stock_inventory_service.py` 的库存 CTE 是回归高发区，需重点比对改造前后相同数据的统计口径。
- 删除 `api/country.ts`、`stores/country.ts`、`CountryDialog.vue`、`StockWarningDialog.vue` 后，需全量搜索确认无残留 import。
- 迁移是结构性不可逆操作，必须在测试库先演练，再在生产执行。
- 工作区已存在与本任务无关的未提交改动（purchase / pattern-room / supplier / server_manager 等），实施时不得触碰。

## 11. 明确不做

- 不新增订单类型抽象（不保留「类型」字段作为未来扩展点）
- 不做历史 custom 数据迁移（核查结果为 0 条）
- 不顺带重构 purchase、pattern-room、supplier 等无关模块
