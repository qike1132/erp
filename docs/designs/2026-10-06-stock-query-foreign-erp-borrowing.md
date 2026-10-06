# 库存查询模块 · 外部 ERP 借鉴与代码评审（2026-10-06）

> 目的：在动手写 `/stock-query` 之前，先看成熟开源 ERP 怎么做库存余额、批次与流水，
> 避免重新发明轮子；并用它们的已知坑反过来审我们已批准的方案与本仓现有实现。
>
> 评审对象：已批准的 `docs/plans/2026-10-06-stock-query-workflow.md`（待写）+ 本仓现有库存代码。
> 结论：方案主体成立，但有 **3 个 BLOCKER** 需要在写代码前处置，其中 2 个是既有代码的老问题，
> 与本功能直接相撞。

---

## 一、四家开源 ERP 的库存模型对比

| 项目 | 余额（当前量） | 流水（可变历史） | 批次维度 | 占用/预订 | 回溯补录 |
|---|---|---|---|---|---|
| **ERPNext** | `Bin`（product×warehouse 缓存） | `Stock Ledger Entry`：`actual_qty`（增量）+ **`qty_after_transaction`（运行结存）** + `batch_no` + `voucher_type/voucher_no` + `is_cancelled` + 成本列（`stock_value_difference`/`valuation_rate`/`incoming_rate`） | **批次是流水行上的列**（`batch_no` + `has_batch_no`），不是外部查表 | 无（Bin 上有 projected_qty） | `Stock Reconciliation` + **`Repost Item Valuation`**：回溯单据会触发重算队列 |
| **Odoo** | `stock.quant`：**主键维度 = (product, location, lot, owner, package)**，字段含 `quantity`(在手)、`reserved_quantity`、`available_quantity`、`inventory_quantity`(盘点值)、`inventory_diff_quantity`(差异)、`is_outdated`、`cost_method`、`value` | `stock.move`（移动）+ `stock.move.line`（**按 lot 拆行**） | **lot 是余额行的键维度** | ✅ `reserved_quantity` 是独立列 | 盘点调整（`inventory_quantity` vs `quantity` 的 diff） |
| **InvenTree** | `StockItem`：**每个批次/序列号一行**，数量直接挂在行上 | `StockItemTracking`：**user FK + 日期 + 数量变化 + 数字型事件类型**（create/count/added/removed/shipped 等 20+ 种码表） | `batch` 是一等字段，**拆分后仍保留** | 有 allocated/shipped 状态 | 盘点事件（Stock counted）+ **保留期设置**（默认 365 天清理） |
| **本仓现状** | `product.current_stock`（单一标量 + `version` 乐观锁 + `ck_product_current_stock_nonneg` CHECK） | `inventory_log`：`change_type/change_quantity/change_date/related_id/note/customer`，**无操作人、无运行结存、无批次、无成本** | ❌ 无（`stock_in.stockin_no` 只是备货单号） | ❌ 无（用「订单余量」近似） | ❌ 无（`inventory_reconcile.py` 是**只读**对账，不改数） |

### 值得直接偷的 6 条设计

1. **流水行自带运行结存**（ERPNext `qty_after_transaction`）→ 正是我们要加的 `quantity_before/quantity_after`，方向正确。
2. **批次作为余额/流水的维度列**（ERPNext `batch_no`；Odoo `lot_id` 进 quant 键；InvenTree `batch` 字段）→ 我们「批次只在查询里展示」的取舍在**批次库存表**上够用，但**变动历史无法按批次切**（见 SUGGESTION 1）。
3. **作废用标记而非删除**（ERPNext `is_cancelled`；InvenTree 删了 stock item 仍保留 tracking）→ 本仓退货软取消（`status='cancelled'`）已对齐 ✅。
4. **事件类型用码表，标签与码分离**（InvenTree 20+ 数字类型 + 文档表）→ 本仓 `change_type` 是散落的中文自由文本（见 SUGGESTION 2）。
5. **请求级幂等**（本仓 `uq_inventory_log_idem` 部分唯一索引）→ 已比多数开源实现更严，保留 ✅。
6. **盘点差异与在手量分列**（Odoo `inventory_quantity` / `inventory_diff_quantity`）→ 未来做「账面 vs 实盘」时直接照抄这一对字段。

### 值得警惕的 2 个已知坑

- **ERPNext #51562「并发下 qty_after_transaction 算错」**：两个用户同时提交时运行结存会错，因为它是**用「此前所有流水的 SUM」推导**的，并发读到了交叉快照；修复路径是引入 Repost Item Valuation 重算队列。
  → **我们的方案（在锁内用写入口返回值反推 before/after）恰好避开了这个坑**，比 ERPNext 更强，应写进代码注释防止后人改回去。
