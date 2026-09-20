---
intent: 将 958 行的批量发货弹窗拆为「纯函数模型 + 双栏子组件」，主文件及全部新文件 ≤400 行，行为零变化
success_criteria: check_vue_component_length(400) 对主文件与 3 个新文件全 PASS；quality_gate PASS；四层测试全绿；浏览器实测行为一致
risk_level: medium
auto_approve: true
worktree: false
---

## Steps

- [x] **Step 1: 创建纯函数领域模型 shipCartModel.ts**
action: 新建 `frontend-vite/src/views/outsource/components/shipCartModel.ts`。从 `OutsourceShipDialog.vue` 的 `<script>` 段迁出并导出：类型 `PickGroup` / `OrderOption` / `MergedInput` / `CartProcessRow` / `CartProduct`（含各自 JSDoc 注释，原样保留）；类型 `ShipResult` 留在主文件不迁。导出纯函数：`mergeKey(productName, processType)`（模板串 `产品名||工序名`）、`productNameOf(row)`（返回 `row.product_name || '未命名产品'`，新抽取的公共助手）、`productRows(rows, productName)`（按产品名过滤工序行，用 productNameOf 比较）、`buildOrderOptions(list)`（按 order_id 去重提取订单基础信息）、`buildPickGroups(list)`（两级聚合：订单+产品去重 → 产品名合并跨订单，输出按 productName localeCompare 排序）、`buildCartGroups(rows, cartProducts, mergedInputs)`（按产品名×工序名合并行；对 mergedInputs 中不存在的键写入默认 `{ qty: 剩余合计, on: true }`——在函数 JSDoc 中注明该写入是跨重算保持输入稳定的既有行为）、`splitQty(r)`（按订单顺序依次填满 entries 剩余量，数量为 0 的订单不返回）、`rowQty(r)`（未勾选或非法记 0）、`isRowInvalid(r)`（未勾选恒 false；否则空/非有限/非整数/<1/超过 remaining 为非法）。所有函数不 import Vue 响应式 API，仅依赖入参；`ShippableProcessItem` 类型从 `@/api/outsource` 导入。
loop: false
max_iterations: 1
verify: npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | Select-String "shipCartModel" ; 应无输出（新文件零类型错误）

- [x] **Step 2: 创建模型单测**
action: 新建 `frontend-vite/src/test/shipCartModel.test.ts`。构造最小 `ShippableProcessItem` 夹具助手，覆盖：`buildPickGroups` 同一产品跨订单合并为一组且 orderCount 正确、不同产品分组、按名称排序；`buildOrderOptions` 按 order_id 去重；`buildCartGroups` 同产品同工序跨订单合并为一行且 targetQty/remaining 为合计、mergedInputs 缺省键被写入默认值且再次调用不覆盖用户已填值、cartProducts 顺序决定输出顺序；`splitQty` 依次填满各订单剩余（第一单 remaining 小于合计时的拆分）、数量为 0/负数/NaN 返回空数组；`isRowInvalid` 未勾选恒 false、小数/0/负数/超上限为 true、恰好等于上限为 false；`rowQty` 未勾选与非法时返回 0。
loop: false
max_iterations: 1
verify: npx vitest run src/test/shipCartModel.test.ts

- [x] **Step 3: 创建左栏子组件 OutsourceShipPickPanel.vue**
action: 新建 `frontend-vite/src/views/outsource/components/OutsourceShipPickPanel.vue`。模板为 `OutsourceShipDialog.vue` 左栏 `<aside class="osw-left">…</aside>` 整块（搜索框 + 计数行 + 全选按钮 + 列表表头 + 产品卡片列表）原样迁入，类名逐一保留。脚本：`defineProps<{ groups: PickGroup[]; selectedNames: string[] }>()`；`const keyword = defineModel<string>('keyword', { default: '' })`；`defineEmits<{ (e: 'toggle', g: PickGroup): void; (e: 'select-all'): void }>()`；内部 `filtered` computed 按 `keyword.trim()` 过滤 props.groups（含 `product_name || '未命名产品'` 的空列表态文案「没有匹配的产品」）；`isPickOn(g)` 改用 `props.selectedNames.includes(g.productName)`；卡片点击与复选框点击均 `emit('toggle', g)`；全选按钮 `emit('select-all')`。样式：迁入父文件左栏样式块（`.osw-left`、`.osw-l-toolbar`、`.osw-search`、`.osw-l-meta`、`.osw-l-list`、`.osw-l-head`、`.osw-card`、`.osw-prod-name`、`.osw-prod-orders`、`.osw-l-empty`）以及两栏共用的 `.osw-link`（在子组件内复制一份，scoped 样式不跨组件）。
loop: false
max_iterations: 1
verify: npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | Select-String "OutsourceShipPickPanel" ; 应无输出

