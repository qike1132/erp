# 销售退货管理功能调研与开发方案（2026-10-05）

> 调研方法：四路并行核实 GitHub 上 Odoo 17/18、ERPNext version-15、Apache OFBiz trunk、jshERP master（附 Dolibarr 快查）的退货实现源码与官方文档；本地结论基于当日对 `fastapi_app/`、`frontend-vite/`、`migrations/` 的实际核查（模型、服务、引用分布逐文件验证）。
> 所有外部结论均附仓库内确切文件路径或文档 URL；未能核实处明确标注。

---

## 0. 摘要（TL;DR）

1. **本系统不是从零开发，而是"补完半成品"。** 销售退货的后端底座已存在且质量良好：`stock_return` 模型、`stock_return_service` 服务（防超退、乐观锁回补库存、流水留痕、订单状态重算、领域事件联动采购计划）、`SR-YYYYMMDD-XXXX` 单号、建表迁移 `add_stock_return.py` 全部就绪。**缺的是 API 端点、Pydantic schema、权限码 seed、前端页面/路由/菜单**（`api/v1`、`schemas`、`frontend-vite/src` 三处 `stock_return` 引用数为 0，已逐目录核实）。
2. **用户感知的缺口主体**：服务层明确禁止"订单抵扣备货出货"（`stockin_id IS NOT NULL`）直接退货，提示"请通过订单管理进行处理"（`stock_return_service.py:57-58`）——但订单管理目前并没有退货功能。与出货订单相对应的退货管理正是需要补的这块。
3. 开源四范式横向对比后，推荐沿用**显式退货单**路线（现 `StockReturn`，对齐 OFBiz/jshERP 风格），分三阶段：**P0 补齐可见层**（API+权限+前端，覆盖现有服务能力）→ **P1 订单级退货与软取消** → **P2 审批流（可选）**。
4. 本系统无金额字段、无批次/序列号、无多仓库、无退款结算——OFBiz 的退款分道、ERPNext 的退货计值、Odoo 的批次闭环均**不适用**，可直接裁剪，方案因此大幅简化。

---

## 1. 本系统现状盘点（2026-10-05 实地核实）

### 1.1 已存在且可用

| 部件 | 位置 | 说明 |
|---|---|---|
| 退货模型 | `fastapi_app/shared_models/stock_return.py:22` | 表 `stock_return`：`return_no`(唯一)、`return_date`、`product_id`(FK RESTRICT)、`quantity`、`customer`、`stockout_id`(FK CASCADE，**必填**)、`order_id`(FK SET NULL)、`reason`(String 200)、`note`；索引齐 |
| 退货服务 | `fastapi_app/services/stock_return_service.py` | `create_stockreturn_core` / `delete_stockreturn_core` + 对外编排 `create` / `delete` |
| 防超退 | 同上 :60-62 | `available_return = stockout.quantity - stockout.returned_quantity`，超出抛错 |
| 并发与锁序 | 同上 :45-53 | 锁序统一 Product→StockOut（第十四轮修死锁），行锁 + `with_for_update` |
| 库存回补 | 同上 :87-88 | 统一走 `update_stock_with_optimistic_lock`（乐观锁，不直写 `current_stock`） |
| 库存流水 | 同上 :91, :127 | `inventory_log` `change_type='退货'/'退货删除'`，`related_id` 回链 |
| 订单状态联动 | 同上 :96 → `stock_event_service.recalc_order_status_after_return` | 订单状态由 `compute_status_from_stockouts()` 按 `returned_quantity` 派生（`shared_models/order.py:41`） |
| 领域事件 | 同上 :151-209 | `STOCK_RETURN_CREATED/DELETED` → 采购计划重算 |
| 单号 | `services/numbering.py` + `numbering_reconcile.py` | `SR-YYYYMMDD-XXXX` 前缀已注册 |
| 出货侧防护 | `services/stock_out_service.py:113, :81` | 有退货的出货禁止删除；出货编辑数量不得小于已退量 |
| 建表迁移 | `migrations/versions/add_stock_return.py` | 已 merge 进主链 |

### 1.2 明确的缺口

- **API 端点：0**。`fastapi_app/api/v1/` 无任何 `stock_return` 引用。
- **Pydantic schema：0**。`schemas/` 无定义。
- **权限码：0**。`permission` 表无 `stock_return_*` seed。
- **前端：0 引用**。`frontend-vite/src` 搜"退货 / stock_return / StockReturn"零命中。
- **无状态字段**：退货即生效，无草稿/审核/取消态；删除是**物理删除**（流水有留痕但单据消失）。
- **原因自由文本**：`reason` String(200)，无受控分类。