- **ERPNext #58995**：batch 同时存在「流水行 `batch_no` 列」与「serial_and_batch_bundle 子表」两处，导致 Stock Ledger 报表期初余额翻倍。
  → **单一真相**原则：批次若入流水，就只入一处，不要既存列又存子表。

---

## 二、代码评审（按 agent-code-reviewer 规范）

### 🔴 BLOCKER 1 — 产品删除会**级联抹掉全部库存流水**，与「建立库存变动日志系统」直接冲突

**位置**
- `fastapi_app/shared_models/inventory_log.py:29` — `ForeignKey('product.id', ondelete='CASCADE')`
- `migrations/versions/pg_standalone_001_pg_standalone_initial_schema.py:462` — `FOREIGN KEY(product_id) REFERENCES product (id) ON DELETE CASCADE`
- `fastapi_app/services/product_service.py:337-338` — docstring 明写「删除时级联删除库存日志」（**刻意为之，非疏漏**）

**Why**
需求 2.4 要求「记录所有库存数量变更操作，含操作人/时间/前后数量」，需求 1.4 要求可查变动历史。
但 delete_product 一旦执行，该产品的**全部历史流水同步消失**，且 `GET /stock-query/change-logs` 会静默少行——
审计能力不是「没做」，而是「做了却会在某天凭空归零」。

这是三家开源实现一致反对的做法：
- InvenTree 文档明确：「Even if a stock item is deleted from the system, the associated stock tracking entries are **retained** for historical reference.」
- ERPNext `Stock Ledger Entry` 的 `item_code` 是 `DF.Link`（软引用），不是级联外键。

**Suggestion（二选一，需产品决策）**
- **A（推荐，贴近 ERPNext）**：`product_id` 改 `ondelete='SET NULL'`，并在流水行**冗余** `product_name`/`product_barcode`（`item_code` 式反范式化）。代价：迁移 + `inventory_reconcile.py` 的 JOIN 口径复核对齐（product 行没了 JOIN 结果本就不变，风险低）。
- **B（最小改）**：保留 CASCADE，但 `delete_product` 增加守卫——存在 `inventory_log` 行时拒绝删除（文案「该产品有库存流水，禁止删除」）。历史保住了，代价是产品删不掉。

> 现状不动的话，请把「本系统库存流水不构成审计凭证」写成明确声明，否则需求 2.4 是**名义交付**。

---

### 🔴 BLOCKER 2 — `related_id VARCHAR(50)` 在「一单拆多订单」时会溢出，出货直接 500

**位置**
- `fastapi_app/services/stock_out_service.py:70` 和 `:333`：
  `related_id=','.join(str(stock_out.id) for stock_out in created_stockouts)`
- DDL：`migrations/.../pg_standalone_001_...py:458` — `related_id VARCHAR(50)`

**Why**
`create_stockout_core` 会**按 FIFO 把一次出货拆成多条 StockOut**（每个订单一条）：
```python
for order_detail in shipment_info['orders']:
    ship_qty = min(remaining_qty, order_detail['available'])
    ...  created_stockouts.append(stockout)
```
再把它们的 id 逗号拼接写入 `related_id`。5 位数 id 下 **约 9 条订单就超过 50 字符**，
PostgreSQL 抛 `StringDataRightTruncation` → 大客户的一笔正常出货变成 500。
本仓已有同类前车之鉴：迁移 067 正是把 `inventory_log.idem_key` 改成 **TEXT** 才解决的同类长度墙。

**Suggestion**
- 立刻：把 `related_id` 提为 `VARCHAR(200)` 或 `TEXT`（迁移，与 067 同范式 `ALTER COLUMN ... TYPE`），并加一条「写入前长度断言 + 截断/摘要」的防御。
- 更好（对齐 ERPNext 的 `voucher_type` + `voucher_no` 结构化对）：本功能已在改流水表，顺手加 `voucher_type VARCHAR(30)` + 保持 `related_id` 为**单个**单据号；多单场景改为写多行流水（每单一行），语义与 Odoo 的 `stock.move.line` 按行拆分一致。

---

### 🔴 BLOCKER 3 — 运行结存（before/after）在**业务日期回溯**下不自洽，不能对外宣称「按时序结存」

**位置（方案侧）**
- 计划中的 `quantity_before = updated.current_stock - delta` / `quantity_after = updated.current_stock`
- `fastapi_app/shared_models/inventory_log.py:34` — `change_date` 默认 `datetime.now(UTC)`（**记录时刻**）
- 业务日期来自请求：`stock_out_service.create_stockout` → `_parse_date_preserve_time(stockout_date_str)`（**用户可填过去日期**）

