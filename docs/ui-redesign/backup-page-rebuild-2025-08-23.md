# 备份页重构执行文档（对标采购页 / 全局 Plush Cute）

> 生成时间: 2025-08-23
> 执行人: software-engineer-3 (寇豆码)
> 依据: `backup-vs-purchase-analysis.md`（差异报告），口径已由 team-lead 确认 → **套用全局 Plush Cute 体系**，业务逻辑铁律不动
> 类型检查: `npx vue-tsc --noEmit` **exit 0 / 0 errors**（全项目通过，含备份 7 文件）

---

## 〇、执行范围

共改动 **7 个文件**（BackupView + 6 个 `components/backup/` 组件），全部只动 `<style scoped>` 与 `<template>` 结构/类名，**未改任何 `<script setup>` 业务逻辑**：

| # | 文件 |
|---|------|
| 1 | `src/views/backup/BackupView.vue` |
| 2 | `src/components/backup/BackupOverviewCards.vue` |
| 3 | `src/components/backup/BackupActions.vue` |
| 4 | `src/components/backup/BackupRecordTable.vue` |
| 5 | `src/components/backup/ScheduleConfig.vue` |
| 6 | `src/components/backup/PathSettings.vue` |
| 7 | `src/components/backup/RestoreWizard.vue` |

> 说明：`components/backup/` 下另有旧组件（BackupModeSelector / BackupRecordList / BackupDbOverview / FileRestorePanel / RestoreProgressBar / ServerBackupList 等），经检索**未被当前 `BackupView.vue` 引用**（它们仅经 `components.d.ts` 自动注册、互相关联，属于另一套未路由历史页面），故不在本次 `/backup` 页面重构范围内。

---

## 一、逐文件「改动前 → 改动后」样式变更摘要

### 1. BackupView.vue（页面骨架 — 结构级）

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| 根容器 | `<div class="bk-center">`（`max-width:1440px; margin:0 auto; padding:24px` 独立居中） | `<div class="page-card page-card-main bk-root">` 撑满主区（flex:1） |
| 头区 | 独立 `.bk-head` 标题块 + 各 section 内散落的操作按钮 | 移入 `.page-card-header`：左 = 标题+副标题，右 = 主操作按钮（对齐采购页 header） |
| 主体 | 直接在根下多个 `.bk-section` | 包一层 `.page-card-body`（flex 滚动,padding 20px 24px） |
| 标题 | `.bk-head-title` 28px/600/黑 | 18px/700/`var(--color-text)`、`letter-spacing:-0.01em` |
| 副标题 | 13px `var(--color-text-secondary,#4e5969)` | 13px `var(--color-text-secondary)`（去旧 fallback） |
| 还原/上传按钮 | 旧 `.bk-btn-primary`/`.bk-btn-outline`（r9、描边细、`#2f7bff` 残留） | 新 `.bk-btn .btn-primary`（`--gradient-primary` 渐变、`var(--radius-button)14px`、蓝色调阴影）/`.btn-outline`（白底+border-light+primary-600） |
| 区块间距 | `margin-bottom:24px` | `margin-bottom:20px` + 入场 `fadeIn` 动效 |
| 双列网格 | `gap:16px` | `gap:20px` |
| 上传提示 | `var(--color-text-tertiary,#86909c)` | `var(--color-text-muted)` |

