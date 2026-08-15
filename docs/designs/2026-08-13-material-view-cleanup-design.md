---
design_type: feature
created_at: 2026-08-13
---

# 来料登记页面精简搜索栏与分页设计

## Intent Contract

```
intent: 精简 /material 来料登记页面：删除「来料进度」与「历史查询」两个 tab 的搜索栏全部代码
        （供应商/订单号/客户/分类/日期范围/重置），并将列表分页改为始终显示共享分页组件
        （UiPagination，已内置于 UiDataTable）。
constraints:
  - 页面路由 /material 与两个 tab（来料进度/历史查询）结构不变
  - 不删数据表格与导出按钮；导出时不再携带筛选参数（搜索栏已删）
  - 分页组件复用 UiDataTable 内置的 UiPagination（共享组件），不引入新组件
  - 只改 MaterialView.vue 单文件，不动后端接口
  - 遵循简约原则：删除搜索栏相关模板与 JS（filters 状态、重置函数、筛选参数、分类过滤）
success_criteria:
  - 前端 npm run type-check / test 全部通过
  - /material 两个 tab 顶部不再显示搜索栏
  - 列表底部始终显示共享分页栏（含 每页条数 / 共N条 / 页码 / 跳页）
  - 删除后无死代码引用（pFilters/hFilters/reset* 全部清理）
risk_level: low
```

## Verification Contract

```
verify_steps:
  - run tests (frontend): npm run type-check && npm run test
  - check: /material 页面两个 tab 均无搜索栏
  - check: 两个列表底部始终显示共享分页组件（UiPagination 样式）
  - check: script 中无 pFilters / hFilters / resetProgressFilters / resetHistoryFilters 残留
  - confirm: 无 P0/P1 编译错误；既有测试全部通过
```

## Governance Contract

```
approval_gates:
  - 设计文档批准（本次）
  - 实现计划（writing-plans）批准
  - 合并前 code-review
rollback: 单文件改动，git 还原 MaterialView.vue 即可；不涉及迁移与后端
ownership: 来料登记模块负责人
```

## Scope

| In | Out |
| --- | --- |
| 删除「来料进度」tab 搜索栏模板与 JS | 删除表格 / 导出按钮 |
| 删除「历史查询」tab 搜索栏模板与 JS | 改动后端接口 |
| 两个列表分页始终显示共享 UiPagination | 改动其他页面 |
| 清理 pFilters / hFilters / reset* 相关 JS | 改动分页组件本身 |

## Decisions

| # | 决策 | 选择 | 被否方案 |
| --- | --- | --- | --- |
| D1 | 删除范围 | 两个 tab 的搜索栏全部删除（用户确认） | 仅删「来料进度」 |
| D2 | 分页显示时机 | 始终显示共享分页组件（用户确认） | 仅多页时显示 |
| D3 | 实现方式 | 复用 UiDataTable 内置 UiPagination，仅把 `:paginator` 条件改为常真 | 单独手写分页逻辑 |

## Surface

**前端组件**（单文件）：
- `frontend-vite/src/views/material/MaterialView.vue`：删除两个 tab 的 `.mr-filters` 搜索栏模板；将两个 `UiDataTable` 的 `:paginator="pPages > 1"` / `:paginator="hPages > 1"` 改为始终显示；删除 script 中的 `pFilters`、`hFilters`、`resetProgressFilters`、`resetHistoryFilters`；`loadProgress`/`loadHistory` 移除筛选参数；`progressOrderRows` 移除 `pFilters.category` 分类过滤（改为展示全部非填充物料）；`exportData`/`exportHistory` 移除筛选参数。

## Risks & Open Questions

- `progressOrderRows` 原按 `pFilters.category` 过滤 items，删除后需改为展示全部非填充物料，避免删搜索栏导致物料明细消失。
- `UiDataTable` 的 `total-records` 当前传 `pPages * pPerPage`（= 总页数×每页数），翻页始终显示时 totalPages 计算一致，无需调整。
