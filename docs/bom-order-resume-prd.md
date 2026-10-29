# BOM 缺失下单续提增量 PRD

> 状态：产品需求草案（基于现行代码只读调查）；本文描述目标行为，不表示功能已经实现。

## 1. 项目信息

- **Language**：中文
- **Programming Language**：沿用现有 Vue 3 + TypeScript + Vite 7 / FastAPI，不引入新前端框架
- **Project Name**：`bom_order_resume`
- **原始需求**：当检测到商品未配置 BOM 时，用户点击下单、提交等相关操作后，直接跳转至 BOM 配置页面，并携带商品信息及原下单流程上下文；BOM 保存成功后自动返回原采购页面，保留已填写的下单数据，重新校验通过后续原下单流程，避免重复提交。
- **本期默认范围**：PC 端 `/purchase` 缺 BOM 待生成行，单条来源记录（`order:<id>` 或 `stockin:<id>`）；移动端与批量续提不进入 P0。

## 2. 现状流程与代码证据

### 2.1 现行主流程不是“未提交表单 → 人工审核”，而是“来源单已保存 → 自动生成采购单”

1. 客户订单或备货记录先持久化；对应写路径注册 `schedule_auto_generate_purchase_orders`，事务提交后扫描并生成采购单。
2. `/purchase` 将待生成来源记录与已生成采购单并列展示。缺 BOM 行目前只有只读文案“未配置BOM，无法下单”，没有下单按钮、跳转事件或表单提交。
3. 多 SKU 来源单必须全部 SKU 均有 BOM 才进入自动生成候选；保存 BOM 后，后端在 BOM 事务提交成功后再次自动生成。
4. 因而本期“保留已填写的下单数据”首先指**不清空、不重复创建已经持久化的 Order/StockIn 来源单及其 SKU 数量、抵扣、备注等数据**，而不是把来源单创建表单重新提交一次。

### 2.2 前端证据

| 文件 / 关键函数 | 当前事实 | 对本需求的影响 |
|---|---|---|
| `frontend-vite/src/router/index.ts` | 已有 `/purchase`、`/product`；没有独立 `/bom` 路由 | 默认复用 `/product` + 查询参数自动打开 BOM 编辑器，无需新增页面壳 |
| `frontend-vite/src/views/purchase/PurchaseView.vue` | 渲染 `ActiveOrdersPanel`；现有操作为“汇总下单”“下单完成/批量确认” | 新入口放在缺 BOM 待生成行，不改变已生成采购单的汇总/完成逻辑 |
| `frontend-vite/src/views/purchase/components/ActiveOrdersPanel.vue` | `u.has_bom` 为真显示“生成中…”，否则仅显示缺 BOM 文案；待生成行不可勾选 | 将缺 BOM 文案升级为可执行入口；`composite_id`、`record_type`、`items` 可作为上下文基础 |
| `frontend-vite/src/views/purchase/composables/usePurchaseHandlers.ts` | 初始加载并每 30 秒刷新待生成/待生产列表，WebSocket 也触发刷新 | 返回后仍须显式等待新鲜校验结果，不能只依赖轮询或推送 |
| `frontend-vite/src/views/purchase/composables/useUnprocessedOrders.ts` | `useUnprocessedOrders` 是只读数据源，不含选择或生成动作 | 本期新增续提编排，不恢复旧人工审核页签 |
| `frontend-vite/src/views/purchase/composables/usePurchaseActions.ts` | `handleSummary`、`handleCompleteOrder`、`handleBatchComplete` 均操作已生成采购单；旧 `handleOneClickGenerate` / `handleQuickGenerate` / `handleNoBomError` 已移除 | “汇总下单”“下单完成”不是本期缺 BOM 触发入口 |
| `frontend-vite/src/views/product/ProductListView.vue` | `openBomEditor(p)` 调用编辑器暴露的 `open`；当前不读取路由查询参数 | 需支持按 `product_id` 加载产品并自动打开，且处理无效/无权限上下文 |
| `frontend-vite/src/views/product/components/BomEditor.vue` | BOM 是 `/product` 内模态编辑器；`saveBom`、`requestCloseBom` 已存在；`defineExpose({ open: openBomModal, bomDirty })` | 可复用编辑器与未保存确认，不另写一套 BOM 表单 |
| `frontend-vite/src/views/product/composables/useProductListActions.ts` | `openBomModal` 加载 BOM；`saveBom` 有 `bomSaving` 防重，成功后仅关闭弹窗并失效查询，没有保存成功回调或返回原路由；失败保留弹窗 | 需增加可选续提回调/返回编排，保持普通产品页保存行为不变 |
| `frontend-vite/src/api/purchase.ts` | `purchaseApi.unprocessedOrders`、`oneClickGenerate`；`bomApi.loadBom/saveBom` 已存在；`oneClickGenerate` 当前只传 body，未暴露 `X-Idempotency-Key` | 续提复用现有 API 域，不调用客户订单/备货创建接口；P0 需补齐幂等键请求头契约 |
| `frontend-vite/src/api/index.ts` | 兼容层 `productApi = { ..._core, ...bomApi }` | 当前 BOM 编辑器实际经该兼容层调用 BOM API |
| `frontend-vite/src/types/index.ts` | `UnprocessedOrderItem` 含 `product_id/product_name/product_barcode/has_bom`；`UnprocessedOrder` 含 `composite_id/record_type/items`，但手写类型漏了后端已返回的顶层 `product_id/source_order_id` | 多 SKU 可逐行定位缺 BOM 产品；旧数据回退所需字段需补齐类型，不得靠 `any` 猜测 |
| `frontend-vite/src/api/request.ts` | 写请求默认不自动重试，只有调用方显式声明幂等才允许有限重试 | 响应未知时不能盲目换键重发；续提键必须在同一尝试内稳定 |