- [x] **Step 4: 创建左栏子组件测试**
action: 新建 `frontend-vite/src/test/OutsourceShipPickPanel.test.ts`。mount 时以真实组件 + 最小 groups 夹具覆盖：卡片计数与名称渲染、跨订单角标（orderCount>1 显示「N单」）、点击卡片触发 toggle 且 payload 为对应 PickGroup、勾选框点击（.stop 修饰）同样触发 toggle、selectedNames 含该产品时卡片带 is-on 类且复选框选中、输入关键字后列表即时过滤、无匹配时显示「没有匹配的产品」、点击全选触发 select-all。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipPickPanel.test.ts

- [x] **Step 5: 创建右栏子组件 OutsourceShipCartPanel.vue**
action: 新建 `frontend-vite/src/views/outsource/components/OutsourceShipCartPanel.vue`。模板为父文件右栏 `<section class="osw-right">…</section>` 整块原样迁入（清单头 + 空态 + 产品卡 + 工序格）。脚本：`defineProps<{ groups: CartProduct[] }>()`；`defineEmits<{ (e: 'remove', productName: string): void }>()`；从 `./shipCartModel` 导入 `rowQty` / `isRowInvalid`；迁入内部函数 `liveRemaining(r)`、`onQtyInput(r, e)`（含写回 DOM 的注释）、`productCheckedSum(p)`、`productOrderCount(p)`；卡头 ✕ 按钮 `emit('remove', p.productName)`。样式：迁入右栏样式块（`.osw-right`、`.osw-r-head`、`.osw-chip`、`.osw-r-list`、`.osw-cart-empty*`、`.osw-cart-card`、`.osw-cart-head`、`.osw-cart-title`、`.osw-cart-orders`、`.osw-cart-sum`、`.osw-rm`、`.osw-proc-grid`、`.osw-cell*`、`.osw-proc`、`.osw-total`、`.osw-remain`、`.osw-qty`）与共用的 `.osw-cbx`、`.osw-link`（复制一份）；并在组件内新增 `@media (max-width: 768px)` 块承接原父文件响应式中属于右栏内部的三条规则（`.osw-cart-head { flex-wrap: wrap; row-gap: 2px; }`、`.osw-cart-title { flex: 1 1 100%; }`、`.osw-qty { padding: 8px; }`）——父作用域样式无法命中子组件内部元素，此迁移是行为保持的关键。
loop: false
max_iterations: 1
verify: npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | Select-String "OutsourceShipCartPanel" ; 应无输出

- [x] **Step 6: 创建右栏子组件测试**
action: 新建 `frontend-vite/src/test/OutsourceShipCartPanel.test.ts`。以构造好的 `CartProduct[]` 夹具 mount 覆盖：空 groups 显示空态文案「发货清单还是空的」、产品卡标题与合并单数角标、卡头合计（productCheckedSum 口径：未勾选/非法行记 0）、工序格渲染工序名与总量/剩余、数量输入输入小数被向下取整、输入 0 恢复为剩余上限、输入超上限被钳制、超限输入框带 is-invalid 类、勾选框取消后整格带 is-off 类、✕ 按钮触发 remove 且 payload 为产品名。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipCartPanel.test.ts