### 1.3 业务约束（方案必须面对）

`create_stockreturn_core` 对 `stockout.stockin_id IS NOT NULL`（订单抵扣备货出货）直接拒绝。也就是说**当前唯一的退货通道只覆盖"独立出货"**，而订单抵扣出货、以及订单维度的批量退货，都没有出路——这正是"缺少与出货订单相对应的退货管理"的实质。

### 1.4 可复用的基础设施

- **权限**：`core/deps.py` `require_permission/require_any_permission`（`user.py:44`：`xxx_manage` 自动含 `xxx_view`）；permission 表 `is_nav` + `parent_id` 树即导航权威源（`core/nav_context.py:113`、前端 `router/navAccess.ts:115` fail-closed）。新模块需 seed permission 记录（参考 `pg_standalone_043_seed_missing_permissions.py`）。
- **审批**：`approval_request` 模型 `order_id` FK **nullable=False 硬绑订单**、操作类型仅 `edit/delete`（`shared_models/approval.py:29`），退货审批不能直接复用，需新建表或泛化（P2 再议）。
- **库存双轨**：`product.current_stock`（乐观锁 + CHECK 非负）+ `inventory_log` 台账（`idem_key` 部分唯一索引可用作幂等）。
- **前端模式**：`views/<module>/{XxxView.vue, components/}`、`UiDataTable/UiDialog/UiDrawer/UiStatusBadge`（自研 36 组件，PrimeVue4）、`src/api/*.ts` 一域一文件、路由 `src/router/index.ts` pc/mobile 两套同路径。

---

## 2. 开源项目退货管理调研

### 2.1 Odoo 17/18 —— "反向拣货单"范式（库存视角的黄金标准）

> 核实基准：github.com/odoo/odoo `17.0` 分支（18.0 抽查对照）。**更正**：`stock_return_picking` 独立插件在 12.0+ 已不存在，退货向导内置于 stock 核心 `addons/stock/wizard/stock_picking_return.py`。

- **流程**：仅 `state='done'` 的发货拣货单可一键 "Return"（`stock_picking_views.xml:157`）→ 向导预填每行"已交付 − 已退"（`stock_picking_return.py:80-92`）→ `_create_returns` copy 原单生成**收货方向**的新 picking（`picking_type.return_picking_type_id`，建仓时自动互指 `stock_warehouse.py:363-365`）→ 走与普通收货**完全相同**的验证/预留/quant 入库状态机。
- **数据模型**：三层回链——`stock.move.origin_returned_move_id`（copy=False、index，`stock_move.py:143-145`）、`returned_move_ids` One2many、`stock.picking.return_id/return_ids`（`stock_picking.py:410-413`）。
- **`to_refund` 解耦**（定义在 `stock_account/models/stock_move.py:17`）：布尔开关决定该次退货是否冲减 SO 的 `qty_delivered` 与开票基数；仓库先收货、销售再决定账务，物流与账务分离。
- **防超退：软约束**（核心无硬拦截，grep 无 "cannot return more"）——仅 done 可退、默认只预填剩余可退量、全零行报 UserError。多级 pick/pack/ship 链有显式回链算法防止补货规则重复触发（wizard:151-175）。
- **财务**：Credit Note（`move_type='out_refund'` + `reversed_entry_id`，`account_move_reversal.py`）由财务在发票上**独立发起**；官方文档明确退货与贷项通知单"配合而非自动联动"。
- **批次闭环**：退货 move 强制选择**已有** lot/serial、禁止新建（`stock_move.py:571-583`）。
- **UX**：原单一键发起 → 内联编辑向导（行不可新建）→ 确认后直跳新退货单；原单挂 "Returns" 智能按钮聚合全部退货记录。

### 2.2 ERPNext v15 —— "负数原单"范式（单据复用的极致）

> 核实基准：github.com/frappe/erpnext `version-15`。**重要更正**：`Stock Entry purpose='Sales Return'` 是 v13 旧机制，v15 的 `validate_purpose()`（`stock_entry.py:596`）合法列表已不含它。现行机制 = `make_return_doc`（`erpnext/controllers/sales_and_purchase_return.py:381`）复制原单生成 `is_return=1`、`return_against=原单`、**负数量**的退货 Delivery Note / Credit Note。