### 2.3 后端证据

| 文件 / 关键函数 | 当前事实 | 对本需求的影响 |
|---|---|---|
| `fastapi_app/api/v1/endpoints/purchase_center/product_routes.py::api_save_product_bom` | 保存 BOM 后注册 `schedule_bom_saved_side_effects`；写权限为 `product_manage` | 保存成功已经会触发采购自动生成；采购-only 用户不能默认获得 BOM 写权限 |
| `fastapi_app/core/exceptions.py::db_transaction/run_post_commit_callbacks` | commit 成功后等待 post-commit 回调执行，回调失败被隔离 | 正常响应返回时，本次自动生成尝试已结束，可立即回采购页重新校验 |
| `fastapi_app/services/purchase/_auto_generate.py` | `_run_bom_saved` 先处理删空撤销，再 `_run_auto_generate`；自动生成是 best-effort，失败不影响 BOM 保存 | “BOM 保存成功”不等于“采购单一定生成成功”，必须有续提失败/重试路径 |
| `fastapi_app/services/purchase/_unprocessed.py` | `_order_has_bom` 要求全部 SKU 有 BOM；`list_auto_generate_candidates` 排除已处理或缺 BOM 来源；响应含逐 SKU `has_bom` | 多 SKU 必须逐份补齐，不能在第一份 BOM 保存后强行下单 |
| `fastapi_app/services/purchase_order_generate.py` | `auto_generate_purchase_orders` 与人工端点共用 `generate_purchase_orders_from_customer_orders`；该函数重新加载来源单和 BOM，空物料会拒绝 | 续提应复用同一生成服务，以后端当前数据为准，不能用跳转前快照重算 |
| `fastapi_app/api/v1/endpoints/purchase_center/order_routes.py::api_one_click_generate_order` | 旧端点仍接收 `composite_ids` 与 `X-Idempotency-Key` | 默认强化并复用为续提入口，避免另建第二套生成算法 |
| 同上 + `purchase_order_generate.py::generate_purchase_orders_from_customer_orders` | 路由注释称同幂等键 10 分钟复用，但服务层 `idempotency_key` 目前仅为未来保留，未真正消费 | 不得把注释当作已有防重能力；P0 必须补齐真实幂等语义 |
| `fastapi_app/shared_models/purchase_order.py` | `uq_po_pending_dedup` 仅约束 `status='pending'` 的采购单 | 数据库唯一索引是重要兜底，但不能单独覆盖“已有 completed 单 + 旧续提请求”等路径 |
| `fastapi_app/services/purchase/_unprocessed.py` | 已处理判断优先使用 `purchase_order_sku.source_record_type + source_order_id`，并处理 Order/StockIn ID 撞号 | 幂等预查也必须区分来源类型和 ID，不能只用裸 ID |

### 2.4 现有测试与缺口