**Why**
`quantity_before/after` 反映的是**记账（提交）顺序**，而 `change_date` 是**系统时刻**，
两者都不等于业务单据日期（`stockin_date`/`stockout_date`/`return_date`）。
若用户今天补录一张上月日期的出库，流水里会出现「上月业务流水排在今天之后」，任何按业务日期重排的
视图都会得到与 before/after 矛盾的链条——这正是 ERPNext 需要 Repost Item Valuation 的根因
（见其 #51562：并发/回溯下 `qty_after_transaction` 错，靠重算队列兜）。

我们**不做重算队列**是合理的取舍（本仓是内网单库、写入量小），但必须把语义说清，否则前端一排序就"露馅"。

**Suggestion**
- 流水表加一列 `posting_date`（业务日期，取对应单据日期）与保留 `change_date`（记账时刻），**明确二者分工**（对齐 ERPNext 的 `posting_date` + `posting_time` + `creation` 三列并存）。
- 变动历史接口**默认按 `(change_date DESC, id DESC)` 排序**并标注「账面时序」；若提供「按业务日期」排序，必须在 UI 上提示结存列不适用。
- 在 `log_inventory_change` 的 docstring 写明「before/after 为记账时序结存，非业务日期结存；禁止在未加锁读的场景下用 SELECT 反推」。

---

### 🟡 SUGGESTION 1 — 流水缺批次维度，变动历史无法按批次切

**位置**：`fastapi_app/shared_models/inventory_log.py`（无 batch/stockin 列）；方案把批次做成「查询时从 `stock_in.stockin_no` 派生」。

**Why**：需求 1.4 的筛选只要求「时间、产品」，所以 v1 够用。但 ERPNext（`batch_no` 在流水行）与 Odoo（`lot_id` 在 quant 键）都把批次当流水维度——
一旦业务提出「这批货到底出给了谁/动了多少次」，我们只能靠 `note` 文本捞，`related_id` 是出货单号不是批次号。

**Suggestion**：既然本次迁移已经在动这张表、写点也已经在逐个改签名，**顺手加 `stockin_id INTEGER`（可空，FK SET NULL）** 几乎零边际成本；
批次库存行天然持有 `stockin_id`，历史就能按批次聚合。不做也应记明「批次维度缺失」为已知限制。

---

### 🟡 SUGGESTION 2 — `change_type` 是散落的中文自由文本，缺码表与校验

**位置（实测全仓字面量，ast 扫描）**
`入库` / `入库修改` / `入库删除` / `出库` / `出库修改` / `出库删除` / `退货` / `退货取消`
/ `订单抵扣`（`order/deduction.py:152`）/ `取消抵扣`（`order/deduction.py:217,230`）/ `抵扣回滚`（`order/commands.py:473`）
—— 同一「抵扣」语义出现 **三个名字**。

**Why**：InvenTree 用 20+ 个**数字类型码 + 文档表**，标签与码分离；
我们若把自由文本直接当筛选值，一次拼写差异就会造出「新类型」并让筛选下拉漏项，
而且筛选项要靠 ast 扫描"猜"出来（方案里就是这么写的）——这是味道，不是设计。

**Suggestion**：定义唯一常量表（如 `fastapi_app/core/stock_change_types.py`），
存码（或至少存受控常量），标签单独映射；加一条守卫测试断言全仓 `change_type=` 取值 ⊆ 常量表。

---

### 🟡 SUGGESTION 3 — 流水缺「结存自洽」不变量，无法自证

**Why**：ERPNext #51562 那类 bug 之所以难发现，就是因为流水表没有任何机制校验
`结存 == 前结存 + 变动量`。本仓已有 `ck_product_current_stock_nonneg` 这种 CHECK 的先例，说明团队接受 DB 级不变量。

**Suggestion**：随本次迁移加
`CHECK (quantity_before IS NULL OR quantity_after IS NULL OR quantity_after = quantity_before + change_quantity)`
—— 允许历史行 NULL，但对新写入的流水，任何"结存算错"的代码会**在写入时立刻失败**，而不是等出报表才发现。

---

### 🟡 SUGGESTION 4 — 软删除过滤三套口径，且新接口会与旧接口数字不一致

**位置**
- 有过滤：`fastapi_app/services/order/beile.py:96,394,744`、`order/unified.py:125`
- **无**过滤：`stock_inventory_service._build_inventory_cte_sql` 的 `stockin_agg`（`WHERE 1=1{si_pid}{si_cust}`）、`get_stockins`
- 团队已自查记录：`order/unified.py:12`「不学 get_stockins 的静默忽略」