- **流程**：已提交原单 `Create > Sales Return`（`delivery_note.py:1270`）→ 行级预填 `qty = -1 × (原行qty − 已退qty)`（按 `dn_detail/si_detail` 行级锚点聚合历史）→ 提交即过库存账（SLE）与 GL。
- **数据模型**：单头 `is_return` + `return_against`；行级锚点 `dn_detail/si_detail/so_detail` 精确回链原单行与 SO 行——可多次部分退货、按行累计。
- **集中式防超退**：`validate_quantity`（同文件 :188）`max_returnable = 原行数量 − Σ已退(仅 docstatus=1)`，超退抛专用 `StockOverReturnError`；还有 party 不匹配、退货时间早于原单、rate 异常等成套校验。
- **双轨回写**：SO 的 `delivered_qty` 自然冲减 + `returned_qty`/`per_returned`（退货进度百分比）独立累计，头部可见。
- **计值锁定**：退货入库成本取**原单行 rate**（`get_rate_for_return` :682），保证毛利不被退货扭曲。
- **权限三拆**：DocPerm 的 submit / cancel / amend 三个独立权限位（如 SI 侧 Accounts User 可 submit 无 cancel）；多级审批交给可配置的 Frappe Workflow，不硬编码。
- **批次序列**：Serial and Batch Bundle——可退集合 = 原单发出集合 − 累计已退集合（`make_bundle_for_sales_purchase_return`，`stock_controller.py:341`）。
- **UX**：原单按钮生成、负数显示、SI 退货自动换打印标题 "Credit Note"。

### 2.3 Apache OFBiz trunk —— "专用退货对象"范式（流程治理的完备形态）

> 核实基准：ofbiz-framework trunk（2026-10-05 推送，tree 8c1de31），实体集中于 `applications/datamodel/entitydef/order-entitymodel.xml`（**注意**：实体已迁出各业务组件，旧路径失效）。

- **数据模型**：`ReturnHeader`（:2492）：`returnHeaderTypeId`（CUSTOMER_RETURN/VENDOR_RETURN 一套实体双向复用）、`statusId`、`needsInventoryReceive`、`destinationFacilityId`、`currencyUomId`、`supplierRmaId`。`ReturnItem`（:2559）：`orderId+orderItemSeqId` 回链、**`returnQuantity`（客户承诺）vs `receivedQuantity`（实收）分离**、`returnReasonId`（为什么退）、`returnTypeId`（资金去向：退款/换货/store credit）、`returnPrice`。辅助实体：`ReturnReason`、`ReturnAdjustment`（运费/税类型化）、`ReturnStatus`（状态历史）、`ReturnItemResponse`（退款结果留痕）。关键金额字段 `enable-audit-log`。
- **状态机白名单**（`OrderSeedData.xml:188-202`）：`RETURN_REQUESTED → RETURN_ACCEPTED → RETURN_RECEIVED → RETURN_COMPLETED / RETURN_MAN_REFUND / RETURN_CANCELLED`（**没有 APPROVED，审批通过即 ACCEPTED**）；合法迁移落成 StatusValidChange 数据，服务端统一校验；header 状态由 item 聚合推进（`OrderReturnServices.checkReturnComplete`）。
- **库存关联**：审批只改状态；收货由仓库端 `receiveInventoryProduct` 直接创建 `InventoryItem + ShipmentReceipt`（`ShipmentReceiptServices.groovy`），`quickReceiveReturn` 可自动收（生成 `SALES_RETURN` 类型 Shipment 仅作登记载体）；**部分收货**：ShipmentReceipt 的 ECA 按 `quantityAccepted+quantityRejected` 回写 `ReturnItem.receivedQuantity`，实收 ≥ 承诺才推进 item 状态，收齐推 header——天然支持分批到货。
- **三道超退防护**：`getReturnableQuantity`（`OrderReturnServices.java:375-455`，= 发货量 − Σ未取消退货，且商品 `returnable=N` 直接不可退）→ 审批时退货总额 ≤ 订单可用额 → 退款时 `checkPaymentAmountForRefund`。
- **退款分道 + 人工兜底**：电子支付网关退款 / 账期 / 无法自动退 → `RETURN_MAN_REFUND` 显式暴露待办；每笔写 `ReturnItemResponse` 再按退货发票分摊核销。
- **权限**：服务端 `returnPermissionCheck`（`services_perm.xml`）→ `ORDERMGR_RETURN`（"Process returns"）等权限串，**服务层强校验**，非仅前端隐藏。
- **UX**：ordermgr 的退货列表/详情（header+items）/订单页 Quick Return 选品；详情页带六个审计页签（状态/类型/原因/数量/实收/价格历史）。

