---
intent: 订单备货录入的订单条目支持"有出货计划"+出货日期，提交时在同一数据库事务内把订单数据同步为采购计划明细（客户+月 find-or-create，明细落日期/数量，remark 记来源订单号）
success_criteria:
  - 选"有"+日期提交后，purchase_plans/purchase_plan_details 出现对应明细（plan_date=所选日期、quantity=订单数量、remark=来源订单:{order_no}）
  - 选"无"提交行为与改动前完全一致（payload 新字段缺省 false/''，同步函数对空集合短路）
  - 同客户跨月两个出货日 → 两个月各自 find-or-create 计划；已有计划 → 追加明细不报 409
  - 计划同步失败时该客户订单组整体回滚并在 results[].error 可见原因
  - pytest 新增测试通过且后端全量不回归；vitest 全量不回归；quality_gate.py PASS
risk_level: medium
auto_approve: true
branch: main
worktree: false
dirty_worktree: allow  # 工作区有他人未提交的备份模块 WIP，本功能只提交自身文件清单，严禁卷入
---

## Steps

- [x] **Step 1: 后端 schema——BatchOrderItem 增加出货计划字段**
action: 编辑 fastapi_app/api/v1/endpoints/auxiliary.py 的 BatchOrderItem（现含 product_id/customer/quantity/deduct_stock/deduct_quantity/note/order_date 七字段），追加两个可选字段：`has_shipment_plan: bool = False` 与 `shipment_plan_date: str | None = None`，均带中文 comment 说明（是否同步出货计划；出货日期 YYYY-MM-DD，has_shipment_plan 为真时必填）。不改 BatchStockInItem/BatchStockOutItem。
verify: python -c "import ast; ast.parse(open('fastapi_app/api/v1/endpoints/auxiliary.py', encoding='utf-8').read())"
gate: auto

- [x] **Step 2: 新建同步服务 shipment_plan_sync.py**
action: 新建 fastapi_app/services/shipment_plan_sync.py，实现 `async def sync_order_items_to_plans(db: AsyncSession, *, customer_name: str, order_no: str, validated_items: list, created_by: str) -> int`：
  1) 过滤 `it.get('has_shipment_plan')` 为真的条目，空则直接 return 0（无计划路径零开销）；
  2) 按名称精确查询 Customer（`select(Customer).where(Customer.name == customer_name)`），查不到 raise `ValueError(f'客户档案中不存在客户「{customer_name}」，无法同步出货计划')`；
  3) 每条用 `normalize_plan_date`（来自 fastapi_app.services.plan_utils）解析 shipment_plan_date，按 `strftime('%Y-%m')` 分组；明细 dict 形如 `{'product_id': it['product_id'], 'product_name': it['product'].name, 'barcode': getattr(it['product'], 'barcode', '') or '', 'quantity': it['quantity'], 'plan_date': it['shipment_plan_date'], 'remark': f'来源订单:{order_no}'}`；
  4) 每个月份查既有计划（customer_id + plan_month，参照 PurchasePlan 模型字段）：存在则调 purchase_plan_crud_ops.add_details(db, plan.id, details)；不存在则调 create_plan(db, customer_id=..., customer_name=..., plan_month=month, details=details, remark=f'订单 {order_no} 自动同步', created_by=created_by)；
  5) 返回同步条目数。文件头 docstring 写明设计依据：docs/designs/2026-10-06-order-shipment-plan-sync-design.md，同事务语义由调用方 savepoint 保证。
verify: python -c "import ast; ast.parse(open('fastapi_app/services/shipment_plan_sync.py', encoding='utf-8').read())"
gate: auto