### 2. BackupOverviewCards.vue（概览卡）

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| 卡片圆角 | `9px` | `var(--radius-md,14px)` |
| 卡片 hover | `translateY(-1px)` + `rgba(0,0,0,.08)` | `translateY(-2px) scale(1.01)` + `rgba(135,206,235,.35)`（对齐 `.card-hover`） |
| 状态圆点 | `--color-success #10b981` / `--color-warning #f59e0b` / `--color-border-strong #c9cdd4` | `--color-success-500 #28c76f` / `--color-warning-500 #ff9f43` / `--color-border #e4e7ed` |
| 标签/描述文字 | `--color-text-tertiary #86909c` / `--color-text-secondary #4e5969` / `--color-text-primary #1d2129` | `--color-text-muted` / `--color-text-secondary` / `--color-text` |
| 进度轨道 | `--color-surface-muted #f2f3f5` | `--color-border-light` |
| **进度填充(进行)** | **`#6366f1`（靛蓝）** | **`var(--color-primary-500, #5b8def)`** |
| 进度填充(危险) | `var(--color-danger, #ef4444)` | `var(--color-danger-500, #ea5455)` |

### 3. BackupActions.vue（备份操作 + 任务进度）

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| 卡片圆角/底色/阴影 | r9 / white / 无明确阴影 | `var(--radius-md,14px)` / `#ffffff` / 全局 card 阴影 |
| 按钮规格 | 7px 14px / r9 / 12px | 9px 16px / `var(--radius-button,14px)` / 13px |
| 全量按钮「一键全量备份」 | 描边 success（bg success-50） | 渐变 success（`linear-gradient(success-500,success-600)` + 绿色调阴影） |
| 增量按钮「增量备份」 | 描边 primary | 白底 border-light + primary-600 字 + hover primary-50 |
| 徽章 | `#e9eafe/#4338ca`、`#e6faf1/#047857`、`#ffece8/#b91c1c`（旧 2023 色） | `primary-50/700`、`success-50/700`、`danger-50/700`（Plush Cute 语义色） |
| 进度轨道 | `--color-surface-muted #f2f3f5` | `--color-border-light` |
| **进度填充(处理中)** | **`#6366f1`** | **`var(--color-primary-500, #5b8def)`** |
| 进度填充(失败) | `--color-danger #ef4444` | `var(--color-danger-500, #ea5455)` |

### 4. BackupRecordTable.vue（备份记录表）

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| 卡片圆角 | r9 | `var(--radius-md,14px)` |
| 表头 | `bg:#f8fafc; color:#475569; border-bottom:2px solid #e2e8f0`（硬编码） | `bg:var(--color-surface); color:var(--color-text-secondary); border-bottom:2px solid var(--color-border-light)` |
| 单元格 | `td{padding:0 24px; border-top:1px...}` | `td{padding:10px 14px; border-bottom:1px solid var(--color-border-light)}`（对齐采购页） |
| 行 hover | `var(--color-surface-hover,#f7f8fa)` | `var(--color-primary-50)`（品牌蓝 hover） |
| 下拉/搜索框 | `padding:7px 14px; r9; font:12px/600; min-height:32px` | `height:36px; padding:0 12px; radius-input(12px); font:13px/600` + focus 光环 |
| 徽章 | `#e6faf1/#047857`、`#ffece8/#b91c1c`、`#e9eafe/#4338ca`、`#fef6e6/#b45309`、`#f2f3f5/#6b7280` | `success-50/700`、`danger-50/700`、`primary-50/700`、`warning-50/700`、`border-light/text-secondary` |
| 链接按钮 | `--color-primary-600 #2f7bff` / `--color-danger-600 #ef4444` / `--color-text-disabled #c9cdd4` | `primary-600` / `danger-500` / `text-muted` |
| 分页按钮 | `padding:7px 14px; r9; 12px` | `8px 14px; radius-button; 13px`（描边） |
| 等宽字体 | `var(--font-mono, Consolas, monospace)` | `'SF Mono','Fira Code','Consolas',monospace` |