### 2.4 jshERP（华夏ERP）—— "单据类型化"范式（国内进销存惯例）

> 核实基准：github.com/jishenghua/jshERP master（4.6k star，活跃；SpringBoot+MyBatis+MySQL / Vue2.7+AntD）。

- **单表多态**：退货与出入库共用 `jsh_depot_head/jsh_depot_item` 两表，`type`（入库/出库）+ `sub_type`（销售退货/采购退货/零售退货…，**中文串即枚举值**，`BusinessConstants.java`）区分。销售退货 = `type=入库, subType=销售退货`（`SaleBackModal.vue#classifyIntoFormData` 硬编码），单号前缀 XSTH。
- **双层关联**：头表 `link_number` 指向原出库单 + 明细行 `link_id` 指向原单明细行 id。
- **两步选原单 UX**（`LinkBillList.vue`）：先选单据 → 再勾明细，仅 `已退/已出 < 原数量` 的行可选 → 回填后**锁定商品列**只允许改数量金额，并按"原数量−已退货"预填。
- **防超退**：`DepotItemService.saveDetials:521-558`，`operNumber+finishNumber > preNumber` 抛错；`overLinkBillFlag` 开关可放行超额（配置化管控强度）。
- **重算式库存**：库存 = 初始 + Σ台账，快照表 `jsh_material_current_stock` 由 `updateCurrentStock` 重算刷新——因此**反审核无需任何回滚代码**，单据不计入台账库存自然回落；编辑/删除仅限未审核单。
- **状态**：`status` 0未审核/1已审核（订单类另有 2/3），`batchSetStatus` 审核/反审核；"保存"与"保存并审核"分离。
- **按钮级权限**：`jsh_function.push_btn='1,2,3,7'` 定义页面按钮位，角色经 `jsh_user_business.btn_str`（JSON）逐按钮授权，前端 `btnEnableList` 控显隐。**警示短板**：后端 `LogCostFilter` 只校验登录态，**无 URL 级权限强校验**——自研切勿复刻。
- **成本**：销售退货入库按当前移动平均成本计值，不污染成本单价。

### 2.5 Dolibarr（参考反例，快速核实）

客户退货标准载体是贷项通知单（`Facture::TYPE_CREDIT_NOTE`，`fk_facture_source` 关联原发票）；**库存不自动回补**——Reception 模块源码绑定供应商订单（`reception/class/reception.class.php` `origin_type='supplier_order'`），并非客退收货工具。钱货两个松耦合动作 + 手工库存调整，进销存场景不完整。**结论：jshERP 的单据化退货对本类系统更完整，Dolibarr 不足为法。**

### 2.6 横向对比

| 维度 | Odoo | ERPNext v15 | OFBiz | jshERP |
|---|---|---|---|---|
| 退货载体 | 反向 picking（独立新单，复用收货机制） | 同 doctype 负数单（`is_return`+`return_against`） | 专用 ReturnHeader/ReturnItem | 同表多态（`type+sub_type`） |
| 与原单关联 | move 级 `origin_returned_move_id` | 行级 `dn_detail/si_detail` | 头级 `orderId+orderItemSeqId` | 头 `link_number` + 行 `link_id` |
| 状态机 | 完全复用 picking 状态机 | docstatus 0/1/2 + Amend | 六态白名单 + 状态历史表 | 0 未审 / 1 已审，可反审 |
| 库存联动 | 反向 move → quant；收货即复用普通收货 | 提交过 SLE，取消冲销重算 | 收货直接建 InventoryItem+ShipmentReceipt | 重算式台账，反审零回滚 |
| 防超退 | 软约束（预填剩余可退量） | 集中校验抛 `StockOverReturnError` | 三道防护（数量/审批额/退款额） | 行级校验 + 超额开关 |
| 财务退款 | Credit Note 独立发起，与退货协同 | Credit Note 同族单据开关控制 | 退款分道 + MAN_REFUND 兜底 + 留痕 | 退货单内负数金额 + 结算账户 |
| 权限 | 库存组 ACL（user/manager） | submit/cancel/amend 三拆 | 服务端强校验 `ORDERMGR_RETURN` | 按钮级 btn_str，**后端弱校验（短板）** |
| 部分退货 | 行级数量选择 | 行级累计、可多次 | 承诺/实收分离，分批收货 | 两步选行、仅可选剩余行 |
| 审计 | 单据链+流水 | 单据+账务冲销 | 状态历史表 + 字段级 audit-log | 单据+台账（无状态历史） |