- `fastapi_app/tests/test_purchase_auto_generate.py`：覆盖 post-commit 时机、同事务去重、失败隔离、缓存/广播、缺 BOM 候选过滤、删空撤销；**不覆盖前端返回续提、已完成单幂等或自动/手动并发**。
- `fastapi_app/tests/test_purchase_center.py`：覆盖一键生成端点基本调用和参数缺失；不证明真实幂等键重放。
- `tests/test_po_dedup_index_migration.py`：只锁定 `uq_po_pending_dedup` 的结构，不等于续提全场景防重测试。
- `frontend-vite/src/test/purchaseOrderNoColumn.test.ts`：锁定缺 BOM 只读文案，后续应改为新入口行为断言。
- `frontend-vite/src/test/PurchaseView.autorefresh.test.ts`：覆盖采购列表刷新及徽标。
- `frontend-vite/src/test/bomEmptyStateGuard.test.ts`、`bomEditorUnsavedConfirm.test.ts`、`auditAUD18BomQuickCopy.test.ts`：覆盖 BOM 读取失败禁止保存、未保存确认、保存/复制互斥等，可复用这些安全约束。
- `frontend-vite/src/test/mobileViewsDataLayer.test.ts`：明确移动端待生成为只读且不调用一键生成。
- 当前没有“路由上下文保存/恢复、保存后自动返回、续提状态机、刷新/重复回跳”的测试。

## 3. 产品定义

### 3.1 Product Goals

1. **不断流**：采购员从缺 BOM 待生成行一步进入正确产品的 BOM 配置，保存后回到原采购上下文。
2. **不重复**：以来源单为边界自动续接原采购生成流程，重复点击、刷新、重试或自动生成并发均不得重复创建来源单/采购单。
3. **可恢复**：取消、保存失败、仍缺 BOM、生成失败、来源变化等路径均有明确状态和可继续操作，不出现静默丢单或无限跳转。

### 3.2 User Stories

- 作为采购员，我希望在缺 BOM 行点击“配置 BOM 并下单”，以便直接配置正确商品且不必返回后重新找单。
- 作为采购员，我希望 BOM 保存后保留原来源单和采购页上下文并自动续提，以便不重录数量、抵扣和备注。
- 作为采购员，我希望多 SKU 订单能逐份补齐缺失 BOM，以便只有全部齐备后才生成采购单。
- 作为采购员，我希望取消、失败、刷新或重复点击不会造成重复单据，以便安全地中断和恢复操作。

## 4. Requirements Pool

### P0（Must have）

1. **缺 BOM 行入口与权限**
   - `has_bom=false` 的待生成行提供“配置 BOM 并下单”按钮，保留缺 BOM 提示。
   - P0 只处理当前行的一个 `composite_id`；Order 与 StockIn 均支持。
   - 只有同时具备采购访问与 `product_manage` 的用户可执行配置；无 BOM 写权限者保留原因提示及“联系产品管理员”，不得跳转后才形成权限死路。后端仍独立鉴权。

2. **跳转与上下文**
   - 复用 `/product`，通过查询参数携带 `product_id` 和 `resume_attempt_id`，页面加载产品详情后自动打开同一 `BomEditor`。
   - 多 SKU 时从 `items` 选择 `has_bom=false` 的产品；旧数据无逐项信息时才使用顶层产品字段，无法解析产品 ID 时停止跳转并提示刷新。
   - 上下文保存原 `/purchase` 路由、当前行 `composite_id`、来源类型/ID、订单号（展示用）、待补产品列表、当前产品、尝试 ID/幂等键，以及采购页临时状态（活动页签、待生成/待生产页码、仍有效的选择、滚动位置）。
   - URL 只放必要 ID；完整上下文放当前标签页 `sessionStorage`，以尝试 ID 隔离。来源数量、抵扣、备注等不在 URL 中作为提交真相。

3. **BOM 保存成功自动返回与数据恢复**
   - 仅在 BOM API 明确保存成功后返回 `/purchase?resume=<attempt_id>`；普通 `/product` 编辑没有有效续提上下文时保持原行为。
   - 返回后恢复原采购页临时状态，并强制取得新鲜待生成数据；不得仅凭 sessionStorage 快照、WebSocket 或 30 秒轮询判定可续提。
   - 来源单始终使用后端当前 Order/StockIn 数据；不得重新调用来源单创建接口，也不得用旧快照覆盖用户/他人在跳转期间的修改。