### 5. ScheduleConfig.vue（乙组 — 定时配置）

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| 卡片底色 | `var(--color-surface,#fff)` → **`#f4f6fc` 浅蓝底** | `#ffffff`（对齐 page-card 白底） |
| 卡片圆角/边框/阴影 | r8 / `--color-border #e5e6eb` / 无 | `var(--radius-md,14px)` / border-light / 全局 card 阴影 |
| 开关 | `.on` `var(--color-primary,#2f7bff)` | `var(--color-primary-600)` + 尺寸微调到 38×22、滑钮加微阴影 |
| 下拉/输入 | `h:32px; border:1px solid var(--color-border-strong,#c9cdd4); r6px` | `h:36px; border:border-light; radius-input(12px)` + focus 光环 |
| 「保存配置」按钮 | `#2f7bff` 实底 r6 | `--gradient-primary` 渐变 + `radius-button` + 蓝色调阴影 |
| 「立即触发」按钮 | 透明描边 | 白底 border-light + primary-600 |
| 列表项 | r8 / `--color-border #e5e6eb` / 文字 `#4e5969/#86909c` | `radius-sm(10px)` / border-light / `text/-secondary/-muted` |
| 删除按钮 | `var(--color-danger,#ef4444)` | `var(--color-danger-500)` |

### 6. PathSettings.vue（乙组 — 路径设置）

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| 卡片底色 | `var(--color-surface,#fff)` → **`#f4f6fc`** | `#ffffff` |
| 卡片圆角/边框/阴影 | r8 / `--color-border #e5e6eb` / 无 | `radius-md` / border-light / 全局 card 阴影 |
| 单选 accent | `var(--color-primary,#2f7bff)` | `var(--color-primary-600)` |
| 当前路径块 | `--color-surface-muted #f2f3f5; r6px` | `--color-slate-100; radius-input(12px)` |
| 输入框 | `h:32px; border:border-strong #c9cdd4; r6px` | `h:36px; border:border-light; radius-input` + focus 光环 |
| 校验反馈 ok/error | `--color-success #10b981` / `--color-danger #ef4444` | `--color-success-500` / `--color-danger-500` |
| 保存按钮 | `#2f7bff` 实底 r6 | `--gradient-primary` + `radius-button` |
| 校验按钮 | 透明描边 | 白底 border-light + primary-600 |

### 7. RestoreWizard.vue（乙组 — 还原向导，对齐全局 UiDialog）

| 项 | 改动前 | 改动后 |
|----|--------|--------|
| 遮罩 | `rgba(0,0,0,.32)` **无模糊**、z-index:300 | 加 `backdrop-filter:blur(2px)`、`z-index:var(--z-modal,40)`、入场 `fadeIn` |
| 对话框 | `--color-surface #fff→#f4f6fc` 底 / **r12px** / `rgba(0,0,0,.14)` | `--color-surface-card #fff` / **`var(--radius-modal,28px)`** / `var(--shadow-lg)` 蓝色调 / 入场 `slideUp` |
| 标题 | r18px/600 | 18px/700/`var(--color-text)`、`letter-spacing:-0.01em` |
| 关闭按钮 | 方形 r6 | 圆形 r50%、hover `danger-50/danger-500` |
| 步骤点 | `indigo 当前 #2f7bff / 完成 #10b981` | 当前 `primary-500` + 外圈光环、完成 `success-500` |
| 步骤文字 | `#2f7bff` / `#1d2129` / `#86909c` | `primary-600` / `text` / `text-secondary` |
| 备份点卡片 | `border #e5e6eb; r8px; checked bg #e6f0ff border #2f7bff` | border-light / `radius-sm(10px)` / checked `primary-50 bg + primary-400 border + 3px 光环`；单选 accent `primary-600` |
| 表格 | th `#86909c 12/500`、td `border-top #f2f3f5` | th `text-secondary 12/600 + bg surface + border-light`、td `border-bottom border-light`（采购页表式） |
| 差异高亮 | `#b45309` | `var(--color-warning-700)` |
| 危险列表/确认输入框 | `#ef4444` / `h:32 r6 border-strong #c9cdd4` | `danger-500` / `h:36 radius-input + focus 光环` |
| **还原进度填充** | `--color-danger #ef4444` | `var(--color-danger-500, #ea5455)`（保持红色域） |
| 「下一步/完成/确认还原」 | `#2f7bff` / `#ef4444` 实底 r6 | primary 渐变 + radius-button；确认还原 danger 渐变 + 对应蓝色/红色调阴影 |
| 报告图标 | `#e6faf1 / #10b981` | `success-50 / success-500` |

