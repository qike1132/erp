---
intent: 在发货清单的每个工序格中展示该工序的订单总量与剩余未发数量，且剩余数量随用户填写的本次发货数量实时递减。
success_criteria: 每格显示跨订单总量与实时剩余（剩余合计 − 本次填写）；取消勾选时剩余恢复为剩余合计；既有 16 个回归测试全部通过。
risk_level: low
auto_approve: true
worktree: false
---

## Steps

- [ ] **Step 1: 记录改动前基线**
action: 运行 `npx vitest run src/test/OutsourceShipDialog.test.ts`，确认当前 16 个用例全部通过，作为回归基线。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipDialog.test.ts

- [ ] **Step 2: 在数据结构中补充跨订单总量**
action: 编辑 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue`：在 `CartProcessRow` 接口中新增字段 `targetQty: number`，注释为「跨订单订单总量合计」。在 `cartGroups` 计算属性构造 `processes.push({...})` 时新增 `targetQty: entries.reduce((s, e) => s + e.target_qty, 0)`，与既有 `remaining: entries.reduce((s, e) => s + e.remaining, 0)` 并列。不要改动 `mergedInputs`、`splitQty`、`isRowInvalid`、`submit`。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 3: 新增实时剩余计算函数**
action: 在 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue` 的 `productCheckedSum` 函数之后新增纯函数 `function liveRemaining(r: CartProcessRow): number`：未勾选时返回 `r.remaining`；已勾选时返回 `Math.max(0, r.remaining - (Number(r.input.qty) || 0))`。该函数用于模板展示，不参与校验与提交。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 4: 工序格新增总量与实时剩余展示**
action: 编辑 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue` 模板中 `.osw-cell` 内部：把现有单行 `<span class="osw-remain">剩 {{ r.remaining.toLocaleString() }}</span>` 替换为统计区 `<div class="osw-cell-stats">`，内含两行——`<span class="osw-total" :title="`订单总量 ${r.targetQty.toLocaleString()}`">总量 {{ r.targetQty.toLocaleString() }}</span>` 与 `<span class="osw-remain" :title="`剩余合计 ${r.remaining.toLocaleString()} − 本次发货，发完后剩余`">剩 {{ liveRemaining(r).toLocaleString() }}</span>`。位置保持在 `.osw-cell-top` 与数量框之间。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 5: 新增统计区样式**
action: 编辑 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue` 的 `<style scoped>`：在 `.osw-remain` 规则之前新增 `.osw-cell-stats { display: flex; flex-direction: column; gap: 1px; }`；新增 `.osw-total { font-size: 11px; color: var(--color-text-secondary, #475569); font-family: ui-monospace, Menlo, Consolas, monospace; }`；把既有 `.osw-remain` 规则保留不变（仅字号与颜色）。不要修改 `.osw-cell` 的 `flex: 0 0 152px` 与 `.osw-proc-grid` 的横向滚动设置。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 6: 更新既有断言并新增统计断言**
action: 编辑 `frontend-vite/src/test/OutsourceShipDialog.test.ts`：在「同一 SKU 多工序在同一行内横向展示」用例中，把 `expect(cells[0]!.find('.osw-remain').text()).toContain('9,626')` 改为断言 `.osw-total` 含 `9,626` 且 `.osw-remain` 含 `9,626`（初始未修改数量时两者相等）。在「每道工序独立填数量」用例中新增断言：把第 1 格数量改为 50 后，该格 `.osw-remain` 含 `50`（100 − 50），未修改的第 2 格 `.osw-remain` 仍含 `100`。在「每道工序可单独取消勾选」用例中新增断言：取消第 1 格勾选后其 `.osw-remain` 恢复含 `100`。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipDialog.test.ts

- [ ] **Step 7: 回归修复直到测试全绿**
action: 运行测试；若有失败，逐条对照实际渲染结果修正断言或实现（不得通过放宽断言掩盖真实缺陷）。重点核对：总量与剩余在初始态相等、填数量后剩余递减、取消勾选后剩余恢复、跨订单合并行的总量为各订单之和。
loop: until npx vitest run src/test/OutsourceShipDialog.test.ts exits 0
max_iterations: 4
verify: npx vitest run src/test/OutsourceShipDialog.test.ts

- [ ] **Step 8: 浏览器实测数据展示与实时更新**
action: 打开 `http://192.168.0.95:3000/outsource/shipments`，点「批量发货」，点左栏「全选」。用 `browser_evaluate` 读取第 4 张卡（Nommi糯米儿）6 个 `.osw-total` 与 6 个 `.osw-remain` 文本，确认总量与剩余初始相等且等于各工序跨订单合计；随后把该卡第 1 格数量改为 1000，再次读取，确认该格 `.osw-remain` = 原值 − 1000、其余格不变；最后取消该格勾选，确认 `.osw-remain` 恢复为原值。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 每格显示总量与剩余，剩余随输入实时递减、取消勾选后恢复

- [ ] **Step 9: 确认布局与提交口径未回归**
action: 在同一页面用 `browser_evaluate` 确认 `.osw-proc-grid` 的 `scrollWidth >= clientWidth` 且 `.osw-cell` 的 `flex-wrap` 未生效（各格 top 值一致为单行）；点击「生成发货单」进入确认态，确认提示的订单张数与件数与前一步一致；点「返回调整」退出，不实际提交。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 工序格保持单行横向滚动；确认态张数与件数正确且未产生真实发货单
