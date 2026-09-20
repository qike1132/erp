---
intent: 发货清单中每个 SKU 只占一行，该 SKU 的全部工序在这一行内横向排列，每道工序保留独立的数量输入框与剩余量显示。
success_criteria: 同一 SKU 的工序渲染在同一横向容器内且 SKU 名只出现一次；宽屏下 6 道工序单行显示；窄屏自动换行无溢出；每格含勾选框/工序名/剩余量/独立数量框；回归测试全部通过。
risk_level: low
auto_approve: true
worktree: false
---

## Steps

- [ ] **Step 1: 记录改动前基线**
action: 运行 `npx vitest run src/test/OutsourceShipDialog.test.ts`，记录当前通过用例数与失败数，作为回归基线。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipDialog.test.ts

- [ ] **Step 2: 收窄左栏并新增工序格布局样式**
action: 编辑 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue` 的 `<style scoped>`：将 `.osw-left` 的 `width: 520px` 改为 `width: 360px`；删除 `.osw-crow`、`.osw-crow:hover`、`.osw-crow + .osw-crow`、`.osw-crow.is-off` 四条规则；新增 `.osw-proc-grid`（`display:flex; flex-wrap:wrap; gap:8px; padding:10px 12px`）、`.osw-cell`（`flex:0 1 auto; min-width:152px; display:flex; flex-direction:column; gap:4px; padding:8px 10px; border:1px solid #eef2f7; border-radius:8px; background:#fff`）、`.osw-cell.is-off`（`opacity:0.45`）、`.osw-cell-top`（`display:flex; align-items:center; gap:6px`）；将 `.osw-qty` 的 `width:94px; margin-left:auto` 改为 `width:100%`；将 `.osw-proc` 的 `flex:0 0 110px` 改为 `flex:1; min-width:0`；将 `.osw-remain` 保持 `font-size:11px`。同时把媒体查询中的 `.osw-crow`、`.osw-proc` 两条移动端规则改为 `.osw-proc-grid { flex-direction: column; }` 与 `.osw-cell { min-width: 0; }`。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 3: 改造模板为横向工序格容器**
action: 编辑 `frontend-vite/src/views/outsource/components/OutsourceShipDialog.vue` 右栏模板：把当前 `v-for="r in p.processes"` 的 `.osw-crow` 元素外面包一层 `<div class="osw-proc-grid">`；把 `.osw-crow` 元素改名为 `.osw-cell`，其内部结构改为纵向三段——第一段 `<div class="osw-cell-top">` 包住勾选框（`v-model="r.input.on"`、`class="osw-cbx"`、`:aria-label="`发货 ${p.productName} ${r.processType}`"`）与工序名（`<span class="osw-proc" :title="r.processType">{{ r.processType }}</span>`），第二段为 `<span class="osw-remain">剩 {{ r.remaining.toLocaleString() }}</span>`，第三段为数量框（`v-model.number="r.input.qty"`、`class="osw-qty"`、`:class` 保留 `is-invalid` 判定、`:disabled="!r.input.on"`、`:aria-label` 保持 `${p.productName} ${r.processType} 本次发货数量`）。`:class` 绑定由 `['osw-crow', { 'is-off': !r.input.on }]` 改为 `['osw-cell', { 'is-off': !r.input.on }]`。不要改动任何 `<script setup>` 逻辑。
loop: false
max_iterations: 1
verify: npm run type-check

- [ ] **Step 4: 更新测试选择器以匹配工序格结构**
action: 编辑 `frontend-vite/src/test/OutsourceShipDialog.test.ts`：把所有 `.osw-crow` 选择器替换为 `.osw-cell`（涉及用例「点卡片=加入清单」「每道工序可单独取消勾选」「每道工序独立填数量」「同一客户同产品跨多订单合并」「同一 SKU 的同一工序跨订单合并」「同一产品多工序在清单中逐行展示」）；新增断言：每个 SKU 卡片内 `.osw-proc-grid` 数量为 1，且该容器内 `.osw-cell` 数量等于该 SKU 的去重工序数。用例标题中「逐行展示」改为「同一行内横向展示」。
loop: false
max_iterations: 1
verify: npx vitest run src/test/OutsourceShipDialog.test.ts

- [ ] **Step 5: 回归修复直到测试全绿**
action: 运行测试；若有失败，逐条对照新结构修正断言或实现（不得通过放宽断言来掩盖真实缺陷）。重点关注：工序名序列、数量框数量与默认值、is-off 置灰、数量拆分 payload。
loop: until npx vitest run src/test/OutsourceShipDialog.test.ts exits 0
max_iterations: 4
verify: npx vitest run src/test/OutsourceShipDialog.test.ts

- [ ] **Step 6: 浏览器实测窄屏与宽屏布局**
action: 打开 `http://192.168.0.95:3000/outsource/shipments`，点击「批量发货」，点左栏「全选」使 5 个 SKU 入清单。在 1080px 视口下检查：每个 SKU 卡片内 `.osw-proc-grid` 为 flex-wrap、无横向溢出（`scrollWidth <= clientWidth`）、「企鹅的订单」6 道工序自动换行；改「变形金刚」的「转印」数量为 5000，确认另一行不受影响、底栏合计与按钮数字同步变化。再用 `browser_evaluate` 读取 `.osw-panes`、`.osw-left`、`.osw-right` 宽度确认右栏已加宽。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 每个 SKU 卡片内工序横向排列且无横向溢出；数量框可独立编辑且互不影响

- [ ] **Step 7: 确认提交口径未回归**
action: 在浏览器中把某 SKU 的某道工序数量改为 250（其各订单剩余分别为 100/200/300），点击「生成发货单」进入确认态，确认提示为「将按订单生成 2 张发货单」且合计 250 件；随后点「返回调整」退出确认态，不实际提交。
loop: false
max_iterations: 2
verify:
  type: browser
  url: http://192.168.0.95:3000/outsource/shipments
  check: 确认态显示按订单生成的张数与拆分后的合计件数一致，且未产生真实发货单