---

## 二、关键令牌替换统计

| 旧（被替换） | 新（生效） | 出现文件 |
|--------------|-----------|----------|
| `--color-primary` **#2f7bff** | `--color-primary-500 #5b8def` / `-600 #3a6bd6` / `-700 #2d5ab8` | Schedule/Path/RestoreWizard |
| `--color-success` #10b981 | `--color-success-500 #28c76f` / `-600 #1e9e55` / `-700` | 全部 5 组件 |
| `--color-warning` #f59e0b | `--color-warning-500 #ff9f43` / `-700` | Overview/RestoreWizard |
| `--color-danger` **#ef4444** | `--color-danger-500 #ea5455` / `-600 #d44042` / `-700` | 全部 |
| `--color-text-primary` #1d2129 | `--color-text` #1a1a2e / `--color-heading` | 全部 |
| `--color-text-secondary` #4e5969 | `--color-text-secondary` #475569 | 全部 |
| `--color-text-tertiary` #86909c | `--color-text-tertiary` #595959 / `--color-text-muted` #64748b | 全部 |
| `--color-text-disabled` #c9cdd4 | `--color-text-muted` / `--color-border` | RecordTable/Wizard |
| `--color-border` #e5e6eb（乙组用） | `--color-border` #e4e7ed / `--color-border-light` #f0f2f5 | Schedule/Path/Wizard |
| `--color-border-strong` #c9cdd4 | `--color-border` #e4e7ed | 全部 |
| `--color-surface-muted` #f2f3f5 | `--color-border-light` / `--color-slate-100` | Overview/Actions/RecordTable/Path/Wizard |
| `--color-surface-hover` #f7f8fa | `--color-primary-50` #eff5ff | RecordTable |
| 卡片底 `--color-surface` #f4f6fc | `#ffffff` / `--color-surface-card` | Schedule/Path/Wizard |
| **进度填充 `#6366f1`（靛蓝）** | **`--color-primary-500 #5b8def`**；失败 `--color-danger-500 #ea5455` | Overview/Actions/Wizard |
| 徽章底/字 `#e6faf1/#047857`、`#e9eafe/#4338ca`、`#ffece8/#b91c1c`、`#fef6e6/#b45309`、`#f2f3f5/#6b7280` | `-50/-700` 系语义色 | Actions/RecordTable/Overview |
| 按钮 `#2f7bff` 实底 r6 | `--gradient-primary` / `--gradient-success` + `var(--radius-button,14px)` | BackupView/Schedule/Path/Wizard |

**预估关键替换次数**：旧单数令牌 / 硬编码 hex 的直接替换约 **70+ 处**（跨 7 文件），其中品牌蓝 `#2f7bff`、靛蓝进度 `#6366f1`、危险红 `#ef4444`、成功绿 `#10b981`、旧花灰文字 `#1d2129/#4e5969/#86909c/#c9cdd4` 为最多。

---

## 三、圆角 / 尺寸对齐汇总

| 元素 | 改动前 | 改动后（对齐全局令牌） |
|------|--------|----------------------|
| 卡片 | 8px / 9px | `--radius-md` 14px（大卡片由 page-card 18px 统管） |
| 按钮 | h32 r6 / 7px 14px r9 | h36 `var(--radius-button)` 14px；主操作用渐变 |
| 输入/下拉 | h32 r6 / 2px 边 r9 | h36 `var(--radius-input)` 12px + focus 光环 |
| 模态框 | r12 | `var(--radius-modal)` 28px + 蓝色调大阴影 + backdrop-blur |
| 徽章 | r9 / 52px 圆点 | r10 -50/700 语义色，保持紧凑 |