**Why**：目前**没有任何写入路径把 `StockIn.is_deleted` 置 True**（全仓搜索确认；删除走的是硬删 `delete_stockin_core`），
所以这是**防御性缺口而非活跃数据错误**——严重度别夸大。
但新模块过滤、旧模块不过滤，两页同一个产品会显示不同总量，用户会当 bug 报。

**Suggestion**：新接口显式 `is_deleted IS NOT TRUE`（方案已如此），并在设计稿登记「与 `/stock/inventory` 的口径差」；
是否回填既有一处由你决定，建议单独一个小修提交，别混进本功能。

---

### 🟢 NIT 1 — `inventory_log` 无保留期策略
`docs/performance-baseline.md:30` 记 25,072 行且只增不减。InvenTree 提供保留期设置（默认 365 天）。
25k 行现在无压力，但新历史接口会做范围筛选 + count；建议列入观察项，并确保新查询形状有索引（`operator_id` + `change_date` 复合索引按需再加）。

### 🟢 NIT 2 — `_increase_deduction` 的流水逐条写但缺 customer/操作人
`order/deduction.py:152` 起的 `InventoryLog(...)` 未带 `customer`，而同表的 `stock_return_service` 都带了。
同一张表的同一维度时有时无，会让「按客户看流水」出现空洞。本次线程化时一并补齐。

### ✅ PRAISE（不该被"借鉴"冲掉的本仓优点）
- `fastapi_app/shared/stock_concurrency.py`：**悲观锁 + 乐观锁双入口**，且 `_classify_update_miss` 把「库存不足」与「版本冲突」精确分离——
  比 ERPNext/Odoo 的纯应用层校验更硬（它们最终要靠重算队列兜底）。
- `order/deduction.py:95-113`：FIFO 抵扣 `with_for_update()` + 批量预取已抵扣量（**主动消除 N+1**）+ `stockin_id` 逐批回链，
  与 Odoo「按 lot 拆 move.line」等价，是本仓最像成熟 ERP 的一段代码。
- 退货**软取消**而非删除、`uq_inventory_log_idem` 请求级幂等、写完 commit 后统一失效缓存 + 发 WS 事件——
  这三处都优于同规模开源实现，改动时不要回退它们。

---

## 三、对已批准方案的修订建议

| 编号 | 修订 | 归属 | 阻塞实现？ |
|---|---|---|---|
| R1 | `inventory_log.product_id` → `SET NULL` + 冗余 `product_name`，或加删除守卫 | BLOCKER 1 | 需要一个产品决策（A/B） |
| R2 | `related_id` 提长（TEXT/200）+ 写入前长度防御 | BLOCKER 2 | 否，可与主迁移合并 |
| R3 | 加 `posting_date`（业务日期）列；历史接口默认按记账时序排序并在 UI 标注语义 | BLOCKER 3 | 否，但影响 API 契约（早定早改） |
| R4 | 顺手加 `stockin_id`（批次回链） | SUGGESTION 1 | 否 |
| R5 | `change_type` 收敛为常量表 + 守卫测试 | SUGGESTION 2 | 否，但要在写点线程化**之前**定，否则要改两遍 |
| R6 | 加结存自洽 CHECK 约束 | SUGGESTION 3 | 否，与 R4/R5 同一迁移 |
| R7 | 保留期/索引观察项写入设计稿 | NIT 1 | 否 |

**建议顺序**：先定 R1 + R5（两个决策点），再把 R2/R3/R4/R6 合并进迁移 `pg_standalone_073`，
最后才做写点线程化——否则写点签名要改两遍。

## 参考来源
- ERPNext `stock_ledger_entry.py`（`actual_qty`/`qty_after_transaction`/`batch_no`/`is_cancelled` 字段定义）：<https://github.com/frappe/erpnext/blob/develop/erpnext/stock/doctype/stock_ledger_entry/stock_ledger_entry.py>
- ERPNext 运行结存并发缺陷 #51562：<https://github.com/frappe/erpnext/issues/51562>；批次双存导致余额翻倍 #58995：<https://github.com/frappe/erpnext/issues/58995>
- ERPNext Repost Item Valuation（回溯重算机制）：<https://docs.frappe.io/erpnext/repost-item-valuation>
- Odoo `stock.quant` 字段（quantity / reserved_quantity / available_quantity / lot_id / inventory_diff_quantity）：<https://documentation.invantive.com/2017R2/odoo-data-model/webhelp/odoo-connector-stock-quant.html>
- InvenTree 库存追踪（user + 日期 + 数量变化、事件码表、删除后保留、保留期设置）：<https://docs.inventree.org/en/latest/stock/tracking/>
- InvenTree 批次可追溯（拆分后批次跟随）：<https://docs.inventree.org/en/latest/stock/traceability/>
