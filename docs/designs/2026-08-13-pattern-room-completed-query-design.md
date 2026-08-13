---
design_type: feature
created_at: 2026-08-13
---

# 打样模块已完成项目表格查询设计

## Intent Contract

```
intent: 为打样模块左侧列表区域增加状态筛选胶囊与已完成项目表格查询功能，
        支持「全部/进行中/已完成/已取消」状态筛选，选中「已完成」时左侧切换为
        报表级表格视图，支持 Excel 导出与打印，点击表格行可查看项目详情。
constraints:
  - 不破坏现有分组列表展示逻辑（默认状态仍展示分组列表）
  - 不改变右侧详情面板（ProjectDetailPanel）交互逻辑
  - 复用现有 API 路径前缀与权限体系（customer_sampling_manage 仅写操作需要）
  - 不发生数据库表结构重构
  - 权限仅影响写操作（导出/打印无需特殊权限，有登录即可）
success_criteria:
  - 后端 pytest 全部通过（含新增的 completed_at / 状态筛选 / 导出用例）
  - 前端 npm run type-check / build 通过
  - 状态筛选胶囊（全部/进行中/已完成/已取消）切换正常，默认选中「全部」
  - 选中「已完成」时左侧卡片列表切换为报表表格视图
  - 表格字段：序列号、产品名、版师、完成时间、部位数量、操作人、状态
  - 点击表格行 → 右侧详情面板展示该项目的完整详情
  - 导出 Excel 按钮 → 下载当前筛选结果的 Excel 文件
  - 打印按钮 → 打印当前表格视图
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests (backend): pytest tests/test_customer_sampling_api.py -x -v
  - run type-check (frontend): npm run type-check
  - run build: npm run build
  - check: 页面首次加载 → 左侧显示分组列表，顶部状态胶囊显示「全部/进行中/已完成/已取消」
  - check: 点击「已完成」→ 左侧切换为表格视图，显示已完成项目列表
  - check: 表格行点击 → 右侧详情面板展示正确项目详情
  - check: 导出 Excel → 下载有效文件，打开后字段与表格一致
  - check: 打印 → 浏览器打印预览显示表格
  - confirm: 无编译错误；新后端用例通过
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本文件）
  - 合并前 code-review
rollback: 数据库迁移可回滚（down_revision）；前端表格组件可整体还原不影响分组列表
ownership: 打样模块负责人
```

## Scope

| In | Out |
| --- | --- |
| 数据库迁移：`customer_sampling_project` 表新增 `completed_at` 列 | 修改现有分组列表展示逻辑 |
| 后端：`list_projects` 增加 `status` 筛选参数 | 修改右侧详情面板 |
| 后端：`update_project_status` 完成时写入 `completed_at` | 修改其他模块 |
| 后端：新增表格数据查询端点（含分组统计部位数量） | 大文件上传/流式导出 |
| 后端：新增 Excel 导出端点（openpyxl） | 批量导出/定时导出 |
| 后端：扩展 `ProjectSummary` Schema 增加 `completed_at`、`parts_count` | 权限体系改动 |
| 前端：CustomerGroupList 顶部增加状态筛选胶囊 | 移动端适配 |
| 前端：新增报表表格组件（ProjectCompletedTable） | 表格内嵌编辑功能 |
| 前端：PatternRoomView 状态管理调整（筛选状态、viewMode 切换） | 表格排序/分页（后端返回全部结果） |
| 前端：表格行点击 → 复用现有 selectProject 逻辑 | - |
| 测试：后端状态筛选 + 导出用例 | - |

## Decisions

| # | 决策 | 说明 | 备选 |
| --- | --- | --- | --- |
| 1 | 状态筛选置于左侧列表顶部胶囊样式 | 与全系统统一药丸样式一致，不新增独立 TAB | 独立 TAB（用户确认选中方案 A） |
| 2 | 新增 `completed_at` 字段，完成时写入 | 查询准确简单，一次迁移 | 从审计日志推断（用户确认选新增字段） |
| 3 | 表格视图由后端专用端点返回数据 | 与 `list_projects` 解耦，可返回部位数量等聚合字段 | 复用 `list_projects` + status 筛选 |
| 4 | 导出 Excel 由后端生成（openpyxl），前端下载 blob | 后端可直接用统计数据，避免前端二次计算 | 前端生成 xlsx 库（sheetjs） |
| 5 | 表格一次性返回全部匹配数据（不分页） | 已完成项目数量通常有限（≤ 数百），简化前端 | 分页查询 |
| 6 | 权限不影响查询：所有登录用户均可查看已完成项目表格 | 查询而非写操作，无需特殊权限 | 仅 customer_sampling_manage 可查 |
| 7 | 表格行点击复用现有 `onSelectProject` + `projectHook.fetchDetail` | 保持与卡片列表一致的详情查看体验 | 表格内嵌详情展开 |

## Surface

### API

**1. 扩展 `list_projects` 端点**