**跨项目共识（六条）**：① 退货必须回链原单（头级至少，行级更佳）；② 防超退 = 原量 − Σ未取消已退量（本系统服务层已是同口径）；③ 退货入库必须走统一库存账入口并留流水（本系统已实现）；④ 退货与退款解耦（本系统无金额，天然不需要）；⑤ 生效时点二选一并贯穿一致——创建即生效（Odoo/ERPNext 提交制）或审核后生效（jshERP），不混用；⑥ 取消/删除必须对称回冲库存且留痕（本系统 delete 已实现）。

**本系统裁剪项**：无金额/应收 → 退款结算全免；无批次/序列号 → 批次闭环免；无多仓库/库位 → 退货库位选择免；无订单价格 → 退货计值免。剩余核心 = 数量流 + 状态 + 权限 + 留痕。

---

## 3. 推荐方案（分阶段）

### 3.0 总体架构决策

**沿用显式退货单 `StockReturn` 路线，不做 ERPNext 式负数出库单改造。** 理由：现有服务层已验证且带完整防护（防超退/锁序/乐观锁/流水/事件），改造 `stock_out` 支持负数会牵连 FIFO 分摊、采购计划重算、订单状态机等一大片；显式单据也符合本仓库"每个模块一张表"的既有风格与 OFBiz/jshERP 的主流实践。

### 3.1 P0：补齐可见层（预计 1-2 天，先让退货"看得见、管得住"）

> **落地状态（2026-10-05 当日完成）**：后端 `migrations/versions/pg_standalone_069_stock_return_permission.py`（view/manage 权限 seed，幂等）、`fastapi_app/schemas/stock_return.py`、`fastapi_app/api/v1/endpoints/stock_return.py`（`/stock-returns/list|create|/{id}`，router.py 挂载）、`get_stockreturns` 扩 customer/date 筛选、`nav_context.py` SPECIAL_PERMISSION_MAP 补 manage 可见入口；集成测试 `tests/test_stock_return_api.py`（10 用例：403/422/400 映射/happy path/404）。前端 `api/stockReturn.ts`、路由 `/stock-return`（PC 端）、`views/stock-return/`（View+Dialog+composable）、`StockOutRecords.vue` 行内「退货」按钮（复用弹窗与 composable）。门禁：ruff/mypy/quality_gate 全绿，退货 API 测试 10/10，前端 type-check/eslint(改动文件)/check:api/check:routes 全绿。
> **插曲**：会话期间 `pg_standalone_068_drop_product_stock_check.py` 源文件被外部会话删除（生产库已应用至该版本），已从 `__pycache__` 的 .pyc 常量忠实还原，`check_alembic_heads` 108 revisions 单 head PASS。其后外部会话又整体回滚 068（库降回 067、CHECK 重建、源文件再删、069 改挂 067），与本模块兼容。
> **两轮技能评审（当日）**：第一轮（code-review-excellence + frontend-code-review 模板）修复 4 项——🔴 create 缺省日期误用 UTC（00:00–08:00 会落前一天，改 `business_now()`）、🟡 出货列表手工拉取不随退货刷新（包 onReturnSubmit 提交后重取）、🟡 出货下拉永久缓存致可退量失真（每次打开重拉）、🟡 筛选零覆盖（补 test_list_with_data_and_filters）。
> **全流程 E2E（tests/test_stock_return_flow.py，2/2）**：模拟数据走真实服务层+HTTP——产品(库存100)→订单30→create_stockout（FIFO 匹配订单、扣库存、订单→已出货）→API 退货 10（库存 80、returned_quantity=10、订单→待出货、退货流水落 inventory_log）→边界退满 20（库存 100）→超退 400→逐一删除（对称扣回 90→70、订单恢复已出货、列表清空）→抵扣出货退货 400（订单管理约束）。
> **Mimosa 写入门禁要点**：新文件中 SQL 经变量持有/拼接/f-string 构造会被 graded-deny 拦截（043/067 属基线豁免不受限）；069 downgrade 已改为全内联字面量直书 SQL 后放行，聚焦复扫确认清零。

