---
intent: "让 /backup 页面点击备份记录「还原」按钮时直接针对该备份进入还原确认与执行，取消先选备份点的向导步骤，同时保留既有安全校验、明确操作确认与执行进度反馈。"
success_criteria: "记录行「还原」与顶部入口打开同一确认弹窗并自动带出触发备份点；预览失败时禁止执行；执行按钮仅在「确认还原」文本匹配、预览成功、且加密包已填密码时可用；确认后弹窗内展示进度与终态结果报告；执行期间弹窗不可关闭；type-check 与 build 通过；手工回归清单六类流程全部通过。"
risk_level: medium
auto_approve: true
branch: hotl/backup-restore-direct
worktree: false
---

## Steps

- [x] **Step 1: 新建还原确认弹窗的「确认态」**
action: 新建 `frontend-vite/src/components/backup/RestoreConfirmDialog.vue`。props 定义：`open: boolean`、`serverBackups: ServerBackupSummary[]`、`initialFilename: string`、`plan: BackupRestorePlan | null`、`planLoading: boolean`、`task: BackupTaskState | null`、`result: BackupTaskState | null`、`onPlan: (filename: string) => void`、`onExecute: (filename: string, opts: RestoreExecuteOptions) => void`；emit `close`。`ServerBackupSummary` 与 `RestoreExecuteOptions` 两个类型在本文件导出，保持与旧向导同名同形（`ServerBackupSummary` 含 filename/size/created_at；`RestoreExecuteOptions` 含 confirmSensitive/password）。内部状态：`selected`(备份点文件名)、`view: 'form' | 'running' | 'done'`、`confirmText`、`confirmSensitive`、`decryptPassword`。打开逻辑：watch `open` 转 true 时，`selected = initialFilename || serverBackups[0]?.filename || ''`，重置 `confirmText`/`confirmSensitive`/`decryptPassword`，`view = 'form'`，随后调用 `props.onPlan(selected)`。备份点下拉选项 = `serverBackups`，若 `selected` 不在其中则把该备份点补到列表首位（保证记录行触发的备份点一定可选）。切换备份点时重置 `confirmText` 并重新调用 `props.onPlan(新值)`。确认态渲染内容：① 备份点下拉（选项显示文件名、大小、时间）；② 影响范围区——`planLoading` 为真显示「加载中…」，`plan?.success` 为真显示覆盖表数与差异明细表（表名/备份行数/当前行数/差异），`plan` 存在但 `success` 为假显示 `plan.error`；③ 危险提示清单（将覆盖当前数据库全部数据 / 执行期间系统停止写入 / 未备份的新增数据将丢失）；④ `plan?.encrypted` 为真时显示解密密码输入框（type=password，autocomplete=new-password）；⑤ 敏感配置勾选（文案：同时还原敏感配置文件——默认跳过，仅确有需要时勾选）；⑥ 占位符为「输入「确认还原」以继续」的文本输入。底部按钮：左「取消」（emit close）；右「确认还原」，`:disabled` 条件为 `confirmText !== '确认还原' || !selected || planLoading || !plan?.success || (!!plan?.encrypted && !decryptPassword)`。样式处理：把当前 `frontend-vite/src/components/backup/RestoreWizard.vue` 的 scoped 样式块整体复制到新组件，保留遮罩/弹窗/影响范围/差异表/危险清单/输入框/底部按钮相关类（`.rw-overlay`、`.rw-dialog`、`.rw-head`、`.rw-title`、`.rw-icon-btn`、`.rw-body`、`.rw-desc`、`.rw-impact`、`.rw-affected`、`.rw-table-wrap`、`.rw-table`、`.rw-error`、`.rw-danger-list`、`.rw-confirm-input`、`.rw-pw-row`、`.rw-pw-label`、`.rw-sensitive-check`、`.rw-progress-row`、`.rw-progress`、`.rw-progress-fill`、`.rw-fill-processing`、`.rw-fill-danger`、`.rw-pct`、`.rw-stage`、`.rw-report`、`.rw-report-icon`、`.rw-report-title`、`.rw-report-sub`、`.rw-foot`、`.rw-foot-right`、`.rw-btn`、`.rw-btn-primary`、`.rw-btn-danger`、`.mono` 及两个 `@keyframes`），删除步骤条相关规则（`.rw-stepper`、`.rw-step`、`.rw-step-dot`、`.rw-step-label`、`.rw-step-line`）与单选列表相关规则（`.rw-point`、`.rw-point-name`、`.rw-point-meta`、`.rw-empty`）；再新增备份点下拉的样式，令牌沿用现有 `--color-*` 变量与 `.rw-confirm-input` 的输入框写法。保持 `--color-*` 令牌不变，遮罩保留半透明背景 + `backdrop-filter: blur(2px)`，点击遮罩不关闭。
loop: false
verify: cd frontend-vite && npm run type-check

