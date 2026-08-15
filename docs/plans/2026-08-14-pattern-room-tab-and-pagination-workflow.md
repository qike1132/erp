---
intent: 删除「全部」TAB 并默认选中「进行中」，将已完成打样项目表格改为服务端分页并接入共享翻页组件
success_criteria: 状态 TAB 仅剩「进行中/已完成/已取消」且默认「进行中」；已完成表格按 20 条/页服务端分页、翻页正确；后端单测与前端类型检查通过
risk_level: low
auto_approve: true
---

# 2026-08-14 pattern-room TAB 精简 + 已完成表格服务端分页

## Steps

- [ ] **Step 1: 后端已完成表格服务端分页**
action: 修改 d:\erp_system\fastapi_app\services\customer_sampling_service.py 的 get_completed_table 函数，新增 page 与 per_page 参数（默认 page=1, per_page=20）。先执行 count 查询得到 total，再用 offset/limit 分页取项目。返回结构增加 pages 与 current_page。修改 d:\erp_system\fastapi_app\schemas\customer_sampling.py 的 CompletedTableResponse 增加 pages: int 与 current_page: int 字段。修改 d:\erp_system\fastapi_app\api\v1\endpoints\customer_sampling.py 的 api_get_completed_table 增加 page: int = Query(1, ge=1) 与 per_page: int = Query(20, ge=1, le=100) 参数并透传给 service。
loop: false
verify:
  type: shell
  command: python -c "import ast; ast.parse(open(r'd:\erp_system\fastapi_app\services\customer_sampling_service.py',encoding='utf-8').read())"

- [ ] **Step 2: 更新后端单测并验证**
action: 修改 d:\erp_system\tests\test_customer_sampling_api.py，在 test_completed_table_endpoint 中验证分页字段 pages/current_page 存在，并新增一个分页断言（如请求 page=1&per_page=1 时 total 不变、items 长度受 per_page 限制）。
loop: until tests pass
max_iterations: 3
verify:
  type: shell
  command: python -m pytest tests/test_customer_sampling_api.py -q

- [ ] **Step 3: 前端 API 层增加分页参数**
action: 修改 d:\erp_system\frontend-vite\src\api\patternRoom.ts，将 getCompletedTable 参数类型扩展为 { keyword?: string; pattern_maker_id?: number; page?: number; per_page?: number }，并在 CompletedTableResponse 类型中增加 pages 与 current_page 字段（若已存在则忽略）。
loop: false
verify:
  type: shell
  command: cd d:\erp_system\frontend-vite && npx vue-tsc --noEmit -p tsconfig.app.json

- [ ] **Step 4: 前端视图支持分页状态**
action: 修改 d:\erp_system\frontend-vite\src\views\pattern-room\PatternRoomView.vue：将 statusFilter 默认值改为 'in_progress'；新增 completedPage = ref(1) 与 completedPerPage = 20；loadCompletedTable 中传 { keyword, page: completedPage.value, per_page: completedPerPage }，并读取 res.pages 计算总页数（新增 completedPages ref）；onStatusChange 的 all 分支改为 in_progress（status 取值逻辑保持 undefined 仅当 in_progress）；onSearch 同样重置 completedPage 到 1。
loop: false
verify:
  type: shell
  command: cd d:\erp_system\frontend-vite && npx vue-tsc --noEmit -p tsconfig.app.json

- [ ] **Step 5: 精简 TAB 选项并默认进行中**
action: 修改 d:\erp_system\frontend-vite\src\views\pattern-room\components\CustomerGroupList.vue 的 STATUS_OPTIONS，删除 { value: 'all', label: '全部' }，保留 in_progress/completed/cancelled；将 statusFilter 默认值从 'all' 改为 'in_progress'。
loop: false
verify:
  type: shell
  command: cd d:\erp_system\frontend-vite && npx vue-tsc --noEmit -p tsconfig.app.json

- [ ] **Step 6: 已完成表格接入共享翻页组件**
action: 修改 d:\erp_system\frontend-vite\src\views\pattern-room\components\ProjectCompletedTable.vue：新增 props totalPages 与 totalItems 与 currentPage；新增 emit 'update:page'；在表格下方（pct-wrap 内、pct-screen 之后）引入 UiPagination（import '@/components/ui/UiPagination.vue'），当 totalItems > 每页条数 时渲染，绑定 :current-page="currentPage" :total-pages="totalPages" :total-items="totalItems" @update:current-page="$emit('update:page', $event)"。同时 PatternRoomView.vue 中给 ProjectCompletedTable 传入 :current-page="completedPage" :total-pages="completedPages" :total-items 由 completedItems 数量与分页推导（若无 totalItems 传 0 则用 completedPages*perPage），并监听 @update:page 更新 completedPage 以重新加载表格。
loop: false
verify:
  type: shell
  command: cd d:\erp_system\frontend-vite && npx vue-tsc --noEmit -p tsconfig.app.json

- [ ] **Step 7: 全量验证**
action: 运行后端 customer_sampling 相关测试与前端类型检查，确认全部通过。
loop: until all pass
max_iterations: 3
verify:
  type: shell
  command: python -m pytest tests/test_customer_sampling_api.py -q && cd d:\erp_system\frontend-vite && npx vue-tsc --noEmit -p tsconfig.app.json