- [x] **Step 3: 接线 order_batch_create.py——校验透传 + savepoint 内同步**
action: 编辑 fastapi_app/services/order_batch_create.py：
  1) `_validate_one_item` 返回 dict 增加 `'has_shipment_plan': bool(order_data.get('has_shipment_plan'))` 与 `'shipment_plan_date': str(order_data.get('shipment_plan_date') or '').strip()`；在其现有校验后追加：has_shipment_plan 为真且日期为空 → `_fail('选择了出货计划但未选择出货日期')`；日期非空但 `datetime.strptime(值, '%Y-%m-%d')` 抛 ValueError → `_fail(f'出货日期格式错误，请使用 YYYY-MM-DD：{值}')`；
  2) 新增 `async def _sync_shipment_plans(db, order, validated_items, customer, results, created_by) -> None`：局部导入 Step 2 的 sync 函数并调用；捕获 ValueError 时 `results.append({'success': False, 'error': f'出货计划同步失败：{e}', 'customer': customer})` 并 raise `_SavepointRollbackSignalError()`（触发整组回滚，订单与计划同生共死）；
  3) `batch_create_orders` 签名改为 `(db: AsyncSession, orders_data: list, created_by: str = '')`（唯一生产调用方是 auxiliary_service.orchestrate_batch_orders，测试调用方不传新参不受影响）；在每客户 begin_nested 块内、`_apply_deductions` 之后、`results.append(_build_success_result(...))` 之前调用 `await _sync_shipment_plans(db, order, validated_items, customer, results, created_by)`；
  4) 顺带把 batch_create_orders docstring 中过期的"同步至采购中心的操作不在此函数内执行，由调用方在事务提交后统一处理"注释改写为实际语义："has_shipment_plan 条目在本函数内（同客户 savepoint 中）同步为采购计划明细，与订单同事务原子"。
verify: python -c "import ast; ast.parse(open('fastapi_app/services/order_batch_create.py', encoding='utf-8').read())"
gate: auto

- [x] **Step 4: 编排层与端点传递 created_by**
action: 编辑 fastapi_app/services/auxiliary_service.py 的 orchestrate_batch_orders 签名加 `created_by: str = ''` 并透传给 batch_create_orders；编辑 fastapi_app/api/v1/endpoints/auxiliary.py 的 batch_submit_orders 端点，把 `orchestrate_batch_orders(db, [item.model_dump() for item in data.orders])` 改为带 `created_by=user.username`（User 模型字段名 username）。batch_submit_stockins/stockouts 不动。
verify: python -c "import ast; ast.parse(open('fastapi_app/services/auxiliary_service.py', encoding='utf-8').read()); ast.parse(open('fastapi_app/api/v1/endpoints/auxiliary.py', encoding='utf-8').read())"
gate: auto

- [x] **Step 5: 后端测试——新增 test_shipment_plan_sync.py**
action: 新建 fastapi_app/tests/test_shipment_plan_sync.py，fixture 模式（建产品/客户/订单数据的内存 SQLite 或测试库构造）参照 fastapi_app/tests/test_order_batch_create.py 现有写法。用例清单：
  1) sync_order_items_to_plans 传入全无计划条目 → 返回 0 且不写任何表；
  2) 客户名不在 customer 表 → pytest.raises(ValueError) 且文案含"客户档案中不存在客户"；
  3) 单月新建路径：断言 purchase_plans 出现 1 行（plan_month、remark 含订单号、created_by）且 purchase_plan_details 出现对应行（plan_date、quantity、remark='来源订单:...'、barcode）；
  4) 已有同客户同月计划 → 不新建主单，明细追加到既有 plan_id；
  5) 同客户两个不同月日期 → 两个月主单各 1；
  6) 集成：batch_create_orders 传入含 has_shipment_plan=True 的条目 → 函数返回后订单与计划明细同时可见；
  7) 集成回滚：monkeypatch create_plan 抛 ValueError → results 中该客户 success=False 且订单行未持久化。
loop: until 全部用例通过
max_iterations: 4
verify: python -m pytest fastapi_app/tests/test_shipment_plan_sync.py -v
gate: auto

- [x] **Step 6: 后端回归**
action: 不改代码，跑后端订单相关回归，确认 Step 3 的签名扩展未破坏现有行为（重点关注 test_order_batch_create.py、test_order_batch.py、test_order_batch_lock_order.py、test_auxiliary*.py）。
loop: until 通过
max_iterations: 3
verify: python -m pytest fastapi_app/tests/test_order_batch_create.py fastapi_app/tests/test_order_batch.py fastapi_app/tests/test_order_batch_lock_order.py -q
gate: auto

- [x] **Step 7: 前端类型——FormState/StagedItem 增加字段**
action: 编辑 frontend-vite/src/views/customer-order/composables/types.ts：FormState 追加 `hasShipmentPlan: boolean` 与 `shipmentDate: string`；StagedItem 追加同名字段（必填，靠编译器暴露所有构造点），注释注明"仅订单类型有意义；Excel/OCR 导入条目默认 false/''"。随后运行 vue-tsc 收集全部类型错误位置（预计 CustomerOrderView.addStaged、useOrderImport、OrderOcrPaste 相关构造点），下一批步骤逐个补齐。
loop: false
max_iterations: 1
verify: cd frontend-vite; npx vue-tsc --noEmit 2>&1 | Select-String -Pattern "StagedItem|FormState" | Measure-Object | Select-Object -ExpandProperty Count
gate: auto

