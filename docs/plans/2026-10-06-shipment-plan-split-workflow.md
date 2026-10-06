---
intent: 订单条目拆多批次出货计划（每批独立日期/数量/备注，总和必须排满订单量），同事务同步为多条采购计划明细
success_criteria:
  - 500 件订单拆 200+300 两批提交 → 采购计划两条明细（日期/数量/备注各自正确，remark 含批次备注）
  - 分批总和 ≠ 订单量：前端暂存前拦截，后端逐条兜底拒绝
  - 无计划路径与 v1 行为一致
  - 后端/前端测试全绿；quality_gate 无本功能新增违规
risk_level: medium
auto_approve: true
branch: main
worktree: false
dirty_worktree: allow  # 工作区有他人未提交 WIP，本功能只提交自身文件清单
---

## Steps

- [x] **Step 1: 后端 schema——shipment_plans 列表替换 v1 两字段**
action: 编辑 fastapi_app/api/v1/endpoints/auxiliary.py：新增 `class BatchShipmentPlanSplit(BaseModel): plan_date: str; quantity: int = Field(..., ge=1, le=9999999); note: str = ""`；BatchOrderItem 删除 has_shipment_plan/shipment_plan_date 两字段及其注释，改为 `shipment_plans: list[BatchShipmentPlanSplit] = Field(default_factory=list, description='分批出货计划，空=无计划')`。
verify: python -c "import ast; ast.parse(open('fastapi_app/api/v1/endpoints/auxiliary.py', encoding='utf-8').read())"
gate: auto

- [x] **Step 2: 后端校验——_validate_one_item 排满与逐项校验**
action: 编辑 fastapi_app/services/order_batch_create.py 的 _validate_one_item：读取 `order_data.get('shipment_plans') or []`；若非空：逐项 strptime 校验 plan_date（格式错 → _fail(f'出货日期格式错误，请使用 YYYY-MM-DD：{值}')）、quantity int 化（非法 → _fail('分批数量必须为正整数')）；计算总和 splits_total，`splits_total != quantity` → _fail(f'分批出货计划数量之和({splits_total})必须等于订单数量({quantity})')；返回 dict 以 `'shipment_plans': [{'plan_date': …, 'quantity': …, 'note': str(note or '')}, …]` 替换原 has_shipment_plan/shipment_plan_date 两键。
verify: python -c "import ast; ast.parse(open('fastapi_app/services/order_batch_create.py', encoding='utf-8').read())"
gate: auto

- [x] **Step 3: 同步服务——每批一条明细**
action: 编辑 fastapi_app/services/shipment_plan_sync.py：plan_items 过滤条件改为 `it.get('shipment_plans')`；明细生成改为两层循环——每个 item 的每个 split 一条明细，`remark` = f'来源订单:{order_no}' + (f'；{split["note"]}' if split['note'] else '')，quantity=split['quantity']，plan_date=split['plan_date']；月分组逻辑、IN 批量查既有计划、create_plan/add_details 调用均不变；返回值改为同步的明细批次数（原为条目数，现按批计）。
verify: python -c "import ast; ast.parse(open('fastapi_app/services/shipment_plan_sync.py', encoding='utf-8').read())"
gate: auto

- [x] **Step 4: 后端测试扩充**
action: 编辑 fastapi_app/tests/test_shipment_plan_sync.py：_plan_item/_no_plan_item 构造器与既有用例全部改用 shipment_plans 形状；新增用例：(1) 500 拆 200+300 两批 → create_plan/add_details 收到 2 条明细、数量/日期/备注正确且 remark 含批次备注；(2) 总和 ≠ 订单量（200+200=400≠500）→ _fail 文案含「必须等于订单数量」；(3) 总和相等但分两条不同月 → 两个月各建计划；(4) split 数量 0 或负 → Pydantic/校验层拒绝。
loop: until 通过
max_iterations: 4
verify: python -m pytest fastapi_app/tests/test_shipment_plan_sync.py -v
gate: auto

- [x] **Step 5: 后端回归**
action: 跑订单批量相关回归（test_order_batch_create/test_order_batch/test_order_batch_lock_order）。
loop: until 通过
max_iterations: 3
verify: python -m pytest fastapi_app/tests/test_order_batch_create.py fastapi_app/tests/test_order_batch.py fastapi_app/tests/test_order_batch_lock_order.py -q
gate: auto

- [x] **Step 6: 前端类型与表单状态**
action: 编辑 frontend-vite/src/views/customer-order/composables/types.ts：定义并导出 `export interface ShipmentPlanSplit { date: string; quantity: number; note: string }`；FormState/StagedItem 以 `shipmentPlans: ShipmentPlanSplit[]` 替换 hasShipmentPlan/shipmentDate；useOrderForm.ts：form 初始 `shipmentPlans: []`；新增 `planSplitsInvalid` computed（每行 date 且 quantity>0；总和必须等于 quantity——返回违规原因文案或 ''）；resetFormAfterAdd 清空；addStaged 前的拦截在 CustomerOrderView 中类比 quantityOutOfRange 接入；CustomerOrderView.addStaged push 携带 shipmentPlans（order 才带）。
verify: cd frontend-vite; npx vue-tsc --noEmit
gate: auto