- [x] **Step 7: 主文件瘦身**
action: 编辑 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue`。模板：左栏 `<aside>` 整块替换为 `<OutsourceShipPickPanel v-model:keyword="keyword" :groups="filteredPickGroups" :selected-names="cartProducts" @toggle="togglePick" @select-all="selectAllFiltered" />`；右栏 `<section>` 整块替换为 `<OutsourceShipCartPanel :groups="cartGroups" @remove="removeProductFromCart" @clear="clearCart" />`；手机 Tab、提交遮罩、底栏三态、结果态原样保留。脚本：删除已迁出的类型与函数定义（含 `keyword` 相关仅过滤逻辑不动——`filteredPickGroups` computed 保留在父组件供 Tab 计数与全选用），改为从 `./shipCartModel` 导入类型与 `buildOrderOptions` / `buildPickGroups` / `buildCartGroups` / `mergeKey` / `productRows` / `splitQty` / `rowQty` / `isRowInvalid`；`load()` 内两段聚合改为调用模型函数；`cartGroups` computed 改为 `buildCartGroups(rows.value, cartProducts.value, mergedInputs.value)`（传入同一响应式 Map 引用，输入状态跨重算行为不变）；删除 `liveRemaining` / `onQtyInput` / `productCheckedSum` / `productOrderCount`（仅子组件使用）；`addProduct` / `removeProduct` / `togglePick` / `selectAllFiltered` / `clearCart` / `removeProductFromCart` / `submit` / `backToEdit` / `finish` / `onClose` / `onOpenUpdate` 保留。样式：删除左栏与右栏两个样式块及响应式媒体查询中已迁往 CartPanel 的三条规则，保留 `.osw-body` / `.osw-title-sub` / `.osw-tabs` / `.osw-panes` / 底栏 / 遮罩 / 结果态 / `.osw-empty` 及响应式中 tabs、`.osw-panes[data-tab]` 显隐切换（子组件根元素带父作用域属性，`.osw-panes[data-tab='pick'] .osw-right` 仍命中）与底栏规则。
结果: 首轮瘦身至 450 行仍超标，按预案追加两项抽取：结果态视图 `OutsourceShipResultView.vue`（61 行）+ 汇总口径 `useShipTotals.ts`（38 行），最终主文件 382 行。
loop: false
max_iterations: 1
verify: npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | Select-String "OutsourceShipDialog" ; 应无输出

- [x] **Step 8: 四层测试全绿**
action: 运行四个测试文件；若存量 `OutsourceShipDialog.test.ts` 个别用例因子组件引入而查询不到节点，允许调整该文件的 mount 装配（如补充子组件真实渲染、调整 stubs），但任何断言不得放松或删除。新增测试失败按实现缺陷修复。
loop: until 四个文件全部通过
max_iterations: 5
verify: npx vitest run src/test/OutsourceShipDialog.test.ts src/test/shipCartModel.test.ts src/test/OutsourceShipPickPanel.test.ts src/test/OutsourceShipCartPanel.test.ts

- [x] **Step 9: 行数门禁与质量门禁**
action: 运行组件行数检查与质量门禁；若主文件仍超 400 行，继续把结果态视图（模板+样式，约 55 行）抽为 `OutsourceShipResultView.vue` 并复跑 Step 8，直到达标。
loop: until 两项检查通过
max_iterations: 3
verify: python scripts/check_vue_component_length.py --max-length 400 ; python scripts/quality_gate.py

- [x] **Step 10: 浏览器实测行为一致**
action: 打开 `http://192.168.0.95:3000/outsource/shipments`，点击「批量发货」打开弹窗，逐项核对：左栏产品列表与搜索过滤、全选、点选后产品出现在右栏、工序格总量/剩/数量框与拆分前一致（王者荣耀 电绣/转印 总量 1,009,999）、数量输入输入 0 恢复上限、小数向下取整、底栏已选单数/工序数/合计实时变化、确认态文案与按钮、Escape 关闭。整个过程不点击「确认发货」。
结果: 全链路通过（数据已演进：王者荣耀 6 行工序已被用户真实发满并收货，改用变形金刚验证——搜索过滤、25 单合并卡、工序格总量 3,281,076、改 100 后剩余 3,280,976、底栏 3,281,176 件、小数 100.9→100、确认态文案正确）；发现并修复两处环境问题（FontAwesome default 导入、useBeileOrders 丢失导出致路由崩溃，见执行记录）；「王者荣耀」场景的列表可见性验证待用户重启后端后复核。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 弹窗双栏交互与拆分前一致，无 vite-error-overlay