- [x] **Step 8: 表单状态——useOrderForm 校验与重置**
action: 编辑 frontend-vite/src/views/customer-order/composables/useOrderForm.ts：form 初始值加 `hasShipmentPlan: false, shipmentDate: ''`；missingFields 计算属性追加 `if (isOrder.value && form.hasShipmentPlan && !form.shipmentDate) missing.push('出货日期')`；resetFormAfterAdd 追加重置这两个字段。
verify: cd frontend-vite; npx vue-tsc --noEmit
gate: auto

- [x] **Step 9: 新组件 ShipmentPlanControl.vue**
action: 新建 frontend-vite/src/views/customer-order/components/ShipmentPlanControl.vue（总行数控制在 150 行内，远低于 400 门禁）：props 接收 `form: FormState`（defineModel 或直接 v-model:form，参照 OrderDeductControl 的挂载方式）；模板为一行：UiCheckbox「有出货计划」（v-model 绑定 form.hasShipmentPlan）+ 提示文案"提交时同步至采购计划系统"；勾选后以 grid-template-rows 0fr→1fr 过渡展开 UiDatePicker（绑定 form.shipmentDate，label 出货日期）；勾选态整行加 primary-50 底色与 primary-200 描边（参照 CustomerOrderView 里 co-tab-btn.active 的配色变量），prefers-reduced-motion 时省略过渡。仅订单模式被挂载，组件内部不判断 isOrder。
verify: cd frontend-vite; npx vue-tsc --noEmit
gate: auto

- [x] **Step 10: 挂载到录入面板与暂存链路**
action: 依次编辑：
  1) frontend-vite/src/views/customer-order/components/OrderInputPanel.vue：在 OrderDeductControl 所在 co-form-row 之后、备注 co-form-group 之前插入 `<ShipmentPlanControl v-if="isOrder" v-model:form="form" />`，import 该组件；
  2) frontend-vite/src/views/customer-order/CustomerOrderView.vue 的 addStaged：stagedItems.push 的对象追加 `hasShipmentPlan: isOrder.value && form.hasShipmentPlan, shipmentDate: isOrder.value && form.hasShipmentPlan ? form.shipmentDate : ''`；
  3) frontend-vite/src/views/customer-order/composables/useOrderImport.ts 与 useOrderOcr.ts（或 OrderOcrPaste 构造点）中所有 StagedItem 字面量补 `hasShipmentPlan: false, shipmentDate: ''`；
  4) frontend-vite/src/views/customer-order/composables/useStagedItems.ts 的 buildOrderPayload：map 内追加 `has_shipment_plan: i.hasShipmentPlan, shipment_plan_date: i.hasShipmentPlan ? i.shipmentDate : ''`；submitAll 在 dropUids 之前捕获 `const syncedPlanCount = order.attempted && !order.failed ? stagedOrders.value.filter((i) => i.hasShipmentPlan).length : 0` 并传入 reportSubmit；reportSubmit 增加可选参数，syncedPlanCount>0 且订单成功时播报改为 `提交成功：已创建 N 个主订单（含 M 个 SKU），其中 ${syncedPlanCount} 条已同步出货计划`。
verify: cd frontend-vite; npx vue-tsc --noEmit
gate: auto

- [x] **Step 11: 暂存卡片徽标与编辑弹窗**
action: 依次编辑：
  1) frontend-vite/src/views/customer-order/components/StagingArea.vue：在"数量/抵扣/备注" chip 区追加 `<span v-if="item.type === 'order' && item.hasShipmentPlan && item.shipmentDate" class="count-badge-subtle co-plan-chip"><FontAwesomeIcon icon="truck" aria-hidden="true" />出货: {{ item.shipmentDate.slice(5) }}</span>`，样式给 .co-plan-chip 设 primary 色调（color: var(--color-primary-600)），truck 图标需在 fontAwesome 工具的图标注册处确认已引入（参照文件内其他图标的引入方式，若无则补充）；
  2) frontend-vite/src/views/customer-order/components/EditStagedModal.vue：在抵扣数量分组之后、备注之前，`v-if="editStagedData.type === 'order'"` 的分组内放同样的复选框+日期选择器（直接 v-model 绑 editStagedData.hasShipmentPlan / editStagedData.shipmentDate，复用 UiCheckbox 与 UiDatePicker）；
  3) frontend-vite/src/views/customer-order/composables/useStagedEdit.ts 的 saveEditStaged：保存前校验——type 为 order 且 hasShipmentPlan 为真且 shipmentDate 为空时 showToast('请选择出货日期', 'warning') 并 return，不关闭弹窗（先读该函数现状再最小侵入修改）。