新增 `status` 查询参数：

```
GET /api/v1/pattern-room/projects?page=1&per_page=20&status=completed&keyword=xxx&pattern_maker_id=xxx
```

现有 `ProjectSummary` Schema 扩展：

```python
class ProjectSummary(BaseModel):
    # ... 现有字段
    completed_at: str | None = None  # 新增
    parts_count: int = 0              # 新增（该项目的部位总数）
```

**2. 新增已完成项目表格查询端点**

```
GET /api/v1/pattern-room/projects/completed-table?keyword=xxx&pattern_maker_id=xxx
```

返回 `CompletedTableResponse`，行字段为：`id`、`sequence_no`、`product_name`、`pattern_maker_name`、`completed_at`、`parts_count`（该项目的部位总数）、`operator_name`（标记为完成的操作人）、`status`（恒为 completed）。

**3. 新增 Excel 导出端点**

```
GET /api/v1/pattern-room/projects/completed-table/export?keyword=xxx&pattern_maker_id=xxx
```

返回 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` 流式响应。文件包含字段：序列号、产品名、版师、完成时间、部位数量、操作人、状态。

### Storage

**迁移脚本**：`pg_standalone_031_add_completed_at.sql`

```sql
ALTER TABLE customer_sampling_project
  ADD COLUMN completed_at TIMESTAMP WITH TIME ZONE;
CREATE INDEX idx_csp_completed_at ON customer_sampling_project (completed_at DESC);
```

**Service 写入**：`update_project_status` 中，当 `status='completed'` 且旧状态不为 `completed` 时，设置 `project.completed_at = datetime.now(timezone.utc)`。从其他状态变为非 completed 时清空 `completed_at = None`。

### Components

**CustomerGroupList.vue**（修改）：
- 列表顶部新增状态筛选胶囊区域（全部/进行中/已完成/已取消）
- 新增 `viewMode` prop（`group` / `table`）控制展示模式
- 接收 `completedProjects` / `completedLoading` prop
- 新增 `@export-excel` / `@print-table` 事件
- 新增 `@select-project-from-table` 事件（表格行点击）

**ProjectCompletedTable.vue**（新增）：
- 报表表格组件，接收 `items: CompletedTableRow[]`
- 展示字段：序列号、产品名、版师、完成时间、部位数量、操作人、状态
- 行点击事件向外 emit
- 导出/打印按钮（置于表格顶部操作栏）
- 考虑打印样式（`@media print`）

**PatternRoomView.vue**（修改）：
- 新增 `viewMode` 响应式状态（`group` / `table`）
- 新增 `completedProjects` / `completedLoading` 状态
- 新增 `onStatusFilterChange` 处理函数
- 当状态筛选为「已完成」时，调用 `fetchCompletedTable` 加载表格数据
- 导出/打印处理函数
- 表格行点击 → 复用 `onSelectProject` 逻辑

### Files-touched

- **数据库迁移**：`fastapi_app/alembic/versions/pg_standalone_031_add_completed_at.py`
- **后端模型**：`fastapi_app/shared_models/customer_sampling.py`（completed_at 字段）
- **后端 Schema**：`fastapi_app/schemas/customer_sampling.py`（扩展 ProjectSummary + 新增 CompletedTableRow/Response）
- **后端 Service**：`fastapi_app/services/customer_sampling_service.py`（completed_at 写入 + 表格查询 + 导出）
- **后端 API**：`fastapi_app/api/v1/endpoints/customer_sampling.py`（新增端点 + 扩展现有端点）
- **后端依赖**：`requirements.txt`（添加 openpyxl）
- **前端 API**：`frontend-vite/src/api/patternRoom.ts`（新增类型 + 方法）
- **前端组件**：`frontend-vite/src/views/pattern-room/components/CustomerGroupList.vue`（状态胶囊 + viewMode）
- **前端组件**：`frontend-vite/src/views/pattern-room/components/ProjectCompletedTable.vue`（新建）
- **前端视图**：`frontend-vite/src/views/pattern-room/PatternRoomView.vue`（状态管理 + 事件绑定）
- **测试**：`tests/test_customer_sampling_api.py`（新增状态筛选 + 导出用例）

## Risks & Open Questions

- **已完成项目再次标记为完成**：`completed_at` 不会重复更新（仅当旧状态不为 completed 时写入），已处理。
- **从已完成变更为其他状态再变回已完成**：`completed_at` 会被重新写入（当前时间），符合预期（用户完成了第二轮操作）。
- **表格不分页，数据量较大时**：已完成项目通常不会超过数百条，且表格查询含关键词筛选，性能可接受。若后续数据量增长，可改为分页。
- **导出 Excel 依赖 openpyxl**：需在环境中安装，建议加入 `requirements.txt`。
- **打印样式**：需为表格视图添加 `@media print` 样式，隐藏无关 UI 元素（左侧胶囊、右侧面板等），仅打印表格内容。