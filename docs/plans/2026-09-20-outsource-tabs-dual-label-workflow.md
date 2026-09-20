---
intent: 将外发模块顶部三个 TAB 调整为「收货/发货（同一 TAB 双名）| 外发工序 | 工序预设」，其中第一个 TAB 对贝乐用户显示「收货」、其余用户显示「发货」。
success_criteria: 从左到右为 收货/发货、外发工序、工序预设；贝乐用户看到「收货」、其余用户看到「发货」；三个 TAB 点击跳转与激活态正确；既有回归测试通过。
risk_level: low
auto_approve: true
worktree: false
---

## Steps

- [ ] **Step 1: 记录改动前基线**
action: 运行 `npx vitest run src/test/OutsourceShipmentView.test.ts`，确认当前 4 个用例通过，作为回归基线。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipmentView.test.ts

- [ ] **Step 2: 新增身份判定与双名标签**
action: 编辑 `frontend-vite/src/views/hubei/HubeiRouteTabs.vue` 的 `<script setup>`：在 `canOutsource` 之后新增 `const isBeile = computed(() => authStore.user?.username === '贝乐')` 与 `const shipmentTabLabel = computed(() => (isBeile.value ? '收货' : '发货'))`。更新文件顶部注释块，把「外发工序 / 工序预设 两个页面」改为「收货·发货 / 外发工序 / 工序预设 三个页面」，并补充说明首个 TAB 按贝乐身份显示双名。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 3: 调整 TAB 顺序与标签文案**
action: 编辑 `frontend-vite/src/views/hubei/HubeiRouteTabs.vue` 模板：把 `value="shipments"` 的 `UiTabTrigger` 移到 `UiTabs` 内第一位，其图标保持 `truck-fast`，文案由 `发货单` 改为 `{{ shipmentTabLabel }}`；其后依次为 `value="orders"`（文案保持 `外发工序`、图标 `clipboard-list`）与 `value="presets"`（文案保持 `工序预设`、图标 `cogs`）。三个 `v-if="canOutsource"` 与 `:active` 绑定保持不变。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 4: 新增标签文案与顺序的回归测试**
action: 新建 `frontend-vite/src/test/HubeiRouteTabs.test.ts`。mock `@/stores/auth` 返回可控的 `user.username` 与 `hasAnyPermission`（返回 true）；mock `vue-router` 的 `useRoute`（返回 `{ path: '/outsource' }`）与 `useRouter`（返回 `{ push: vi.fn() }`）；stub `FontAwesomeIcon`。用例一：username='贝乐' 时，第一个 TAB 文本含「收货」且不含「发货单」；用例二：username='admin' 时，第一个 TAB 文本含「发货」且不含「收货」；用例三：两种身份下三个 TAB 的文本顺序均为 [收货|发货, 外发工序, 工序预设]。
loop: false
max_iterations: 1
verify: npx vitest run src/test/HubeiRouteTabs.test.ts

- [ ] **Step 5: 回归修复直到全部测试通过**
action: 运行两个测试文件；若失败，逐条对照实际渲染修正断言或实现（不得通过放宽断言掩盖真实缺陷）。重点核对：`authStore.user` 可能为 null 时不报错、stub 后 `UiTabs`/`UiTabTrigger` 的文本提取方式、`computed` 在 setup 中的响应性。
loop: until npx vitest run src/test/HubeiRouteTabs.test.ts src/test/OutsourceShipmentView.test.ts exits 0
max_iterations: 4
verify: npx vitest run src/test/HubeiRouteTabs.test.ts src/test/OutsourceShipmentView.test.ts

- [ ] **Step 6: 浏览器实测标签文案与顺序**
action: 以 admin 身份打开 `http://192.168.0.95:3000/outsource`，用 `browser_evaluate` 读取 `.hu-tabs-bar` 内全部 TAB 的文本，确认顺序为「发货 / 外发工序 / 工序预设」；逐个点击三个 TAB，每次读取 `location.pathname` 与带激活样式的 TAB 文本，确认跳转路径分别为 `/outsource/shipments`、`/outsource`、`/outsource/presets` 且激活态跟随。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource
  check: 三个 TAB 顺序为 发货/外发工序/工序预设，点击后路由与激活态均正确

- [ ] **Step 7: 确认页面功能未受影响**
action: 在 `/outsource/shipments` 页面确认「批量发货」按钮对 admin 仍可见；点击打开弹窗并确认渲染出产品项，随后按 Escape 关闭。确认页面无 Vite 错误遮罩（`document.querySelector('vite-error-overlay')` 为 null）。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 批量发货按钮可见且弹窗可正常打开，无构建错误遮罩
