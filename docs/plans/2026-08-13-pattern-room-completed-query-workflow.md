---
intent: 为打样模块左侧列表区域增加状态筛选胶囊与已完成项目表格查询功能，支持「全部/进行中/已完成/已取消」状态筛选，选中「已完成」时左侧切换为报表级表格视图，支持 Excel 导出与打印，点击表格行可查看项目详情
success_criteria: 后端 pytest 通过；前端 type-check/build 通过；状态胶囊切换正常；选中「已完成」左侧切换为表格；表格字段完整；表格行点击看详情；Excel 可下载；打印正常
risk_level: low
auto_approve: true
---

# 打样模块已完成项目表格查询

设计文档: docs/designs/2026-08-13-pattern-room-completed-query-design.md

## Steps

- [x] **Step 1: 数据库迁移添加 completed_at 字段**
action: 在 `d:\erp_system\migrations\versions\` 新建 `pg_standalone_032_add_completed_at.py`。参照 `pg_standalone_031_pattern_maker.py` 的写法。revision='pg_standalone_032_add_completed_at'，down_revision='pg_standalone_031_pattern_maker'。upgrade()：给 `customer_sampling_project` 表 `op.add_column` 添加 `completed_at`（`sa.DateTime(timezone=True)`，nullable，comment='完成时间'），并 `op.create_index('idx_csp_completed_at', 'customer_sampling_project', ['completed_at'])`。downgrade()：drop_index + drop_column。
verify:
  - type: artifact
  - path: migrations/versions/pg_standalone_032_add_completed_at.py
  - assert:
      kind: exists

- [x] **Step 2: 更新后端 ORM 模型与 to_dict**
action: 在 `d:\erp_system\fastapi_app\shared_models\customer_sampling.py` 的 `CustomerSamplingProject` 类中，在 `status` 字段定义之后新增 `completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment='完成时间')`。在 `to_dict()` 返回的 dict 中增加 `'completed_at': self.completed_at.strftime('%Y-%m-%d %H:%M:%S') if self.completed_at else None`。在 `__table_args__` 增加 `Index('idx_csp_completed_at', desc('completed_at'))`。
verify:
  - type: shell
  - command: python -m py_compile fastapi_app/shared_models/customer_sampling.py
gate: auto

- [x] **Step 3: service 更新状态时写入/清空 completed_at**
action: 在 `d:\erp_system\fastapi_app\services\customer_sampling_service.py` 的 `update_project_status` 函数中：当 `status == 'completed'` 且 `old_status != 'completed'` 时，设置 `project.completed_at = datetime.now(timezone.utc)`；当 `status != 'completed'` 时，设置 `project.completed_at = None`。确保 `datetime` 和 `timezone` 已在文件顶部导入。
verify:
  - type: shell
  - command: python -m py_compile fastapi_app/services/customer_sampling_service.py
gate: auto

- [x] **Step 4: 扩展后端 Schema 增加 completed_at 与 parts_count**
action: 在 `d:\erp_system\fastapi_app\schemas\customer_sampling.py` 的 `ProjectSummary` 中新增字段 `completed_at: str | None = None` 和 `parts_count: int = 0`。
verify:
  - type: shell
  - command: python -m py_compile fastapi_app/schemas/customer_sampling.py
gate: auto

- [x] **Step 5: service 扩展 list_projects 支持 status 筛选**
action: 在 `d:\erp_system\fastapi_app\services\customer_sampling_service.py` 的 `list_projects` 函数签名新增 `status: str | None = None` 参数。在函数内 conditions 构建处：当 `status` 不为空时，`conditions.append(CustomerSamplingProject.status == status)`。保持分页与图片批量预取逻辑不变。调用方 `_project_to_summary` 需同步输出 parts_count（Step 4 的字段）。在 `_project_to_summary` 中，若 `project.parts` 已加载则取 `len(project.parts)`，否则统计需保证不产生 N+1（本步骤仅确保 summary 输出该字段，取值可先为 0，Step 6 完成表格专用聚合）。
verify:
  - type: shell
  - command: python -m py_compile fastapi_app/services/customer_sampling_service.py
gate: auto

- [x] **Step 6: service 新增 get_completed_table 聚合函数**
action: 在 `d:\erp_system\fastapi_app\services\customer_sampling_service.py` 新增 `async def get_completed_table(db, *, keyword=None, pattern_maker_id=None) -> dict`。逻辑：
1. 构建查询：`select(CustomerSamplingProject)` where `status == 'completed'`；keyword 匹配 `sequence_no`/`product_name` ILIKE；pattern_maker_id 精确筛选。order by `updated_at.desc()`。
2. 预取图片 URL（复用 `_batch_get_image_urls`）。
3. 对每个项目统计部位数量：`parts_count` 用一次 group-by 查询统计该项目所有角色（含全部版本）的 part 行数，避免 N+1：`select(CustomerSamplingPart.project_id, func.count()).where(CustomerSamplingPart.project_id.in_(ids)).group_by(CustomerSamplingPart.project_id)`。
4. 查询操作人：从 `customer_sampling_change_log` 取每个项目最近一次 `action='update_project_status'` 且 field_diffs 含 `status->completed` 的记录 operator_name（可在 service 内查询后聚合为 project_id→operator_name 映射）。
5. 返回 `{'success': True, 'items': [ {id, sequence_no, product_name, pattern_maker_name, completed_at, parts_count, operator_name, status} ], 'total': N}`。pattern_maker_name 取 `project.pattern_maker_name or project.pattern_maker.name`。
verify:
  - type: shell
  - command: python -m py_compile fastapi_app/services/customer_sampling_service.py
gate: auto

- [x] **Step 7: 扩展后端 API 列表端点支持 status + 新增表格端点**
action: 在 `d:\erp_system\fastapi_app\api\v1\endpoints\customer_sampling.py`：
1. `api_list_projects` 增加 `status: str | None = Query(None, description='状态筛选')` 参数，传给 svc.list_projects。
2. 新增端点 `GET /projects/completed-table`：`@router.get('/projects/completed-table', response_model=...)`，参数 `keyword`、`pattern_maker_id`，调用 svc.get_completed_table。新增 Pydantic schema `CompletedTableRow`（id, sequence_no, product_name, pattern_maker_name, completed_at, parts_count, operator_name, status）与 `CompletedTableResponse`（success, items, total），在 schema 文件中定义后导入。注意：该端点路由需放在 `/{project_id}` 之前注册以避免路径冲突。
verify:
  - type: shell
  - command: python -m py_compile fastapi_app/api/v1/endpoints/customer_sampling.py
gate: auto

- [x] **Step 8: 后端新增 Excel 导出端点**
action: 在 `d:\erp_system\fastapi_app\api\v1\endpoints\customer_sampling.py` 新增 `GET /projects/completed-table/export` 端点。复用 svc.get_completed_table 获取数据（keyword/pattern_maker_id 同参数），用 `openpyxl` 生成 Workbook：一个 Sheet 名「已完成打样」，表头为 序列号/产品名/版师/完成时间/部位数量/操作人/状态，逐行写入 items。用 `fastapi.responses.StreamingResponse` 返回 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`，`Content-Disposition` attachment 文件名 `已完成打样_YYYYMMDDHHMMSS.xlsx`（用 BytesIO）。若 openpyxl 未安装，先 `pip install openpyxl`（已在 requirements/base.txt:36 声明 openpyxl==3.1.5）。权限：仅登录（不加 require_permission，与查询端点一致）。
verify:
  - type: shell
  - command: python -m py_compile fastapi_app/api/v1/endpoints/customer_sampling.py