4. **重新校验与自动续提**
   - 返回后不依据前端列表快照提前跳过；始终以同尝试、同幂等键调用一次权威生成校验。仍缺 BOM 时后端以 0 写入返回 `MISSING_BOM` 与精确 `missing_bom`，前端据此展示剩余 SKU 并保留“继续配置”入口。
   - 若全部 SKU 已齐备，或当前行已不在待生成列表：同一尝试只发起一次续提调用；后端必须再次权威校验来源、处理状态和全部 SKU BOM。
   - 下一份 BOM 必须优先使用服务端返回的 `missing_bom` / attempt 的 `pending_products`，不得从未刷新的采购列表 `items` 重新取首个缺 BOM 产品，否则会反复打开刚保存的 SKU。
   - 默认强化现有 `POST /purchase-center/orders/one-click-generate` 及其服务作为续提入口，复用 `generate_purchase_orders_from_customer_orders`；不得复制生成算法或重新创建来源单。
   - 续提响应必须能区分“本次新建”与“已有采购单幂等返回”，并返回关联采购单；不得出现“成功但 0 单且无法判断”的终态。来源无效/已删除必须返回可识别失败，而非新建。

5. **多 SKU**
   - 每次 BOM 保存成功均先返回原采购页；若仍缺其他 SKU，停留在采购页并提示“还需配置 N 个 SKU”，由用户点击继续下一份，避免自动往返循环。
   - 只有后端确认全部 SKU 齐备才允许生成；P0 不支持部分 SKU 提前生成采购单。

6. **异常与刷新恢复**
   - 取消、保存失败、仍缺 BOM、续提失败、来源失效、重复点击、刷新、浏览器前进/后退和重复回跳按第 5 节状态机处理。
   - 同一尝试在刷新后继续使用原尝试 ID/幂等键；终态或明确取消后清除上下文并移除 resume 查询参数，重复回跳不得自动发写请求。

7. **前后端防重**
   - 前端：入口导航单飞；沿用 `bomSaving`；续提 `resumeInFlight` 单飞；同一尝试固定幂等键；响应未知时不得换键重发；不得盲开写自动重试。
   - 后端：同键重放必须真实复用首次结果（默认落实现有 10 分钟语义或更强）；按“来源类型 + 来源 ID”预查关联采购单，**任意状态已存在均先幂等返回，再进入来源状态门控**；生成时再次校验并保留 `uq_po_pending_dedup` 作为最后防线。
   - 后端必须以事务/锁等机制覆盖“自动生成与续提并发”“完成操作与旧续提并发”，不能只靠前端按钮锁或 pending-only 索引。
   - 防重不得依赖 `has_bom` 文案、订单状态字符串或前端快照单独判断。

8. **测试与回归**
   - 覆盖第 7 节全部 P0 验收场景，并保留现有自动生成、BOM 安全护栏、采购汇总/完成测试。
   - 补齐 API/类型：`oneClickGenerate` 支持同一尝试的 `X-Idempotency-Key`，并同步 `UnprocessedOrder` 实际返回字段、续提请求/响应及生成层类型；通过对应前端 `check:*` 与后端聚焦测试。

### P1（Should have）

- 移动端提供同等续提能力；需先补移动端 BOM 编辑入口，不能仅把桌面路由强搬到移动端。
- 多 SKU 在用户明确选择“连续配置”时自动进入下一份 BOM，仍须每次经过后端校验。
- 返回后高亮/定位本次新建或幂等命中的采购单，并提供可复制的采购单号。
- BOM 未保存草稿的路由离开/刷新保护进一步增强；普通编辑与续提共用 dirty 语义。

### P2（Nice to have）

- 记录缺 BOM 进入率、配置完成率、续提成功率、幂等命中率和失败原因，用于发现长期滞留来源单。
- 批量来源记录统一点检与逐单续提；须另行定义部分成功和批量幂等，不在 P0 推断实现。

### 明确非目标

- 不恢复旧“待审核订单”页签或批量人工审核流程，不改变现行自动生成主策略。
- 不拦截已生成采购单的“汇总下单”“下单完成/批量确认”，不序列化与缺 BOM 流程无关的汇总弹窗未保存编辑。
- 不在客户订单、备货创建/导入页面增加全局跳转；这些入口继续保存来源单并自动生成。
- 不重写 BOM 角色/物料模型、生成算法或移动端 BOM 编辑器。
- 不支持跨标签页/跨浏览器共享续提上下文，不承诺恢复刷新前未保存的 BOM 输入草稿。
- 不用客户端快照替代后端来源单与 BOM 的当前值。

