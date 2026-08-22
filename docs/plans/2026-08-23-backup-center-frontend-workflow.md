---
intent: 把双 Tab 备份前端重写为单视图六模块「数据备份中心」，接通任务化/调度/settings/还原向导后端能力
success_criteria: vue-tsc 与 vite build 通过；六模块组件落成并被 BackupView 单视图容器引用；api/backup.ts 新增绑定被实际调用
risk_level: medium
auto_approve: true
---

## Steps

- [ ] **Step 1: 扩展 api/backup.ts 后端绑定**
action: 在 `frontend-vite/src/api/backup.ts` 的 backupApi 对象新增：`triggerFull/(payload?)` 调 POST `/backup/full`、`triggerIncremental` 调 POST `/backup/incremental`、`getStatus` 调 GET `/backup/status`、`listSchedules` GET `/backup/schedule`、`createSchedule(body)` POST、`updateSchedule(id,body)` PUT `/{id}`、`deleteSchedule(id)` DELETE、`getSettings` GET `/backup/settings`、`saveSettings(body)` POST、`validatePath(path)` POST `/backup/settings/validate-path`、`restorePlan(filename)` POST `/backup/restore/plan`；沿用既有 `get/post/del` 封装与返回类型约定。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 2: 统一轮询 composable useBackupTask.ts**
action: 新建 `frontend-vite/src/components/backup/composables/useBackupTask.ts`：入参 `taskIdGetter:()=>string|null`、间隔 800ms、终态(`completed`/`completed_with_warnings`/`failed`)停止、404 容忍上限 `MAX_NOT_FOUND=3`(沿 useRestoreProgressPolling 语义)；导出 `{ progress, status, error, result }` 与回调 onCompleted/onFailed；taskId 为空则停止并复位。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 3: 概览四卡 BackupOverviewCards.vue**
action: 新建 `frontend-vite/src/components/backup/BackupOverviewCards.vue`：四卡(上次备份/下次备份/空间占用+进度条/健康度)，状态圆点与数值按 DESIGN.md 令牌；组件仅接收父级注入的 `status` props(由容器用 getStatus 填充)，不自行发请求。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 4: 一键备份 BackupActions.vue**
action: 新建 `frontend-vite/src/components/backup/BackupActions.vue`：全量/增量按钮调 parent 注入的 `onFull`/`onIncremental`(容器内调 triggerFull/triggerIncremental 得 task_id)，任务卡经 useBackupTask 轮询显示进度/阶段/剩余；`busy` 时按钮 disabled 并提供互斥提示。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 5: 定时任务配置 ScheduleConfig.vue**
action: 新建 `frontend-vite/src/components/backup/ScheduleConfig.vue`：启用开关 + 周期(每日/每周/每月/自定义 cron) + 时间，保存调 createSchedule/updateSchedule、删除调 deleteSchedule、立即触发调 parent 传入的 onTrigger；列表数据由父级 listSchedules 注入。字段对齐后端 BackupSchedule(名称/task_type/cron_expr/enabled)。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 6: 路径设置 PathSettings.vue**
action: 新建 `frontend-vite/src/components/backup/PathSettings.vue`：默认/自定义路径切换；自定义路径实时调 validatePath 显示「可写/原因」；保存调 saveSettings；当前路径与可用空间由 props 注入(getSettings)。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 7: 备份记录表格 BackupRecordTable.vue**
action: 新建 `frontend-vite/src/components/backup/BackupRecordTable.vue`：接收 props(records/loading)，类型/状态筛选、关键词搜索、分页 forward 给父级(onPageChange 调 getRecords)；状态用徽章、操作列还原/下载转发。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 8: 还原向导 RestoreWizard.vue**
action: 新建 `frontend-vite/src/components/backup/RestoreWizard.vue`：第1步选备份点(父级注入 serverBackups)→第2步差异预览(restorePlan)→第3步危险确认(输入「确认还原」激活)→第4步执行(asyncRestoreByName 得 task_id→useBackupTask 轮询)→第5步结果/建议；复用既有 RestoreProgressBar 与 RestoreConfirmDialog；遮罩/Esc 不关闭危险层。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 9: BackupView 单视图容器 + 路由**
action: 重写 `frontend-vite/src/views/backup/BackupView.vue` 为单视图六模块容器：页头+概览(OverviewCards)+操作(BackupActions)+两栏(定时 ScheduleConfig / 路径 PathSettings)+记录(BackupRecordTable)+还原向导(RestoreWizard 浮层)；容器负责调用 getStatus/listSchedules/getRecords 及各写入入口并把 taskId 桥接给 useBackupTask；确认 `/backup` 路由与菜单指向本视图。
verify: cd frontend-vite && npm run type-check

- [ ] **Step 10: 集成验收 + 人工评审**
action: 运行完整构建与类型检查；自检六模块组件均被 BackupView 引用、api/backup.ts 新增绑定无未调用残留。
verify:
  - type: shell
    command: cd frontend-vite && npm run type-check
  - type: shell
    command: cd frontend-vite && npm run build
gate: human