gate: auto

- [x] **Step 9: 后端新增测试用例**
action: 在 `d:\erp_system\tests\test_customer_sampling_api.py` 新增测试：
1. `test_list_projects_status_filter`：创建一个 in_progress 与一个 completed 项目，调用 `GET /api/v1/pattern-room/projects?status=completed` 断言只返回 completed 项目，且 items[0].status == 'completed'。
2. `test_completed_table_endpoint`：标记一个项目完成（调用 status 端点），调用 `GET /api/v1/pattern-room/projects/completed-table` 断言返回该项目且 completed_at 非空、parts_count >= 0。
3. `test_completed_table_export`：调用 export 端点，断言 200 且 `Content-Type` 为 xlsx 类型。
参照该文件现有 fixture 与测试风格。运行后修正。
verify:
  - type: shell
  - command: pytest tests/test_customer_sampling_api.py -x -q --no-header --no-summary
gate: auto

- [x] **Step 10: 前端 API 客户端新增类型与方法**
action: 在 `d:\erp_system\frontend-vite\src\api\patternRoom.ts`：
1. 新增接口 `CompletedTableRow`（id, sequence_no, product_name, pattern_maker_name, completed_at, parts_count, operator_name, status）与 `CompletedTableResponse`（success, items, total）。
2. 在 `patternRoomApi` 增加 `getCompletedTable: (params?: { keyword?: string; pattern_maker_id?: number }) => get<CompletedTableResponse>('/pattern-room/projects/completed-table', params)` 和 `exportCompletedTable: (params?: { keyword?: string; pattern_maker_id?: number }) => download('/pattern-room/projects/completed-table/export', '已完成打样.xlsx', params)`。确认 `download` 已从 './request' 导入（未导入则补充）。
verify:
  - type: shell
  - command: npm run type-check --prefix frontend-vite
gate: auto