- [x] **Step 7: ShipmentPlanControl v2 多行编辑器**
action: 重写 frontend-vite/src/views/customer-order/components/ShipmentPlanControl.vue（≤250 行）：勾选「有出货计划」时自动生成首行（date=''、quantity=form.quantity、note=''）；行模板 [UiDatePicker 日期][number 数量 min=1][input 备注][删除按钮]；「添加一批」按钮追加行（数量默认当前剩余=quantity-已分配，若剩余>0）；底部统计行：已分配 X / 订单量 Y，不相等时红色提示（超出或还差 Z）；planSplitsInvalid 时整行 danger 描边；取消勾选清空列表。注意保持 grid-rows 展开动画与勾选态锚点样式（沿用 v1 视觉）。
verify: cd frontend-vite; npx vue-tsc --noEmit
gate: auto

- [x] **Step 8: 提交链路与展示**
action: 依次编辑：useStagedItems.buildOrderPayload 改发 `shipment_plans: i.shipmentPlans.map(s => ({plan_date: s.date, quantity: s.quantity, note: s.note}))`（空数组=无计划，不再发 has_shipment_plan）；syncedPlanCount 条件改为 i.shipmentPlans.length > 0；StagingArea.vue chip 改为按批渲染 `出货: MM-DD×N`（最多 2 枚 + `+N批` 折叠徽标）；EditStagedModal.vue 的出货计划分组改为多行编辑器（与控件同构：日期/数量/备注/增删行 + 排满校验，保存时每行完整且总和等于 quantity 否则 showToast 拦截）；useStagedEdit.saveEditStaged 校验同步更新。
verify: cd frontend-vite; npx vue-tsc --noEmit
gate: auto

- [x] **Step 9: 前端测试**
action: 编辑 src/test/customerOrderShipmentPlan.test.ts 与 4 个既有测试文件的构造点（hasShipmentPlan/shipmentDate → shipmentPlans）；新增用例：(1) 两批 payload 形状（plan_date/quantity/note、无旧字段）；(2) 排满校验——不排满时 planSplitsInvalid 有文案、排满后为空；(3) 控件勾选自动生成首行、加行/删行、剩余统计；(4) 暂存卡片两批 chips 与超过 2 批折叠；(5) 编辑弹窗排满拦截。
loop: until 通过
max_iterations: 4
verify: cd frontend-vite; npx vitest run src/test/customerOrderShipmentPlan.test.ts src/test/customerOrderBatchSubmit.test.ts
gate: auto

- [x] **Step 10: 门禁全量与部署**
action: ruff（本功能 py 文件）→ quality_gate → npm run type-check → npm test → npm run lint（本模块）；全绿后 npm run build + UAC 提权 nssm restart erp-prod + 轮询 prod_runner.json ready/frontend_ok + 冒烟比对 bundle。
loop: until 全绿
max_iterations: 4
verify: python scripts/quality_gate.py
gate: auto

- [ ] **Step 11: code-review 与人工验收**
  <!-- 执行记录（2026-10-06 13:15）：final review 发现 1 BLOCK（编辑弹窗浅拷贝致取消污染暂存数据，可连坐整组提交失败）已修复并补回归测试（15/15），3 条 non-BLOCK 全部处置（整数口径前端补齐 / shipment_plans max_length=50 / TypeError 分支契约注释）。后端 14/14 + 批量回归 42/42；vue-tsc 零错误；vitest 全量含新用例 1174+；eslint 0 问题；quality_gate 仅剩他人 WIP 违规（非本功能）。
       部署（修复版）：build 21.58s → nssm restart erp-prod → ready:true + frontend_ok:true（12:14:57，8 workers）→ 3000 冒烟 bundle 一致（index-CBkE2JO0.js）。
       排查追加（13:15，staff-engineer/state-machine-correctness 流程）：按不变量 INV-1/2/3 系统枚举 10 处 shipmentPlans 生产变异点——INV-1（取消隔离）已由评审修复闭合；INV-2（保存落回隔离）原靠约定维持，已结构闭合（落回深拷贝 + 保存后置空 editStagedData，补回归测试，前端 16/16）；INV-3（构造点字面量）核查无共享。部署加固版：build 26.10s → ready:true（13:14:54）→ chunk CustomerOrderView-DWOPBCFF.js 深拷贝特征 4/4 处。
       剩余：用户页面实测 + 提交 git。
       删除联动追加（13:35，debugging-strategies 流程）：用户报告"删带计划订单 → 采购计划数据残留"。根因取证：两条删除路径（commands._purge_order_related_rows / approval_service._handle_delete_approval）均零引用采购计划表——联动从未实现（v2 设计稿 Scope Out 明示不联动）。修复：shipment_plan_sync 新增 purge_shipment_plan_details_for_order（remark 分号边界匹配防 PO-123 误伤 PO-1234；删明细→删被清空主单→按月 post-commit 失效缓存），双路径接线；直删路径删除备份快照纳入计划明细（误删恢复）。测试 +4（18/18 后端），后端全量 2684 过（2 个 stock_return 存量失败与本次无关）。部署 13:35:11 ready、bundle 一致。历史残留：本次修复前删除的订单留下的计划明细不追溯清理，如需一次性清理另议。 -->
action: 派发 review 代理审查本修订 diff（同 v1 标准）；用户页面实测：单条订单拆两批提交 → 采购计划两条明细；不排满被拦截；无计划订单无感。提交 git 仅限本功能文件清单。
verify:
  type: human-review
  check: 用户确认页面实测通过
gate: human