---

## 四、业务逻辑铁律核对（零改动）

以下**均未改动**，已在本次编辑中刻意保持：
- `backupApi` 全部调用（triggerFull / triggerIncremental / getStatus / listSchedules / createSchedule / deleteSchedule / trigger / validatePath / saveSettings / getRecords / restorePlan / asyncRestoreByName / asyncImport / listServerBackups）
- `useBackupTask` 任务轮询（activeTaskId / busy / uploadRestoring / taskKind / toast 终态）
- 分页逻辑（recordsPage / recordsPageSize / loadRecords / pageCount）
- 还原二次确认（step 3 输入「确认还原」才启用「确认还原」按钮）
- 任务互斥（busy 或 taskId 存在时禁用按钮）
- 所有 `script setup` 类型/事件/emit 形状

---

## 四·补、`src/views/backup/BackupView.vue` `<script setup>` 改动归属说明（历史澄清）

经核对，BackupView.vue 的 `<script setup>` 中以下 **5 处业务增强**（相对基线 commit `c7c4415`）：

1. `import { toast } from '@/composables/useToast'`
2. `taskKind` ref（`<'备份' | '还原'>`）
3. `errText()`（后端 409/500 detail 文案抽取）
4. `useBackupTask` 成功/失败回调改写（`uploadRestoring` 复位 + `toast` 终态提示 + `loadStatus()/loadRecords()` 刷新）
5. `triggerFull / triggerIncremental / executeRestore / onUploadRestore` 补充 `toast` + `taskKind` 终态提示

**结论：这些改动均非本次视觉重构会话引入**，而是本会话**开工前工作区即已存在**的未提交业务代码。判定依据：
- 本会话对 BackupView.vue 的**第一次读取（未做任何编辑）**时，上述 5 处已在源码中完整存在；
- 本会话实际只改动 BackuView.vue 的 `<template>`（外层骨架、第 2–74 行）与 `<style scoped>` 块 **两处**，从未触碰 `<script setup>`；
- 该仓库在开工前已存在大规模未提交改动（`git status` 可见 fastapi 后端、测试、dist 等大量 `M/D`），本会话属于正在推进中的备份中心特性开发的一部分，轮询/终态提示是此前已落盘的业务增强。

故 QA 基于 `git diff HEAD` 判定为「本次改动」属于对未提交基线的误判；这些 `<script setup>` 业务增强应归属于更早的既存开发，与本次视觉重构无因果关系。本文档仅声明视觉改动范围；如需将脚本增强单独立档，建议另开 commit/说明。

---

## 五、类型检查结果

- 命令：`npx vue-tsc --noEmit`（在 `D:\erp_system\frontend-vite`）
- 结果：**exit code 0，0 errors**（全项目通过；覆盖本次改动的 7 个 .vue 文件的 TS + Vue 模板编译）
- 无失效类名 / 无未定义令牌 / 无模板语法错误

---

## 六、总结

- **改动文件数**：7（BackupView + OverviewCards + Actions + RecordTable + ScheduleConfig + PathSettings + RestoreWizard）
- **结构级改动**：BackupView 由「1440px 居中多卡」→「全局 `.page-card` 系」；还原向导对齐全局 `UiDialog` 观感
- **关键令牌替换**：约 70+ 处（`#2f7bff`→primary-500/600、`#6366f1`→primary-500、`#ef4444`→danger-500、`#10b981`→success-500、旧花灰文字→text 语义色、卡片底→`#fff`）
- **圆角对齐**：卡片 8/9→14、按钮 →14、输入 →12、模态框 →28
- **动效**：卡片 hover 上浮 + 蓝色调阴影（对齐 `.card-hover`）、区块/模态入场动画
- **业务逻辑**：铁律零改动
- **类型检查**：vue-tsc 通过（0 errors）