- [x] **Step 2: 为弹窗补上「进度态」与「结果态」**
action: 继续编辑 `frontend-vite/src/components/backup/RestoreConfirmDialog.vue`。① 点击「确认还原」时：`view = 'running'`，并调用 `props.onExecute(selected, { confirmSensitive, password: decryptPassword || undefined })`。② 进度态渲染：进度条（宽度取 `Math.round(task?.progress ?? 0)` 百分比；`task?.status === 'failed'` 用危险色填充、否则用处理中色）、百分比数字、阶段文案（`task?.status === 'failed'` 时显示 `task?.error`，否则显示 `task?.phaseLabel`，两者皆空时回退「准备还原环境…」）、固定说明文案「正在执行还原，此过程不可中断。」。③ 结果态由父级下传的终态快照驱动，而不是 `task`：`watch(() => props.result, (r) => { if (r) { view = 'done' } })`，避免统一轮询在终态复位任务状态导致结果丢失。结果态渲染：成功/失败图标与标题（`result.status === 'failed'` 为失败，`'completed_with_warnings'` 为「还原完成（有警告）」，其余为「还原完成」）、副文案（`result.error` 或「还原流程已结束，请核对校验结果」）、底部「完成」按钮（emit close）。④ 三段互斥渲染：`view === 'form'` 渲染确认态，`'running'` 渲染进度态，`'done'` 渲染结果态。⑤ 执行中锁定：`view === 'running'` 时遮罩点击与右上角关闭按钮均不关闭弹窗（关闭处理函数仅在 `view !== 'running'` 时 emit close）。
loop: false
verify: cd frontend-vite && npm run type-check

- [x] **Step 3: BackupView 接入统一入口并注入终态快照**
action: 修改 `frontend-vite/src/views/backup/BackupView.vue`。① import 由 `@/components/backup/RestoreWizard.vue` 改为 `@/components/backup/RestoreConfirmDialog.vue`，继续导入 `ServerBackupSummary` 类型与 `RestoreExecuteOptions` 类型（若现有代码未用到可只导入用到的）。② 模板中还原弹窗标签同步改名，新增绑定 `:initial-filename="wizardInitialFilename"`、`:plan-loading="planLoading"`、`:result="restoreResult"`、`:on-plan="previewPlan"`，保留 `:open`、`:server-backups`、`:plan`、`:task`、`:on-execute`、`@close`。③ 新增 `const planLoading = ref(false)` 与 `const restoreResult = ref<BackupTaskState | null>(null)`；`BackupTaskState` 类型从 `@/components/backup/composables/useBackupTask` 以 `import type` 引入。④ `previewPlan(filename)` 改为：`planLoading.value = true`；try 分支赋值为 `await backupApi.restorePlan(filename)`，catch 分支赋值为 `{ success: false, filename, error: '预览失败' }`，finally 置 `planLoading.value = false`。⑤ 在 `useBackupTask` 的 `onCompleted` 回调**开头**写入 `restoreResult.value = { ...taskState.value }`，在 `onFailed` 回调**开头**写入同样的快照，之后保持原有的 `busy`/`uploadRestoring`/`activeTaskId` 复位与 toast 逻辑不变；注意 `taskState` 来自同一解构语句，回调为异步执行因此引用安全。⑥ `onRecordRestore(filename)` 改为：`wizardInitialFilename.value = filename; restoreResult.value = null; wizardOpen.value = true`；删除其内部的 `previewPlan(filename)` 调用（预览改由弹窗打开后经 `onPlan` 触发）。⑦ `openWizard()` 改为：`wizardInitialFilename.value = ''; restoreResult.value = null; wizardOpen.value = true`。⑧ 顶部按钮文案由「一键还原向导」改为「还原备份」。不要改动 `onUploadRestore`、下载、删除、备份与调度相关逻辑。
loop: false
verify: cd frontend-vite && npm run type-check