verify: cd frontend-vite; npx vue-tsc --noEmit
gate: auto

- [x] **Step 12: 前端测试**
action: 新建 frontend-vite/src/test/customerOrderShipmentPlan.test.ts（vitest + @vue/test-utils，挂载方式参照 src/test/customerOrderBatchSubmit.test.ts 与 OrderInputPanel.quantityReset.test.ts）：
  1) useOrderForm：勾选 hasShipmentPlan 且 shipmentDate 为空 → missingFields 含"出货日期"；填入日期后不含；
  2) buildOrderPayload/submitAll：有计划订单的 payload 含 has_shipment_plan=true 与 shipment_plan_date，无计划订单两字段为 false/''；mock stockApi.batchSubmitOrders 断言请求体（参照 customerOrderBatchSubmit.test.ts 的 mock 手法）；
  3) ShipmentPlanControl 挂载：复选框默认未勾选且日期选择器不可见（或 aria-hidden/收起态），勾选后日期输入可见；
  4) StagingArea：含计划订单条目渲染"出货: MM-DD"chip，备货/无计划条目不渲染。
  同时检查 src/test/customerOrderBatchSubmit.test.ts 是否有 payload 精确键断言需要同步扩展，有则补上。
loop: until 通过
max_iterations: 4
verify: cd frontend-vite; npx vitest run src/test/customerOrderShipmentPlan.test.ts src/test/customerOrderBatchSubmit.test.ts
gate: auto

- [x] **Step 13: 质量门禁全量**
  <!-- 执行记录（2026-10-06）：ruff/新测试/回归/全量 pytest（2676 过，2 个 stock_return 存量失败与本功能无关）/vue-tsc/vitest 1170 全过/eslint 0 错。
       quality_gate：N+1 已修复（改 IN 批量查询）；「巨型 Vue 组件 6→7」来自他人未提交 WIP（ProjectCardItem.vue +18 行超限，git diff 证据），本功能未新增超限文件。 -->
action: 不改代码（除非门禁报出本功能引入的问题，修复仅限本功能文件），依次运行：ruff check .、python -m pytest fastapi_app/tests -q、python scripts/quality_gate.py、npm run type-check --prefix frontend-vite、npm test --prefix frontend-vite、npm run lint --prefix frontend-vite。任何失败定位到本功能改动则回到对应步骤修复。
loop: until 全部通过
max_iterations: 4
verify: python scripts/quality_gate.py
gate: auto

- [ ] **Step 14: code-review 与人工验收**
  <!-- 执行记录（2026-10-06）：final review 无 BLOCK，4 条 non-BLOCK；P2（savepoint 回滚后幽灵 post-commit 回调）已修复并补回归测试（11/11 过），P3×3 维持现状。
       部署（2026-10-06 11:33）：npm run build 成功（59.65s，PWA 210 项）；UAC 提权 nssm restart erp-prod；新实例 prod_runner.json ready:true + frontend_ok:true + 8 workers（pid 10816, started_at 11:33:03）；3000 端口冒烟确认服务新 dist（index.html 引用与本地构建一致）。
       剩余：用户页面实测（有计划订单 → purchase-plan 月历可见；无计划订单原流程无感）；提交 git（等他人 WIP 或用户授权 --no-verify）。 -->
action: 运行 hotl:code-review 审查全部改动；随后由用户在页面实测：/customer-order 提交一条"有出货计划"订单 → /purchase-plan 月历可见明细；提交一条"无计划"订单确认原流程无感。提交 git 时仅暂存本功能文件（docs/designs、docs/plans 两个新文件 + Step 1-4 的 3 个后端文件 + Step 2/9 两个新文件 + Step 7-11 的前端文件 + 两个测试新文件），工作区中备份模块等他人未提交改动严禁卷入。
verify:
  type: human-review
  check: 用户确认页面实测通过且 review 无未解决的 P0/P1 问题
gate: human