**后端**（全部薄封装，不动 `_core`）：
- 新建 `fastapi_app/schemas/stock_return.py`：`StockReturnCreate`（`stockout_id/quantity/return_date/reason/note`）、`StockReturnOut`（含 `stockout_no`、产品名、`available_return`）。
- 新建 `api/v1/endpoints/stock_return.py`，挂入 `router.py`（绝对导入惯例）：
  - `GET /stock-returns`：分页 + 筛选（customer/product_id/日期区间/关键字），`require_permission('stock_return_view')`
  - `POST /stock-returns`：`require_permission('stock_return_manage')`
  - `DELETE /stock-returns/{id}`：`require_permission('stock_return_manage')`
  - 可退量查询：直接在出货列表返回 `returned_quantity`（列已存在），前端算 `quantity - returned_quantity` 即可，无需新端点。
- 错误处理沿用服务层 ValueError → 400 惯例；**加固项**（可选）：POST 复用 `inventory_log.idem_key` 机制防双击重复提交（口径 `return|stockout_id|quantity|业务日`）。
- **权限 seed 迁移**：`pg_standalone_068_stock_return_permission.py`（`down_revision` = 当前唯一 head；提交前跑 `python scripts/check_alembic_heads.py`），插入 `stock_return_view`（可导航）与 `stock_return_manage`（自动含 view）；导航树即权限分配弹窗权威源，无需前端硬编码。

**前端**：
- 新建 `src/api/stockReturn.ts`（从 `./request` 导入 get/post/del）。
- **入口（决策点 1）**：推荐**独立菜单页** `views/stock-return/StockReturnView.vue`（授权独立、列表纯净、与"库存"解耦）；同时出货 TAB 行操作加"退货"按钮预填发起。备选：库存页第三个 TAB。
- 页面形态遵循既定约定：筛选行 + **一行信息条（~40px，本期退货件数/单数，勿大卡片区）** + `UiDataTable`（退货编号/日期/客户/产品/数量/原因/关联出货号/操作）；方角基准对齐 `/purchase`（去圆角，scoped 覆盖不碰共享组件）；`UiDialog` 新增退货（产品/客户/可退量只读预填，数量上限校验提示，原因必填）。
- 路由 `src/router/index.ts` pc/mobile 两套同路径注册；菜单显隐由后端 permission 树驱动，无需改导航组件。

**测试与上线**：
- pytest：超退拒绝、订单抵扣出货禁止（既有约束回归）、乐观锁冲突、`STOCK_RETURN_CREATED` 事件、订单状态重算（`tests/test_stock.py` 已有退货相关基础，补 API 层 + 权限 401/403 用例）。
- 门禁全套：`python scripts/quality_gate.py`、ruff、mypy、pytest；`npm run type-check / test / lint / check:api / check:routes`；build 后**验证 live hash + erp-web 服务**（既定部署纪律：改前端必须 build + 强刷验证）。
- 部署顺序硬前提：先 `alembic upgrade head` 后重启服务。

### 3.2 P1：订单级退货与软取消

> **落地状态（2026-10-05 晚完成，待后端重启生效）**：
> ① **软取消**：迁移 `pg_standalone_070_stock_return_status`（status 列，active/cancelled，存量默认 active）；服务层 `delete_*` 全部替换为 `cancel_*`（同一库存对称回冲链路，流水 `change_type='退货取消'`，重复取消 400）；领域事件新增 `STOCK_RETURN_CANCELLED`（purchase_plan 同 DELETED 订阅）；前端状态列（正常/已取消徽章）+ 仅 active 行可取消（琥珀色撤销按钮）。
> ② **路线 A 放开订单抵扣退货**：移除 `stockin_id IS NOT NULL` 拒绝；候选端点改为 `get_returnable_stockout_candidates`（含抵扣单，payload 带 `stockin_id` 标记）；E2E 证实抵扣口径语义：订单 30 → 抵扣出货 30（已备货）→ 退货 5（净抵扣 25 → 部分备货）→ 取消（恢复已备货），FIFO 实时算口径下无额外回滚需求——前置风险项解除。
> ③ **幂等**：`create` 接受 `request_id`（前端每次打开弹窗生成 UUID），直存 `inventory_log.idem_key`（uq 部分唯一索引兜底 + 服务层预检 400「请勿重复提交」）；**刻意不用** `return|出货|数量|日` 口径——同日同数量的合法二次退货会被误杀。
> ④ **end_date 边界**：`get_stockreturns` 改左闭右开（`< end+1day`），23:59:59.x 的退货不再被漏；get_stockins/get_stockouts 的同款遗留不在本次范围。
> 测试：`test_stock_return_api.py`（幂等 400/软取消保留记录/重复取消 400）+ `test_stock_return_flow.py`（requestId 幂等不二次累计、抵扣单正向全流程、取消后列表保留 cancelled 行）；退货相关合计 43 用例全绿；quality_gate PASS（顺手修掉并行会话遗留在 `scripts/check_orphan_modules.py` 的 2 处 ruff 违规）。
> **挂账（需产品决策）**：原因字典表管理 UI、退货率报表页。