- [x] **Step 11: 前端新建 ProjectCompletedTable 表格组件**
action: 在 `d:\erp_system\frontend-vite\src\views\pattern-room\components\` 新建 `ProjectCompletedTable.vue`：
1. props：`items: CompletedTableRow[]`、`loading: boolean`。
2. emits：`select`（行点击）、`export`、`print`。
3. 模板：表格顶部操作栏含「导出 Excel」「打印」按钮（`@click="$emit('export')"` / `@click="$emit('print')"`）；`<table>` 列：序列号/产品名/版师/完成时间/部位数量/操作人/状态；每行 `@click="$emit('select', row.id)"`，`cursor:pointer`；空状态提示「暂无已完成项目」。
4. 样式：白色卡片、斑马纹、表头灰底、紧凑字体 12-13px。
5. 打印样式：参照 `PrintDialog.vue` 的 `:global(body.pd-printing > *)` 隔离方案，本组件用独立 body class `pct-printing`：`:global(body.pct-printing > *){display:none!important}` + `:global(body.pct-printing > .pct-print-sheet){display:block!important;padding:20px}`，且组件根节点渲染带 `.pct-print-sheet` 的 Teleport 到 body 的打印内容（含标题 + 表格）。通过 `@media print` 设置 `@page{margin:0}`。
verify:
  - type: artifact
  - path: frontend-vite/src/views/pattern-room/components/ProjectCompletedTable.vue
  - assert:
      kind: exists

- [x] **Step 12: CustomerGroupList 增加状态筛选胶囊与 viewMode 切换**
action: 在 `d:\erp_system\frontend-vite\src\views\pattern-room\components\CustomerGroupList.vue`：
1. 在搜索框下方新增状态筛选胶囊行（全部/进行中/已完成/已取消），本地 `statusFilter` ref，默认 'all'，`@change` 时 `$emit('status-change', value)`。胶囊样式参照全系统药丸样式（白底圆角组 + 渐变激活态）。
2. props 新增 `viewMode: 'group' | 'table'`（默认 'group'）与 `completedItems: CompletedTableRow[]`、`completedLoading: boolean`。
3. emits 新增 `status-change`、`select-completed`、`export-excel`、`print-table`。
4. 模板：`v-if="statusFilter==='completed'"` 时渲染 `ProjectCompletedTable`（导入该组件），绑定 `@select="$emit('select-completed',$event)"`、`@export="$emit('export-excel')"`、`@print="$emit('print-table')"`；否则渲染现有分组/卡片逻辑。当 statusFilter==='completed' 时隐藏版师列表与卡片区，整块替换为表格。
verify:
  - type: shell
  - command: npm run type-check --prefix frontend-vite
gate: auto

- [x] **Step 13: PatternRoomView 状态管理与事件绑定**
action: 在 `d:\erp_system\frontend-vite\src\views\pattern-room\PatternRoomView.vue`：
1. 新增 `statusFilter = ref('all')`、`viewMode = computed(() => statusFilter.value==='completed' ? 'table' : 'group')`、`completedItems = ref<CompletedTableRow[]>([])`、`completedLoading = ref(false)`。
2. 新增 `async function loadCompletedTable()`：调用 `patternRoomApi.getCompletedTable({ keyword, pattern_maker_id })`，写入 completedItems。keyword 用现有 onSearch 的防抖关键字（新增 `searchKeyword` ref 记录）；pattern_maker_id 用当前分组选中（若已有则传入，否则不传）。
3. 新增 `onStatusChange(val)`：设置 statusFilter；若 completed 则 loadCompletedTable。
4. 新增 `onExportExcel()`：调用 `patternRoomApi.exportCompletedTable({ keyword, pattern_maker_id })`，成功 toast.success('导出成功')。
5. 新增 `onPrintTable()`：为 body 添加 `pct-printing` class，window.print()，afterprint 移除（参照现有 handlePrint 的 body class 模式）。
6. 模板：CustomerGroupList 绑定 `:view-mode="viewMode"`、`:completed-items="completedItems"`、`:completed-loading="completedLoading"`、`@status-change="onStatusChange"`、`@select-completed="onSelectProject"`、`@export-excel="onExportExcel"`、`@print-table="onPrintTable"`（抽屉内 CustomerGroupList 同步绑定）。导入 CompletedTableRow 类型。
7. onSearch 中记录 `searchKeyword.value = keyword`，并在状态为 completed 时刷新表格。
verify:
  - type: shell
  - command: npm run type-check --prefix frontend-vite
gate: auto

- [x] **Step 14: 前端构建与后端全量测试**
action: 在 `d:\erp_system\frontend-vite` 运行 `npm run build`；在 `d:\erp_system` 运行 `pytest tests/test_customer_sampling_api.py -q`。若失败，修复后重跑直至通过。
verify:
  - type: shell
  - command: pytest tests/test_customer_sampling_api.py -q --no-header --no-summary
gate: human