- [x] **Step 4: 移除旧向导组件并同步自动生成的全局声明**
action: ① 删除 `frontend-vite/src/components/backup/RestoreWizard.vue`。② 编辑 `frontend-vite/src/components.d.ts`，把 `RestoreWizard: typeof import('./components/backup/RestoreWizard.vue')['default']` 一行替换为 `RestoreConfirmDialog: typeof import('./components/backup/RestoreConfirmDialog.vue')['default']`（该文件由 unplugin-vue-components 自动生成，构建时会重新生成；手工同步是为了让构建前的 type-check 即可通过）。③ 用检索工具确认 `frontend-vite/src` 下已无任何对 `RestoreWizard` 的引用；`docs/` 下的历史文档引用属于文档漂移，不修改。
loop: false
verify: cd frontend-vite && npm run type-check

- [x] **Step 5: 构建校验**
action: 执行前端生产构建，确认类型检查与打包均通过（`build` 脚本为 `vue-tsc -b && vite build`，会同时重新生成 `components.d.ts`）。构建完成后检查 `git status` 中 `components.d.ts` 是否被自动改写，若被改写则以自动生成结果为准。
loop: false
verify: cd frontend-vite && npm run build

- [ ] **Step 6: 手工回归清单核对（需人工执行）**
action: 由具备权限的人在非生产环境（或明确授权、可被覆盖的环境）按本文档末节「手工回归清单」逐条执行，覆盖全量包 / 增量包 / 加密包 / 损坏包 / 无差异包 / 敏感配置六类还原流程。逐条记录实际结果；任一条不通过即视为本次改造未完成，需回到对应步骤修复后重跑清单。真实还原会覆盖目标数据库，禁止在生产库执行；如确需在生产验证，必须先取得显式授权并确认数据可被覆盖。
loop: false
max_iterations: 1
verify:
  type: human-review
  path: docs/plans/2026-09-24-backup-restore-direct-workflow.md
  check: 手工回归清单 12 条逐条通过，且 Step 1-5 的静态校验（type-check / build）均已通过
gate: human

## 手工回归清单（Step 6 使用）

前置条件：目标环境已部署本次改动；准备至少一份全量包、一份增量包、一份加密包，以及一份损坏/截断的包文件用于失败分支；**不连接生产库**。

| # | 场景 | 操作 | 期望结果 |
|---|------|------|---------|
| 1 | 全量包 · 记录行直接进入 | 在备份记录表点击全量包所在行的「还原」 | 弹窗打开且备份点已预填为该行备份，无需再选；影响范围区显示覆盖表数；未输入确认文本时「确认还原」禁用 |
| 2 | 全量包 · 正常执行 | 输入「确认还原」后点击「确认还原」 | 弹窗切至进度态，进度条与阶段文案推进；终态显示成功结果报告；页面记录与概览刷新 |
| 3 | 增量包还原 | 同上，选择增量类备份 | 与 #2 一致，且差异明细符合该增量包涉及的表范围 |
| 4 | 加密包 · 未填密码 | 选择加密包且不填解密密码 | 「确认还原」保持禁用，并可见解密密码输入框 |
| 5 | 加密包 · 已填密码 | 填写正确解密密码后确认 | 正常入队并执行成功 |
| 6 | 损坏包 | 选择损坏/截断的包 | 影响范围区显示预览失败原因；「确认还原」禁用，无法执行 |
| 7 | 无差异包 | 选择与当前库一致的备份 | 预览成功且差异为 0 / 无差异；仍可正常执行 |
| 8 | 敏感配置 | 勾选「同时还原敏感配置文件」后确认；另跑一次不勾选 | 勾选时敏感配置被覆盖；未勾选时敏感配置保持原样 |
| 9 | 确认文本不匹配 | 输入不完整的「确认」 | 「确认还原」保持禁用 |
| 10 | 执行中锁定 | 进度态下点击遮罩与右上角关闭按钮 | 弹窗均不关闭 |
| 11 | 顶部入口与切换 | 点击页面顶部「还原备份」；随后切换备份点下拉 | 同一弹窗打开，下拉默认为列表首项且可切换；切换后确认文本被清空需重新输入 |
| 12 | 终态结果不丢失 | 任一还原执行至终态 | 弹窗稳定停留在结果报告，不会中途回落为表单态 |