## 5. 返回与自动续提状态机

| 当前状态 | 事件 | 下一状态与必须行为 |
|---|---|---|
| `IDLE` | 点击缺 BOM 行 | 创建唯一 `attempt_id`、快照上下文，进入 `CONFIGURING`；重复点击不创建第二个尝试 |
| `CONFIGURING` | 取消/关闭 | 沿用 dirty 确认；确认离开后标记 `CANCELLED`，返回原采购页，不调用续提；来源单保持不变 |
| `CONFIGURING` | BOM 校验失败或保存 API 失败/`success=false` | 留在 `CONFIGURING`，不返回、不续提；保留 BOM 输入，解除保存锁后可重试 |
| `CONFIGURING` | BOM 保存成功 | 进入 `RETURNING`，返回原 `/purchase`；不得在保存成功回调里直接重复创建来源单 |
| `RETURNING` | 页面挂载 | 进入 `RESTORING_REVALIDATING`：恢复页面状态、强制刷新待生成数据；刷新失败则停留原页显示可重试错误，不发续提 |
| `RESTORING_REVALIDATING` | 当前行仍存在且仍缺 BOM | 调用权威生成校验；返回 `MISSING_BOM` 后进入 `WAITING_NEXT_BOM`，提示剩余 SKU，0 写入 |
| `WAITING_NEXT_BOM` | 点击继续配置 | 复用原 `attempt_id`，进入下一份 BOM 的 `CONFIGURING` |
| `RESTORING_REVALIDATING` | 当前行 BOM 已齐备，或行已消失 | 进入 `RESUMING`，用同一幂等键调用强化后的续提端点一次；行消失不能由前端直接等同成功 |
| `RESUMING` | 返回本次新建 | 进入 `DONE`，失效并刷新派生查询，展示采购单号；清除尝试上下文 |
| `RESUMING` | 返回已有采购单/幂等命中 | 进入 `DONE`，提示“采购单已生成，无需重复下单”，0 新增；清除尝试上下文 |
| `RESUMING` | 后端重新判定仍缺 BOM | 进入 `WAITING_NEXT_BOM`，以后端返回的缺失项为准，不生成、不循环跳转 |
| `RESUMING` | 来源删除、无效或无权限 | 进入 `ABORTED`，不生成；保留原采购数据并给出明确原因，清除自动续提能力 |
| `RESUMING` | 网络/服务失败或响应未知 | 进入 `RESUME_FAILED`，留在采购页；用户重试时先重新校验，再使用同一幂等键，不创建新尝试 |
| 任意非终态 | 刷新/重复回跳 | 从 sessionStorage 恢复同一尝试；先读后写。`RESUMING` 刷新不得盲目再次提交，必须先校验并复用同键 |
| `DONE/CANCELLED/ABORTED` | 浏览器后退、再次访问旧 resume URL | 上下文已消费，不自动保存、不自动续提、不重新打开旧流程 |

**状态真相原则**：前端列表只用于减少明显无效的调用；最终“可生成 / 缺 BOM / 已存在 / 来源无效”由后端判定。已有采购单查询必须覆盖任意状态，并区分 `order` 与 `stockin` 来源。

## 6. 表单数据保存/恢复边界

| 数据 | 保存与恢复口径 |
|---|---|
| 来源 Order/StockIn、SKU 数量、抵扣、备注 | 已进入本流程前即持久化；全流程不重建、不重复提交。续提时后端重新读取当前值 |
| 原采购页临时状态 | 在同一标签页 sessionStorage 保存并恢复；失效选择 ID 丢弃，页码越界时回退到有效页 |
| 待补 SKU 队列 | 初始快照仅用于展示和导航；每次返回都按后端最新 `has_bom` 重算，已由他用户配置的 SKU 自动跳过 |
| BOM 已保存内容 | 由现有 BOM API 持久化；返回/刷新后重新加载 |
| BOM 未保存草稿 | 保存失败时保留在当前编辑器；明确放弃或刷新后不保证恢复，不属于“原下单数据” |
| 汇总弹窗未保存编辑 | 与缺 BOM 待生成行不属于同一阶段，P0 不序列化、不自动恢复 |
| 尝试 ID / 幂等键 | 同一尝试跨多份 BOM、刷新、失败重试保持不变；终态清除，下一次用户主动发起才生成新键 |