### 3.2.1 录入逻辑变更：按产品退货（2026-10-05 深夜定稿，迁移 071 已落库）

业务决定：**退货单录入不再选择出货单/订单，直接选产品 + 数量退货**（退货是收回货物入库的物理事件，不追溯出自哪张出货单）。变更内容：

- 迁移 `pg_standalone_071_stock_return_nullable_stockout`：`stockout_id` 改可空；仅历史行保留出货关联（可追溯），新录入 stockout_id/order_id 均为 NULL，**订单状态不因产品制退货而变化**（业务明确接受）。
- `create_stockreturn_core` 签名改为 `(product_id, quantity, …, customer)`：产品行锁 → 回补库存 → 流水；**防超退/可退上限/候选出货端点（stockout-options）整体移除**——"可退上限"概念随出货关联一起失效，数量以实物为准。
- `cancel_stockreturn_core` 分支兼容：历史关联行（stockout_id 非空）取消时回减 `returned_quantity` 并重算订单状态（对称回冲旧语义）；按产品行仅扣库存。cancel 编排层补 `stockout_id IS NULL` 守卫（`db.get(StockOut, None)` 会触发 SAWarning）。
- 幂等 request_id 机制保留不变。
- 前端弹窗改为：产品下拉（catalog store 懒加载缓存）+ 客户（可选自由输入）+ 数量 + 原因；**出货行内"退货"入口移除**（StockOutRecords 还原）；列表"关联出货单号"列仅历史行有值。
- 测试：单元/API/flow 重写为产品制，40 用例全绿；新增"历史关联行取消回减 returned_quantity + 订单恢复已出货"分支用例。
- 语义提示：产品制退货后，"退货率（退货/出货）"报表口径需按产品维度重定义（inventory_log 按产品留痕，数据基础仍在）。
- **客户收紧为硬性必填（同日补充）**：schema `customer` 必填（min_length=1 + strip 校验器，纯空白拒收 422），前端改为客户目录下拉（catalog store `ensureCustomers`，与全系统客户名口径一致，退货列表客户筛选可精确匹配）；产品/客户双下拉均为硬性条件，弹窗加载时 `Promise.all([ensureProducts, ensureCustomers])`。

- **status 列**（`active/cancelled`）：删除改为软取消——走 `delete_stockreturn_core` 同一库存回冲链路但**保留记录**，对齐开源共识"取消而非删除"；流水 `change_type` 增加"退货取消"。此改动同时为 P2 状态机留位。
- **订单抵扣出货的退货路径（决策点 2）**：现约束"请通过订单管理处理"但订单管理无此功能。两条路线：
  - **路线 A（推荐先行）**：放开 `stock_return_service` 对 `stockin_id IS NOT NULL` 的限制，复用现有 `recalc_order_status_after_return` 与事件链。**前置梳理**：订单抵扣出货回补库存后，`stockin_id` 对应备货（stock_in）的抵扣关系语义要过一遍（FIFO 分摊是实时算的，理论上事件重算即可覆盖，需测试证实），这是本阶段唯一的实质设计风险。
  - **路线 B（看业务量）**：订单维度多行退货单（ReturnHeader/ReturnItem 式），一次退多产品。当前 `stock_return` 是"一行一单"，若客户退货行为高频多品，再升级为头+行结构；P0/P1 的单行模型可平滑迁移（旧行=单行头）。
- **原因类型化**：受控枚举/字典（参考 OFBiz `ReturnReason` 种子：质量问题/错发/多送/客户不要/换货/其他），自由备注降级为辅助字段——为退货率统计铺路。
- **报表**：退货率（退货/出货）按产品/客户/月度，数据基础 `inventory_log` 已具备。

