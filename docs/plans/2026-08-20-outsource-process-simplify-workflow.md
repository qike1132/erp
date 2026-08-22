---
intent: 将订单外发工序弹窗精简为「工序 + 发货数量 + 收货数量 + 操作按钮」的紧凑分组表格，移除时间字段编辑
success_criteria: 弹窗仅 5 列且无任何时间字段；发货为行内输入；type-check 与既有测试通过
risk_level: low
auto_approve: true
branch: main
worktree: false
dirty_worktree: allow
---

# 订单外发工序弹窗精简重构 — 工作流

设计文档：docs/designs/2026-08-20-outsource-process-simplify-design.md

## Steps

- [x] **Step 1: 实现精简重构（3 个前端文件）**
action: 在 frontend-vite 下完成三处改动——(1) 重写 src/views/outsource/components/OutsourceProcessFlow.vue 为按 SKU 分组的紧凑表格（每 SKU 一组：通栏表头「SKU名 × 数量」+ 工序行；5 列：工序/发货数量/收货数量/状态/操作；发货数量列在 待发货&可发货 时渲染行内 number 输入框、其余回显 shipped_quantity 或 '-'；收货数量列回显 received_quantity 或 '-'；状态列保留待发货/已发货/已收货徽章；操作列按状态与权限渲染 发货(无数量禁用)/确认收货/删除(图标)；彻底移除所有时间展示与 datetime-local 编辑输入)；props 收窄为 processGroups/canManage/canShip/canReceive/statusLabel/handleShip/handleReceive/handleDeleteProcess。(2) 精简 src/views/outsource/components/OutsourceProcessDialog.vue 头部为 单号/客户 + 进度条/百分比/完成数 + 状态标签，移除「下单日期」「数量」meta，保留「按SKU预设生成工序」按钮与备货记录提示，并更新传给 flow 的 props（去掉 shortDate/toDateTimeLocal/updatePlanned 及模板中 detailTotalQuantity）。(3) 在 src/views/outsource/composables/useOutsourceProcess.ts 中删除 updatePlanned/toDateTimeLocal/shortDate/detailTotalQuantity 的定义与 return 导出（确认无其他文件引用后再删）。
verify: cd frontend-vite && npx vue-tsc --noEmit
loop: until 类型检查通过
max_iterations: 3

- [x] **Step 2: 前端回归测试**
action: 运行前端既有测试，确认本次重构未破坏其他模块。
verify: cd frontend-vite && npx vitest run
loop: until 全部测试通过
max_iterations: 3

- [x] **Step 3: 构建产物并供浏览器验证**
action: 在 frontend-vite 执行 npm run build，生成新 dist（nginx 以 frontend-vite/dist 为根，构建即生效）。
verify:
  - type: shell
    command: cd frontend-vite && npm run build
  - type: artifact
    path: frontend-vite/dist/index.html
    assert:
      kind: exists

- [x] **Step 4: 浏览器验证弹窗效果**
action: 打开 http://localhost:3000/outsource，点击任一订单行打开「订单外发工序」弹窗，人工确认：仅 5 列（工序/发货数量/收货数量/状态/操作）、无任何时间字段与 datetime-local 输入框、发货数量列行内输入与回显正确、发货/确认收货/删除按钮按状态与权限正确显隐（非贝乐用户可发货、贝乐用户可确认收货）。
verify:
  type: browser
  url: http://localhost:3000/outsource
  check: 弹窗仅 5 列且无时间输入框；按钮按状态与权限正确显隐
