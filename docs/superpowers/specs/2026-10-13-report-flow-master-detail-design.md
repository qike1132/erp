# 报表流水五 tab 改造设计（母行-明细 / 单号可见 / 单 SKU 语义）

> 日期：2026-10-13 ｜ 状态：待 owner 评审
> 对比稿：`mockups/report-order-flow-grouping-v4-2026-10-13.html`（最终形态）

## 1. 问题

`/report` 报表页五个 tab（订单流水 / 备货流水 / 出货流水 / 备货抵扣流水 / 退货流水）现状：

1. **看不到单号**：后端其实已返回 `order_nos`/`stockin_nos`/`stockout_nos`/`return_nos`（`STRING_AGG` 拼接），但前端表格**没有任何列**渲染它。
2. **分不清先后**：屏幕侧「下单时间」只到**日**（`DATE(order_date)` → `%Y-%m-%d`），且 `ORDER BY DATE(...) DESC` 同日内不按先后排。
3. **多 SKU 订单行爆炸**：订单流水按 `(日期, 客户, 产品, 状态)` 分组，一张 4 客户 × 10 SKU 的批次 → 40 行，且跨订单合并、单号被拼进同一格。

## 2. 目标

五个 tab 统一到同一套展示与操作逻辑：

- **单号可见**：每行都能看到自己的单号（订单号 / 备货单号 / 出货单号 / 退货单号）。
- **时间到分 + 按时间倒序**：同一天也能看出先后。
- **行数收敛**：多 SKU 订单不再平铺成 N 行。
- **行内编辑/删除直连**：点某行只作用于**该行对应的记录**，不再走「还原聚合行 → 选择弹窗」。

## 3. 现状数据粒度（决定每个 tab 的形态）

| tab | 底层表 | 粒度 | 是否有母行-明细 |
|---|---|---|---|
| 订单流水 | `order` + `order_item` | 一张订单有 N 个 SKU | **有**（母行=订单，明细=SKU） |
| 备货流水 | `stock_in` | 一条记录 = 一个产品 | 无（平铺） |
| 出货流水 | `stock_out`（`stockin_id IS NULL`） | 一条记录 = 一个产品 | 无（平铺） |
| 备货抵扣流水 | `stock_out`（`stockin_id IS NOT NULL`） | 一条记录 = 一个产品 | 无（平铺） |
| 退货流水 | `stock_return` | 一条记录 = 一个产品 | 无（平铺） |

**关键点**：只有订单流水需要母行-明细；其余四个 tab 是「一行 = 一条记录」，改造只是**去掉跨记录聚合**（改为一行一记录）+ 补列。

## 4. 设计决策（已与 owner 锁定）

1. **订单流水用「变体 2」**：单 SKU 订单压成一行；多 SKU 订单 = 母行 + 可展开的 SKU 子行。
2. **子行与母行共用同一列网格**：同一 `<table>` / 同一 `<colgroup>`；子行只填有值的列，其余留空；**不做左缩进**，层级靠底色 + 左侧竖线 + 首列 `└`。→ 产品名称/条码/数量/备注/操作永远与表头对齐。
3. **列定义（五 tab 统一）**：`展开 · 下单时间 · 订单号 · 客户 · 产品名称 · 条码 · 数量 · 备注 · 操作`
   - 备货/出货/抵扣/退货 tab 的「单号」列标题按维度变（备货单号 / 出货单号 / 退货单号），无「展开」列。
   - **不设「状态」列**（沿用现状：屏幕侧本就没有状态列）；末列是「备注」。
4. **编辑/删除 = 单 SKU 语义**（订单 tab）：点某条 SKU 子行只改/只删**这一个 SKU**。
   - 备货/出货/抵扣/退货 tab：点某行只改/只删**这一条记录**（本就单产品）。
5. **时间到分**：屏幕侧时间字段改为 `YYYY-MM-DD HH:MM`，排序改为按 `datetime DESC`。
6. **一行一记录**：备货/出货/抵扣/退货四个 tab 取消 `(日期,客户,产品)` 分组聚合，改为一行一记录（单号因此逐行有意义）。

## 5. 订单流水：母行-明细

### 母行（= 一张订单）
下单时间(到分) · 订单号 · 客户 · 品项数（如「共 10 个 SKU」）· 总数量（= Σ item.quantity）· 备注（订单级）· （无操作按钮）

