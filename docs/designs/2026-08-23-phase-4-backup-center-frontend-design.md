---
design_type: phase
created_at: 2026-08-23
---

# Phase 4 设计 · 数据备份中心前端六模块重写

> 依据：`docs/ui-redesign/backup-center/{DESIGN.md, backage-center-prototype.html, TECHNICAL_PLAN.md v2 §4.3}`
> 范围：M4 前端落地——按原型从零建模为单视图六模块，并打通 M1/M2 后端能力。
> 验收：`vue-tsc --noEmit` + `vite build` 通过（无可视走查门槛）。

## Intent Contract

intent: 把现有双 Tab 的备份前端重写为单视图六模块「数据备份中心」，从原型建模、令牌贴合 DESIGN.md，并接通任务化/调度/settings/还原向导后端能力。

constraints:
- 不得破坏既有备份/还原/记录的核心数据语义（上传恢复、服务器列表还原、记录分页等仍可用或等价迁移）。
- 复用可用的既有组件与组合式（BackupModeSelector / FileRestorePanel / ServerBackupList / BackupRecordList / RestoreProgressBar / RestoreConfirmDialog / useBackupCenter 等），避免大改业务逻辑。
- 令牌优先映射应用现有 UI kit 与 `--color-*` 变量；仅当缺 token 时按 DESIGN.md 补充。
- 不引入新的运行时依赖（沿用现有 Vue3 + 自有 Ui 组件栈）。

success_criteria:
- 六模块（概览四卡 / 一键全量增量 / 定时任务 / 路径设置 / 备份记录 / 还原向导）在单视图按原型排布并能渲染。
- 全量/增量一键备份经 POST /full、/incremental 获取 task_id，经统一轮询展示进度至终态。
- 定时任务配置经 /backup/schedule CRUD 读写；路径设置经 /backup/settings + /settings/validate-path。
- 还原向导第 2 步差异预览接 POST /backup/restore/plan，危险确认沿用「输入 确认还原」，执行接异步还原。
- `vue-tsc --noEmit` 与 `vite build` 通过。

risk_level: medium

## Verification Contract

verify_steps:
  - run: `cd frontend-vite && npm run type-check` → 期望 exit 0
  - run: `cd frontend-vite && npm run build` → 期望成功产出 dist
  - check: 新组件经全局注册或显式 import，无未使用导入/死绑定（沿用 M4 清理纪律）
  - confirm: 六模块组件存在且被 BackupView 引用；`api/backup.ts` 新增绑定被实际调用

## Governance Contract

approval_gates:
  - 本设计文档评审通过（当前步骤）
  - writing-plans 生成的 workflow 拆解确认后进入实现
  - 实现收尾后代码评审 + type-check/build 通过再合入

rollback: 实现以独立小步提交；任一模块异常可 `git revert` 或回退到上一提交，前端不影响后端。

ownership: 备份小组 / 前端负责人；后端接口契约以 TECHNICAL_PLAN v2 §5 为准。

## Scope

| In | Out |
|----|-----|
| 单视图六模块布局（对齐原型 index 结构） | 后端逻辑改动（本 phase 仅前端） |
| 概览四卡（GET /backup/status 聚合） | 新增复杂图表/SSE（保持轮询） |
| 一键全量/增量（POST /full /incremental + 统一轮询） | 迁移旧同步 /save 入口（按 M4 下线） |
| 定时任务配置（/backup/schedule CRUD） | 后端 poller/种子（已在 M2 完成） |
| 路径设置（/backup/settings + validate-path） | 磁盘真实写测（仍由后端校验） |
| 备份记录表格（/backup/records 筛选/分页/搜索） | 分页本地化（保持服务端分页） |
| 还原向导（restore/plan + 异步还原 + 进度 + 结果/建议） | 真实还原执行（高危，走既有后端与维护窗） |
| 统一轮询 composable `useBackupTask.ts` | 移除既有 3 套轮询的残留 |

## Decisions

| # | 决策 | 选择 | 理由 / 备选 |
|---|------|------|------|
| 1 | 布局 | 从原型 HTML 全新建模单视图六模块 | 对齐 DESIGN.md；备选「重构既有双 Tab」被否（保真度低） |
| 2 | 后端对接 | 纳入 M1/M2 能力 | 功能闭环；全量/增量/定时/路径/差异预览均接真实 API |
| 3 | 验收 | type-check + build | 当前 DB 不稳，前端可独立构建验证 |
| 4 | 组件复用 | 复用既有子组件/组合式 | 降低风险、避免重复实现业务逻辑 |
| 5 | 令牌 | 应用现有 UI 变量为主、DESIGN.md 补充 | 与既有企业后台无缝衔接 |

## Surface

APIs（前端调用侧新增/扩展，路径以 `api/backup.ts` 为准）：
- 任务化：POST `/backup/full`、`/backup/incremental`（202 + task_id）；GET `/backup/progress/{task_id}` 轮询
- 定时：GET/POST `/backup/schedule`、PUT/DELETE `/backup/schedule/{id}`、POST `/backup/schedule/trigger`
- 路径：GET/POST `/backup/settings`、POST `/backup/settings/validate-path`
- 概览：GET `/backup/status`
- 记录：GET `/backup/records?page&page_size`
- 还原：POST `/backup/restore/plan`（差异预览）、异步还原 `/backup/async-import` / `/backup/async-restore-by-name/{name}?confirm=true`

Storage/状态：任务进度走后端 Redis（`erp:*_progress:*`），前端仅轮询单条 task_id；无前端持久化改动。

Components（前端新增）：
- `views/backup/BackupView.vue`（重写为单视图容器）/ 或新 `BackupCenterView.vue` 承载六模块
- `components/backup/BackupOverviewCards.vue`（四卡）
- `components/backup/BackupActions.vue`（全量/增量 + 任务卡）
- `components/backup/ScheduleConfig.vue`（定时 CRUD）
- `components/backup/PathSettings.vue`（路径 + 校验）
- `components/backup/BackupRecordTable.vue`（记录表格）
- `components/backup/RestoreWizard.vue`（向导 + 危险确认 + 结果）
- `composables/useBackupTask.ts`（统一轮询）

Files-touched：`frontend-vite/src/api/backup.ts`、`views/backup/**`、`components/backup/**`、路由/菜单（/backup 指向新视图）、必要时 `components.d.ts`。

## Risks & Open Questions

- 高风险操作（还原）只在向导层编排、仍走既有后端资料与维护窗口；前端只在 plan/确认后入队。
- 定时与路径模块依赖 M1/M2 已交付的后端（已在 commit cd8a04d 固化），契约以 §5 为准。
- 令牌映射若与既有 UI kit 冲突：以既有变量为准、DESIGN.md 仅补充缺项；落地时按组件评审。
- 是否保留旧双 Tab 路由作过渡：默认侧替换 /backup，旧入口下线留待 M5。