---
design_type: feature
created_at: 2026-08-14
---

# pattern-room 状态 TAB 精简 + 已完成表格服务端分页

## Intent Contract

```
intent: 删除「全部」TAB 并默认选中「进行中」，将已完成打样项目表格改为服务端分页并接入共享翻页组件
constraints: 不破坏 existing 接口对外行为（默认 page=1 / per_page=20）；保留左侧分组卡片虚拟滚动视图
success_criteria:
  - 状态 TAB 仅剩「进行中 / 已完成 / 已取消」三项，默认「进行中」
  - 已完成表格按 20 条/页服务端分页，翻页正确、总数正确
  - 后端单测与前端类型检查通过
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests: pytest tests/test_customer_sampling_api.py
  - check: vue-tsc 类型检查通过
  - confirm: 浏览器打开 /pattern-room 完成表格分页正常、TAB 默认「进行中」
```

## Governance Contract

```
approval_gates: 本设计获批后方可进入实现
rollback: git revert（改动集中在列出的文件）
ownership: 当前会话
```

## Scope

| In | Out |
|---|---|
| 删除「全部」TAB，默认「进行中」 | 改动「全部」TAB 之外的其他视图逻辑 |
| 已完成表格服务端分页（20/页） | 分组卡片列表分页（已用虚拟滚动，保持现状） |
| 接入共享 UiPagination 组件 | 新建自定义翻页组件 |

## Decisions

| # | 决策 | 说明 / 备选 |
|---|---|---|
| 1 | 默认 TAB 改为「进行中」 | 用户确认；替代方案为「已完成」 |
| 2 | 已完成表格服务端分页 | 用户确认；替代前端切片（数据量大时不利） |
| 3 | 复用现有 UiPagination 组件 | 共享组件已存在，无需新建 |
| 4 | 每页 20 条 | 用户确认；替代 50 或可切换 |

## Surface

- **API**：`GET /pattern-room/projects/completed-table` 新增 `page`（默认 1）、`per_page`（默认 20）查询参数；响应 `CompletedTableResponse` 增加 `pages`、`current_page` 字段。
- **Storage**：`CustomerSamplingProject` 无表结构变更。
- **Components**：
  - `CustomerGroupList.vue`：`STATUS_OPTIONS` 去掉「全部」，默认 `in_progress`。
  - `PatternRoomView.vue`：`statusFilter` 默认 `in_progress`；新增 `completedPage`、`completedPerPage`；`loadCompletedTable`/`onStatusChange`/`onSearch` 传分页参数。
  - `ProjectCompletedTable.vue`：底部接入 `UiPagination`，展示 `total`/`pages`，翻页触发 `update:page` 事件。
- **Files-touched**：
  - `fastapi_app/services/customer_sampling_service.py`
  - `fastapi_app/api/v1/endpoints/customer_sampling.py`
  - `fastapi_app/schemas/customer_sampling.py`
  - `frontend-vite/src/api/patternRoom.ts`
  - `frontend-vite/src/views/pattern-room/PatternRoomView.vue`
  - `frontend-vite/src/views/pattern-room/components/CustomerGroupList.vue`
  - `frontend-vite/src/views/pattern-room/components/ProjectCompletedTable.vue`
  - `tests/test_customer_sampling_api.py`

## Risks & Open Questions

- 默认「进行中」后，若用户无进行中项目，左侧显示空态属预期行为。
- 翻页后需重置页码到 1（搜索/切 TAB 时），避免越界。