### 子行（= 一个 SKU）
产品名称 · 条码 · 数量 · 备注（SKU 级）· 操作（编辑 / 删除该 SKU）

### 单 SKU 订单（变体 2）
母行与子行合并为一行：下单时间 · 订单号 · 客户 · 产品名称 · 条码 · 数量 · 备注 · 操作。

## 6. 后端改动

### 6.1 新增 order_item 级接口（订单 tab 的单 SKU 语义必需）

现状只有整单级：`PUT /orders/edit/{order_id}`、`DELETE /orders/delete/{order_id}`。

新增：
- `PUT /orders/items/{item_id}` — 编辑单个 SKU（`quantity`、`note` 可选；`customer` 仍是订单级，不下发）。
  - 事务内：校验 → 改 `order_item.quantity/note` → **重算 `order.quantity = Σ items.quantity`**（口径来源 `order_batch_create.py:199`）→ 数量变化时补 `InventoryLog`（`change_type='订单修改'`）。
  - 权限沿用 `require_any_permission("order_manage", "order_edit")`。
  - 锁序：沿用 `update_order` 的 Product→Order 预锁（避免与出库路径死锁）。
- `DELETE /orders/items/{item_id}` — 删除单个 SKU。
  - 若删除后**订单仍有其他 item**：删该 item → 重算 `order.quantity` → 补 `InventoryLog`（`change_type='订单修改'`，负向）。
  - 若删除的是**最后一个 item**：等价于删除整张订单（复用 `order_service.delete_order` 的备份/级联逻辑）。
  - 有关联备货抵扣（该 SKU 已被 `stock_out` 抵扣）时拒绝删除并返回明确错误。
  - 权限沿用 `require_any_permission("order_manage", "order_delete")`。

### 6.2 屏幕查询改造（`fastapi_app/services/report_service.py`）

- `get_order_logs`：由「按 `(日期,客户,产品)` 分组」改为 **按订单分页 + 带出 items**：
  - 先用 CTE 取当页 `order_id`（`ORDER BY order_date DESC, id DESC LIMIT/OFFSET`），再 JOIN `order_item`/`product` 展开，返回「一行 = 订单×SKU」，附带订单级字段（`order_id`、`order_no`、`order_date`(到分)、`customer`、`order_note`、`item_count`、`order_total_qty`）与 SKU 级字段（`item_id`、`product_name`、`product_barcode`、`quantity`、`item_note`）。
  - `total_count` = 匹配的**订单数**（DISTINCT order），不是 item 行数。
- `get_stockin_logs` / `get_stockout_logs` / `get_deduction_logs` / `get_return_logs`：取消 `GROUP BY`，改一行一记录；时间字段到分；每行带 `record_id`、`record_no`（`stockin_no`/`stockout_no`/`return_no`）、`product_barcode`、`note`。
- `ReportLogItem`（`fastapi_app/schemas/report.py`）补字段：`record_id`、`record_no`、`order_id`、`item_id`、`item_count`、`order_total_qty`、`item_note`。

### 6.3 导出侧（评审修正：导出侧本就一行一记录）

> **修正**：导出侧 `fastapi_app/shared/report_data_service.py` 的四个非订单 tab **本来就是一行一记录**（`select(StockIn)` 逐行迭代，无 `GROUP BY`/`STRING_AGG`），时间**本就是 `%Y-%m-%d %H:%M`**，单号也已在行里。**所以导出侧数据查询不需要改**。

- `utils/report_exporter.py`：五个 `export_*_logs` 的 `headers` 增加「订单号/备货单号/出货单号/退货单号」与「条码」列，`_format_*_row` 同步——把已存在的字段**渲染出来**（此前表头没有这两列，数据虽在但不显示）。

## 7. 前端改动