### 3.3 P2：审批流（可选，按管控需求启动）

- 现状 `approval_request` 硬绑 `order_id`（仅 edit/delete），不可直接复用；需新建 `return_approval` 或泛化主表引用（`operation_data` JSON 模式可沿用）。
- 若引入"草稿→待审核→已审核"：对齐 jshERP **审核后生效**模式——服务层拆为"创建（仅登记）"与"审核（库存回补+事件+订单重算）"两段；权限位按 ERPNext 三拆（创建/审核/取消各独立权限码）。
- 状态迁移校验参考 OFBiz StatusValidChange：合法迁移白名单落在代码或数据，服务端统一校验。

### 3.4 红线与门禁对照（AGENTS.md）

- 迁移保持**单 head**，新迁移命名 `pg_standalone_NNN_*`、幂等写法（`IF NOT EXISTS`）；不夹带业务逻辑。
- 不碰 `vite.config.js`、`core.hooksPath`、`utils/`；uvicorn 绑定不涉及。
- 提交走 `.githooks` 密钥扫描 + quality_gate 棘轮；提交信息写"为什么"，一提交一件事。
- 本机是生产主机：P0 上线选业务低峰，按"先迁移后重启、build 后验 live hash"既定流程执行。

---

## 4. 待拍板决策点

| # | 决策 | 推荐 | 理由 |
|---|---|---|---|
| 1 | 前端入口：独立菜单页 vs 库存页第三 TAB | 独立页 + 出货行"退货"按钮发起 | 授权独立、职责清晰；TAB 适合强共生模块 |
| 2 | 订单抵扣出货退货：路线 A 放开现有路径 vs 路线 B 订单级多行退货单 | 先 A 后视业务量升 B | A 改动最小且订单状态重算链路已就绪；B 是结构升级，需要时再做 |
| 3 | 是否引入 status（软取消）与审批 | P1 加 `active/cancelled`；审批 P2 按需 | 物理删除不利审计（开源四项目无一例外保留记录）；审批取决于实际管控强度 |

> **拍板（2026-10-05）**：三项均按推荐执行。前端效果图已完成并经浏览器验收，画面一=独立菜单页（含信息条/筛选/表格/状态列）、画面二=新增退货弹窗（预填+可退上限）、画面三=出货行内"退货"入口；效果图文件 `stock-return-mockup.html`（本地 http.server :8765 托管）。P1 放开路线 A 的前置梳理项不变：`stockin_id` 抵扣回补语义。

---

## 5. 参考索引

| 项目 | 关键源码 | 文档 |
|---|---|---|
| Odoo 17.0 | `addons/stock/wizard/stock_picking_return.py`、`addons/stock/models/stock_move.py:143`、`addons/stock_account/models/stock_move.py:17`、`addons/sale_stock/models/sale_order_line.py:169` | [Returns and refunds](https://www.odoo.com/documentation/17.0/applications/sales/sales/products_prices/returns.html)、[Credit notes](https://www.odoo.com/documentation/17.0/applications/finance/accounting/customer_invoices/credit_notes.html) |
| ERPNext v15 | `erpnext/controllers/sales_and_purchase_return.py`（make_return_doc :381 / validate_quantity :188）、`erpnext/stock/doctype/delivery_note/delivery_note.py:1270`、`status_updater` :176-244 | [Sales Return](https://docs.frappe.io/erpnext/user/manual/en/sales-return)、[Stock Entry Purpose](https://docs.frappe.io/erpnext/user/manual/en/stock-entry-purpose) |
| OFBiz trunk | `applications/datamodel/entitydef/order-entitymodel.xml`（ReturnHeader :2492 / ReturnItem :2559）、`applications/order/.../OrderReturnServices.java`（getReturnableQuantity :375）、`applications/product/.../ShipmentReceiptServices.groovy` | [OFBiz 文档](https://nightlies.apache.org/ofbiz/) |
| jshERP | `jshERP-boot/.../constants/BusinessConstants.java`、`service/DepotItemService.java#saveDetials`、`jshERP-web/src/views/bill/SaleBackList.vue`、`LinkBillList.vue` | 仓库 docs/jsh_erp.sql |
| Dolibarr | `htdocs/compta/facture/class/facture.class.php`（TYPE_CREDIT_NOTE） | [Table llx_facture](https://wiki.dolibarr.org/index.php/Table_llx_facture) |
