---
intent: 在板房管理（/pattern-room）页面为当前选中的打样产品新增「打印打样单」功能：一键打印该产品已录入的全部部位明细（部位名称/版本/供应商/布料名称/色号），打印内容同时包含产品图片与产品名称、编号、客户等抬头信息。
success_criteria: 前端 npm run type-check / test / build 全部通过；顶部操作栏出现「打印打样单」按钮，仅当已选中产品且有部位数据时可点击；点击后弹出打印预览，含产品图片、抬头信息与部位明细表格；@media print 下仅显示打样单内容，其余界面隐藏。
risk_level: low
auto_approve: false
---

## Steps

- [x] **Step 1: 新增 PrintDialog.vue 打印弹窗组件**
action: 在 frontend-vite/src/views/pattern-room/components/PrintDialog.vue 新建打印弹窗组件。props 接收 `open: boolean`、`project: ProjectDetailResponse | null`、`parts: PartDetail[]`。模板结构：外层遮罩+居中弹窗（屏幕显示时带背景与关闭/打印按钮），内容区 class=print-content 含：标题「打样单」、抬头信息（产品图片 product_image_url 与 product_name / sequence_no / customer_name）、部位明细表格（表头：部位名称/版本/供应商/布料名称/色号，遍历 parts 渲染每行，空值显示 '-'）。@media print 样式：隐藏遮罩背景、关闭/打印按钮与页面其余元素，仅显示 .print-content（position static、无阴影、无遮罩）。打印按钮调用 window.print()。emit 'close' 用于关闭弹窗。复用 @/api/patternRoom 的 ProjectDetailResponse 与 PartDetail 类型。
loop: false
verify:
  type: artifact
  path: frontend-vite/src/views/pattern-room/components/PrintDialog.vue
  assert:
    kind: exists

- [x] **Step 2: 在 PatternRoomView.vue 接入打印按钮与弹窗**
action: 编辑 frontend-vite/src/views/pattern-room/PatternRoomView.vue。1) import PrintDialog；2) 顶部操作栏（.pr-top-bar .pr-top-right 内）新增「打印打样单」按钮，仅在 selectedProjectId 非空且 partHook.partsByVersion.value.length > 0 时显示或可点击（未选中或无部位时禁用）；3) 新增状态 printVisible = ref(false)，点击按钮设置 printVisible=true；4) 在模板中添加 <PrintDialog :open="printVisible" :project="projectHook.currentProject.value" :parts="partHook.partsByVersion.value" @close="printVisible = false" />。保持现有按钮样式 class pr-add-btn 与 pr-add-btn--primary 风格一致。
loop: false
verify:
  type: artifact
  path: frontend-vite/src/views/pattern-room/PatternRoomView.vue
  assert:
    kind: exists

- [x] **Step 3: 前端类型检查**
action: 在 frontend-vite 目录运行 npm run type-check，确认无 TypeScript 编译错误。
loop: until 命令退出码为 0
max_iterations: 3
verify:
  type: shell
  command: npm run type-check
  cwd: frontend-vite

- [x] **Step 4: 前端单元测试**
action: 在 frontend-vite 目录运行 npm run test，确认既有测试全部通过、无新增失败。
loop: until 命令退出码为 0
max_iterations: 3
verify:
  type: shell
  command: npm run test
  cwd: frontend-vite

- [x] **Step 5: 前端构建**
action: 在 frontend-vite 目录运行 npm run build，确认成功生成构建产物。
loop: until 命令退出码为 0
max_iterations: 3
verify:
  type: shell
  command: npm run build
  cwd: frontend-vite