| 文件 | 改动 |
|---|---|
| `frontend-vite/src/views/report/composables/useReportConfig.ts` | 列定义改为九列；每 tab 的单号列标题不同；`dateKey`/`countKey` 保留 |
| `frontend-vite/src/views/report/components/ReportTable.vue` | 重构为「分组行」渲染：订单 tab 按 `order_id` 分组，多 SKU 渲染母行+子行（展开），单 SKU 压一行；其余 tab 平铺；共用同一 `<colgroup>`，子行对齐 |
| `frontend-vite/src/views/report/composables/useReportRowActions.ts` | 去掉「还原聚合行 + picker」流程，改为**直连**：订单 tab 调 `orderApi.updateItem/deleteItem`；其余 tab 调各自单条接口。`parseGroupNos`/`matchRecordsByNos`/picker 相关可删（确认无他处引用后） |
| `frontend-vite/src/api/order.ts` | 新增 `updateItem(id, data)`、`deleteItem(id)` |
| `frontend-vite/src/api/report.ts` | 响应类型补新字段 |

**保留**：`ReportRecordPicker.vue` 若无引用则删除（同 PR 内，确认零引用）。

## 8. 权限与审批语义

- 行内按钮权限沿用 `TAB_ROW_PERMISSIONS`（迁移 075/079/091），不变。
- 新增的两个 item 级端点复用 `order_manage/order_edit/order_delete`，**不新增权限码**。
- 工厂隔离 `_factory_scope` 口径不变。
- **审批例外（owner 2026-10-13 裁决）**：现有的**整单级**编辑/删除对非超管走审批（`_submit_edit_approval`/`_submit_delete_approval`）且编辑前过 `_check_order_lock`。本设计的 **item 级编辑/删除（非末项）改为直改、不走审批**，仅权限码门控——**但必须仍过 `_check_order_lock`**（被他人锁定/审批中的订单不可改）。这是一处**有意的权限模型放宽**：持有 `order_edit`/`order_delete` 的用户可直接改/删任意未锁定订单的单个 SKU。
- **删末项 = 删整单**：属整单级操作，**沿用 `delete_order` 的既有语义**——对非超管会**变成提交审批**（订单不立即删除）。前端必须展示后端返回的真实 message（`requires_approval` 分支），不能硬编码「已删除」。

## 9. 测试策略

- **后端**：
  - 新增 `PUT/DELETE /orders/items/{id}` 的回归测试（Red→Green）：改数量后 `order.quantity` = Σ items；删非末 item 保留订单；删末 item 订单消失；有抵扣时拒删。
  - `get_order_logs` 新结构的契约测试：按订单分页、`total_count` 是订单数、items 完整。
  - 四个 tab 去分组后的行数/字段契约测试。
  - 导出测试同步（表头含单号/条码）。
- **前端**：`ReportTable` 分组渲染单测（多 SKU 母行+子行、单 SKU 压一行、列对齐 class）；`useReportRowActions` 直连单测。
- **门禁**：`python scripts/quality_gate.py`、`ruff`、`pytest`（聚焦）、前端 `npm run type-check` / `npm test` / `npm run check:api`。

## 10. 风险与回滚

- **单 SKU 删到空 → 整单删除**：复用 `delete_order`（含备份/级联/审批），**非超管会变成提交审批**（订单不立即删）。与「审批删除」路径口径一致（memory `order-delete-two-paths-must-match`）。前端必须展示真实返回，不能硬编码成功文案。
- **item 级直改绕过审批**：owner 已裁决接受；风险是持有 `order_edit/order_delete` 的用户可直接改/删未锁定订单的单个 SKU。`_check_order_lock` 保留，锁定/审批中的订单不受影响。
- **已抵扣 SKU 拒删**：按 `(订单, 产品)` 匹配（抵扣无 item 粒度），同单同产品多 item 时会**过严拒删**——已知限制，错误文案写「该产品在本订单已被抵扣」。
- **`order.quantity` 重算**：多 SKU 下这是兼容值，改动后必须全路径同步（列表页读 `first_item.quantity`，见 `sync_single_item_quantity` 注释）；并重算 `order.status`（数量是状态派生输入）。
- **分页口径变化**（订单 tab 由「行」变「订单」）：前端页码/总数展示要同步，避免「总数是 item 数、页数是订单数」的错配。
- 回滚：前端表格与后端查询是同一 PR；如需回滚，整体 revert 该 PR 即可（无迁移、无数据结构变更）。

## 11. 非目标（YAGNI）

- 不改订单/备货/出货/退货的数据模型。
- 不新增权限码。
- 不改「备货抵扣流水」的客户不可改语义。
- 不动 `/report` 的筛选条与 tab 结构。