## 7. 防重复提交/单据验收标准

1. **单 SKU Order 续提**：点击后打开正确产品；保存后自动返回，原页签/页码恢复；不调用 Order 创建接口；最终只新增 1 张对应该来源的采购单。
2. **单 SKU StockIn 续提**：同上，且与相同数字 ID 的 Order 不串单；不调用 StockIn 创建接口。
3. **多 SKU**：两份 BOM 未齐时 0 次生成、0 张新采购单；全部补齐后仅续提一次，生成内容沿用现有全 SKU/全作用域算法。
4. **取消**：未保存取消或确认放弃后 0 次 BOM 保存、0 次续提、0 张新采购单，原来源单仍待生成。
5. **保存失败**：不离开 BOM 页、不丢失当前输入、不续提；后续只成功保存一次时只返回/续提一次。
6. **校验仍失败**：返回后仍调用一次权威校验，缺 BOM 时后端 0 写入返回 `MISSING_BOM`；前端按响应展示剩余 SKU，不会出现采购页与产品页无限自动跳转，也不会把“保存成功”误报为“下单成功”。
7. **重复点击**：入口、BOM 保存、续提各自并发点击只产生一个有效动作；自动生成与续提同时发生时，同一来源本次流程至多新增 1 张采购单。
8. **响应未知重试**：同一尝试同键重放返回首次结果或现有关联单，0 新增；不得因刷新生成新幂等键。
9. **已完成/他人已生成**：旧续提请求命中任意状态关联采购单时幂等返回，0 新增；不得仅因 pending-only 索引失效而再造一单。
10. **刷新/重复回跳**：在配置页、返回校验中、续提中、续提失败和完成后的刷新均不产生重复尝试/重复单；完成后的旧 URL 不自动发写请求。
11. **来源并发变化**：来源被删除、改为不可生成状态或由他人生成时，后端给出确定结果，前端不盲目重试、不新建来源单。
12. **权限**：无 `product_manage` 的前端入口不可用，直接调用 BOM 保存仍被后端拒绝；不得因续提绕过既有权限。
13. **回归**：现有自动生成、采购汇总/完成、BOM 读取失败禁止保存、未保存确认、移动端只读行为在 P0 范围内不退化。

## 8. UI Design Draft

- **采购页待生成行**：操作列由纯文案改为“缺 BOM”说明 + 主按钮“配置 BOM 并下单”；续提中显示行级 loading 并禁用重复操作。
- **产品页**：有效 resume 上下文时自动打开 BOM 模态框，标题保持现有产品名，附加轻量提示“保存后返回采购中心继续下单”；无上下文时完全沿用现状。
- **返回采购页**：先显示“正在校验并继续下单”；仍缺 BOM 时显示剩余 SKU 与“继续配置”；失败时就地显示错误和“重试续提”；成功显示采购单号，幂等命中使用不同文案。
- **状态恢复**：返回后保持原“待生产订单”页签、页码和有效选择，不因刷新把用户送到记录查询或其他页面。

## 9. Open Questions（均有默认决策，不阻塞）

1. **是否本期必须覆盖移动端？** 默认否。移动端当前没有人工下单按钮，也没有 BOM 编辑器，P0 先做 PC，移动端列 P1。
2. **多 SKU 保存一份后是否自动跳到下一份？** 默认不自动连跳；每次都先回采购页并显示继续配置，只有全部齐备后才自动续提，符合“保存成功自动返回”且避免回跳循环。
3. **是否新增一套续提生成接口？** 默认不新增算法；强化现有 `one-click-generate` 为权威幂等续提入口，复用现有生成服务。若架构选择增加薄状态查询端点，状态语义与验收标准不变。
4. **上下文保存多久？** 默认限当前标签页，直到完成、明确取消或来源失效；刷新可恢复，不做跨标签页持久续提。
5. **采购-only 用户是否也可配置 BOM？** 默认不扩权，仍要求 `product_manage`；无权限时提供明确引导而非静默失败。

## 10. 验证说明

本任务仅新增本 PRD，未修改业务代码，按 `AGENTS.md`“仅文档改动免测”规则未运行测试；上述现状结论均来自只读代码与测试文件调查，未连接生产数据库、未重启服务、未提交代码。
