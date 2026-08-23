# 备份页(/backup) × 采购页(/purchase) 视觉差异报告与重构方案

> 生成时间: 2025-08-23
> 分析人: software-engineer-3 (寇豆码)
> 对标基准: **采购页 `http://192.168.0.95:3000/purchase`**（用户指定的视觉基准）
> 对比对象: 备份页 `http://192.168.0.95:3000/backup`
> 只做分析与方案，**不改代码**。备份页业务逻辑（backupApi / useBackupTask 轮询 / 分页 / 还原确认）保持不变（铁律）。

---

## 〇、核心结论（先给结论）

1. **采购页 = 全局 "Plush Cute" 体系（现行全局风格）。** 采购页 `PurchaseView.vue` 直接复用全局 `.page-card.page-card-main` + `.page-card-header` + `.page-card-body`（定义在 `src/styles/app.css`），面板内用采购页自有的 `.pc-*` 类（`order-panels.scss`），全部落在全局 Plush Cute 设计令牌上（`primary-*` #5b8def 系、`success-*`、圆角令牌 18/24/28px、蓝色调阴影 `rgba(135,206,235,…)`、渐变）。**采购页没有"专属独立风格"，它就是全局体系的样板实现。**

2. **备份页 = 旧风格（两代混用），不是全局 Plush Cute。** 备份页大量使用 **全局令牌表中不存在的旧令牌** `--color-primary`(#2f7bff)、`--color-success`(#10b981)、`--color-warning`(#f59e0b)、`--color-danger`(#ef4444)、`--color-text-primary`(#1d2129)、`--color-text-tertiary`(#86909c)、`--color-border-strong`(#c9cdd4)、`--color-surface-muted`(#f2f3f5)、`--color-text-disabled`(#c9cdd4)、`--color-surface-hover`(#f7f8fa) 等。因为 `app.css` 的新主题**根本没有定义这些单数令牌**，所以它们全部回退到硬编码的旧 hex 值。

3. **因此重构方向是"套用全局 Plush Cute 体系"**（把备份页改成采购页的模样），而不是"复刻某套采购页独占样式"。核心动作 = ① 让备份页复用 `.page-card.page-card-main` 外层骨架；② 把所有旧令牌 `--color-primary/--color-success/…` 换成新令牌 `--color-primary-N/--color-success-N/…`；③ 把圆角 8px/9px/6px 提到采购页的 18px（卡片）与令牌 12/14/24px；④ 把 indigo 进度条 `#6366f1` 与旧徽章色换成 Plush Cute 语义色。

4. **备份页内部还分两代旧风格**，需分别处理：
   - **甲组（较新旧风格）**：`BackupView.vue` / `BackupOverviewCards.vue` / `BackupActions.vue` / `BackupRecordTable.vue` — 圆角 9px、卡片独立、进度条 `#6366f1`（靛蓝）、徽章 `#e6faf1/#047857` 等；但已经用到 `--color-border-light`、`--color-primary-600` 等新令牌（部分值会自动落到新色板上）。
   - **乙组（最旧风格）**：`ScheduleConfig.vue` / `PathSettings.vue` / `RestoreWizard.vue` — 仍用 `#2f7bff`（旧蓝）、`--color-surface`(#f4f6fc) 打浅底、按钮 h=32px 圆角 6px、模态框圆角 12px、无模糊遮罩。

---

## 一、采购页视觉规范总结（完整量化清单）

> 来源：`PurchaseView.vue` + `order-panels.scss` + 全局 `app.css`。采购页 = 全局体系，下表同时列出 `app.css` 的权威令牌。

### 1.1 全局设计令牌（app.css，Plush Cute）— 采购页实际生效的值

| 令牌 | 值 | 用途 |
|------|-----|------|
| `--color-surface` | `#f4f6fc` | 页面背景（浅蓝灰） |
| `--color-surface-card` | `#ffffff` | 卡片背景 |
| `--color-border` | `#e4e7ed` | 强边框 |
| `--color-border-light` | `#f0f2f5` | 弱边框（卡片/分隔线） |
| `--color-text` | `#1a1a2e` | 主文字（深墨蓝） |
| `--color-text-secondary` | `#475569` | 次级文字 |
| `--color-text-muted` | `#64748b` | 弱化文字/占位 |
| `--color-text-tertiary` | `#595959` | 三级文字 |
| `--color-primary-50…900` | `#eff5ff… #1e3d7a`（500=`#5b8def`，600=`#3a6bd6`，700=`#2d5ab8`） | 品牌蓝 |
| `--color-success-50…900` | `#e8f9ef…`（500=`#28c76f`，600=`#1e9e55`） | 成功绿 |
| `--color-warning-50…900` | `#fff3e6…`（500=`#ff9f43`，600=`#e88e2e`） | 警告橙 |
| `--color-danger-50…900` | `#fde8e8…`（500=`#ea5455`，600=`#d44042`） | 危险红 |
| `--color-ocean` / `ocean-deep` / `ocean-text` | `#b0e0e6` / `#87ceeb` / `#02669e` | 产品/海洋强调 |
| `--radius-sm` | `10px` | 小圆角 |
| `--radius-md` | `14px` | 中圆角 |
| `--radius-lg` / `--radius-card` | `24px` | 卡片大圆角 |
| `--radius-xl` / `--radius-modal` | `28px` | 模态框圆角 |
| `--radius-button` | `14px` | 按钮圆角 |
| `--radius-input` | `12px` | 输入框圆角 |
| `--shadow-sm` | `0 2px 8px rgba(176,224,230,.15)` | 蓝色调浅阴影 |
| `--shadow-md` | `0 4px 16px rgba(176,224,230,.22)` | 蓝色调中阴影 |
| `--shadow-lg` | `0 8px 32px rgba(135,206,235,.28)` | 蓝色调深阴影 |
| `--shadow-xl` | `0 12px 48px rgba(135,206,235,.32)` | 最深 |
| `--gradient-primary` | `linear-gradient(135deg,#5b8def 0%,#3a6bd6 100%)` | 主按钮渐变 |
| `--gradient-success` | `linear-gradient(135deg,#3dc97a 0%,#28c76f 100%)` | 成功渐变 |
| `--gradient-card-header` | `linear-gradient(135deg,#f8fafc 0%,#fff 100%)` | 卡片头微渐变 |
| `--gradient-page-title` | `linear-gradient(135deg,#d4f1f4,#b0e0e6 50%,#87ceeb)` | 页面标题渐变 |
| `--font-sans` | `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', Roboto, sans-serif` | 正文字体栈 |
| `--font-mono` | `'Courier New', monospace`（采购页局部用 `'SF Mono','Fira Code','Consolas'`） | 等宽 |

### 1.2 采购页骨架（页面级）

| 元素 | 取值 |
|------|------|
| 根容器 `.pc-container` | `width:100%; height:100%; padding:0; display:flex; flex-direction:column; box-sizing:border-box`（撑满主区，**无居中、无 max-width**） |
| 主卡片 `.page-card.page-card-main` | `background:#fff; border-radius:18px; border:1px solid var(--color-border-light); box-shadow:0 1px 3px rgba(0,0,0,.04),0 4px 12px rgba(0,0,0,.06); flex:1; display:flex; flex-direction:column; min-height:0; overflow:hidden; transition:box-shadow .4s cubic-bezier(.4,0,.2,1),transform .4s` |
| 卡片 hover | `box-shadow:0 4px 12px rgba(0,0,0,.06); transform:translateY(-2px)` |
| 卡片头 `.page-card-header` | `display:flex; justify-content:space-between; align-items:center; padding:14px 24px; border-bottom:1px solid var(--color-border-light,#f1f5f9); background:rgba(255,255,255,.95); gap:12px` |
| 卡片体 `.page-card-body` | `flex:1; min-height:0; overflow-y:auto; padding:20px 24px; scrollbar-gutter:stable` |
| 响应式 | `≤768px` 时 header 换行、`padding:12px 16px; gap:10px` |

### 1.3 采购页组件规范（页内）

| 组件 | 类 | 取值 |
|------|-----|------|
| Tab 容器 | `.pc-tab-group` | `inline-flex; gap:4px; padding:4px; border-radius:12px; background:#fff; border:1px solid var(--color-border-light); box-shadow:0 1px 3px rgba(0,0,0,.04),0 4px 12px rgba(0,0,0,.06)` |
| Tab 项 | `.pc-tab-btn` | `padding:8px 14px; border-radius:9px; font:13px/600; color:var(--color-text-secondary); background:transparent; transition:.3s` |
| Tab hover | | `background:var(--color-primary-50); color:var(--color-primary-600); box-shadow:0 4px 12px rgba(0,0,0,.08); transform:translateY(-1px)` |
| Tab 激活 | `.pc-tab-btn.active` | `background:linear-gradient(135deg,var(--color-primary-50),var(--color-primary-100)); color:var(--color-primary-700); box-shadow:0 4px 12px rgba(0,0,0,.08),0 2px 8px rgba(91,141,239,.2); transform:translateY(-1px)` |
| Tab 角标 | `.pc-tab-badge` | `min-width:18px;height:18px;padding:0 5px;background:var(--color-danger-500, #ea5455);color:#fff;font:10px/700;border-radius:9px` |
| 按钮 | `.pc-btn` | `padding:7px 14px;border:2px solid var(--color-border-light);border-radius:9px;font:12px/600;background:#fff` |
| 按钮(小) | `.pc-btn-sm` | `padding:5px 10px;font-size:11px` |
| 按钮(成功) | `.pc-btn-success` | `color:var(--color-success-600,#1e9e55);border-color:var(--color-success-200);background:var(--color-success-50)` |
| 按钮(成功 hover) | | `background:var(--color-success-500);color:#fff;border-color:transparent` |
| 区块标题 | `.pc-section-title` | `font:14px/700;color:var(--color-text);icon:var(--color-primary-500)` |
| 表格容器 | `.pc-table-wrap` | `padding:0 0 16px;overflow-x:auto` |
| 表头 | `.pc-table-wrap thead th` | `padding:10px 14px;background:var(--color-surface,#f8fafc);font:12px/600;text-transform:uppercase;letter-spacing:.05em;color:var(--color-text-secondary);border-bottom:2px solid var(--color-border-light);white-space:nowrap;text-align:left` |
| 单元格 | `.pc-table-wrap tbody td` | `padding:10px 14px;border-bottom:1px solid var(--color-border-light,#f1f5f9);color:var(--color-text);vertical-align:middle;cursor:pointer` |
| 行 hover | `.pc-table-wrap tbody tr:hover td` | `background:var(--color-primary-50)` |
| 行选中 | `.pc-row-selected td` | `background:rgba(0,148,191,.06)` |
| SKU 徽标 | `.pc-sku-badge` | `padding:1px 6px;border-radius:4px;background:var(--color-primary-100,#d6e4ff);color:var(--color-primary-700,#1d4ed8→实际 #2d5ab8);font:10px/700;height:18px;min-width:48px` |
| 自定义标签 | `.pc-sku-tag--custom` | `background:var(--color-warning-50,#fff3e6);color:var(--color-warning-600,#e88e2e)` |
| 等宽码 | `.pc-barcode-text` | `font-family:'SF Mono','Fira Code','Consolas',monospace;font-size:12px;color:var(--color-text-muted,#94a3b8);letter-spacing:.04em` |
| 空态 | `.pc-empty-state` | `flex column; gap:10px; padding:40px 20px; color:var(--color-text-muted); font:14px` |
| 加载态 | `.pc-loading-state` | `color:var(--color-primary-500); font:14px` |
| 拉取进度条 | `.pc-fetching-bar/.pc-fetching-progress` | `h:2px;bg:var(--color-primary-100);fill:w30% var(--color-primary-500);slide 1s infinite` |
| 模态框 | 全局 `UiDialog.vue` | 遮罩 `bg-black/50 backdrop-blur-sm animate-[fadeIn_.2s]`;内容 `rounded-2xl(=24px,名义 28px)/bg-surface-card #fff/shadow-lg/animate-slide-up`;头 `px-6 py-5 border-b border-light` 标题 `text-lg font-semibold text-text`;关 `w-8 h-8 rounded-full hover:bg-danger-50 hover:text-danger-500`;体 `p-6 overflow-y-auto`;脚 `px-6 py-4 border-t border-light flex justify-end gap-2` |

---

## 二、差异对比表：备份页（当前） vs 采购页（Plush Cute）

> 备份页 = 甲组（BackupView/Overview/Actions/RecordTable）+ 乙组（ScheduleConfig/PathSettings/RestoreWizard）。未特别说明即指备份页当前值。

| # | 元素 | 采购页取值 | 备份页当前取值 | 差异说明 |
|---|------|-----------|----------------|----------|
| D1 | **页面骨架/外层** | `.pc-container` 100%×100%、flex column、`padding:0`；外层 `.page-card.page-card-main`（r18px、白、蓝色阴影） | `.bk-center{max-width:1440px;margin:0 auto;padding:24px}` 独立卡片堆叠 | **结构级**：采购页是"一张大卡片撑满 + 内部分区"；备份页是"多张独立小卡片居中堆叠"。最显著差异 |
| D2 | **页面标题** | 采购页在 `.page-card-header` 内放 tab / 工具栏，无 28px 孤立大标题 | `.bk-head-title{font-size:28px;font-weight:600;line-height:36px}` 纯黑 | 旧标题范式；采购页用 header 区 + 16px/700 区块标题 |
| D3 | **卡片圆角** | `18px`（`.page-card`）/ 令牌 `radius-card:24px` | `9px`（甲组 boc/ba/brt）、`8px`（乙组 sc/ps） | 备份页圆角偏小（旧风格），采购页圆角大、柔和 |
| D4 | **卡片背景** | `rgba/#fff` 白底 | 乙组 `.sc-card/.ps-card` 用 `background:var(--color-surface,#fff)` → 实际 `#f4f6fc` 浅蓝底 | 乙组卡片非纯白，与采购页白卡不一致 |
| D5 | **进度条填充色** | 拉取条 `var(--color-primary-500, #5b8def)`；成功渐变 `--gradient-success` | 甲组 `.boc-fill-primary` / `.ba-fill-processing` = **`#6366f1`（靛蓝）** | **色板代差**：靛蓝不在 Plush Cute 语义色内 |
| D6 | **成功/危险实色令牌** | `--color-success-500 #28c76f` / `--color-danger-500 #ea5455` | `.boc-fill-danger`/`.rw-fill-danger` = `var(--color-danger, #ef4444)`（旧红） | 备份页 `--color-danger` 未定义→回退旧红 |
| D7 | **徽章(状态)背景/文字** | 语义 `--color-*-50/600` 系（r16px 胶囊）：success `#e8f9ef/#1e9e55`、primary `#eff5ff/#2d5ab8`、warning `#fff3e6/#e88e2e`、danger `#fde8e8/#d44042` | 甲组 `.ba-badge-success #e6faf1/#047857`、`.ba-badge-processing #e9eafe/#4338ca`、`.ba-badge-danger #ffece8/#b91c1c`、`.brt-badge-*` 同；乙组 stepper 用 `--color-success #10b981` | 备份徽章是旧 2023 系(靛蓝/薄荷/脏粉)，非 Plush Cute 语义色 |
| D8 | **徽章圆角/尺寸** | `r16px`、`padding:5px 12px`、`font:12px/600`（采购 coq-badge）/ 或 r9px 小角标 | 甲组 r9px、`min-w18 h18`、`font:10px/700`；乙组 r48px 圆点 | 采购页状态徽章更"胶囊+宽松"，备份页偏小 |
| D9 | **品牌主色(按钮)** | `--color-primary-500/600/700`（#5b8def/#3a6bd6/#2d5ab8） | 乙组 `var(--color-primary, #2f7bff)` 旧蓝；甲组 `--color-primary-600` 已自动落新值 | 乙组主按钮是旧蓝 #2f7bff，与采购页 #3a6bd6/#5b8def 不一致 |
| D10 | **按钮规格** | `.pc-btn`：`padding:7px 14px;border:2px solid var(--color-border-light);border-radius:9px;font:12px/600` | 乙组 `.sc-btn/.ps-btn/.rw-btn`：`height:32px;padding:0 16px;border-radius:6px;font:14px;border:1px solid`（主按钮实底 #2f7bff） | 乙组按钮是"高32/圆角6/实底蓝"旧范式，与采购页"细边框描边+小圆角"不一致 |
| D11 | **文字颜色令牌** | `--color-text #1a1a2e`、`--color-text-secondary #475569`、`--color-text-muted #64748b`、`--color-text-tertiary #595959` | 甲/乙组大量 `var(--color-text-primary,#1d2129)`、`var(--color-text-secondary,#4e5969)`、`var(--color-text-tertiary,#86909c)`、`var(--color-text-disabled,#c9cdd4)` | 旧字色令牌未定义→回退旧 hex，与采购页字色不一致 |
| D12 | **边框令牌** | `--color-border #e4e7ed`、`--color-border-light #f0f2f5` | 乙组 `var(--color-border-strong,#c9cdd4)`、`var(--color-border,#e5e6eb)`；甲组 `var(--color-border-light,#e2e8f0)` | 部分旧边框令牌未定义→回退旧值 |
| D13 | **表格表头** | `padding:10px 14px;bg:var(--color-surface);font:12px/600;uppercase;letter-spacing:.05em;color:var(--color-text-secondary);border-bottom:2px solid var(--color-border-light)` | `.brt-table th`：`padding:10px 14px;bg:#f8fafc;color:#475569;font:12px/600;uppercase;letter-spacing:.05em;border-bottom:2px solid #e2e8f0;text-align:left` | 结构接近，仅色令牌硬编码旧值；**td padding 差异大**（见 D14） |
| D14 | **表格单元格** | `padding:10px 14px;border-bottom:1px solid var(--color-border-light);text-align:left` | `.brt-table td{padding:0 24px;border-top:1px solid var(--color-border-light)}` | 备份格 td 用 `0 24px` 且 `border-top`，与采购页不一致 |
| D15 | **表格行 hover** | `background:var(--color-primary-50, #eff5ff)` | `.brt-table tbody tr:hover{background:var(--color-surface-hover,#f7f8fa)}` | 备份页浅灰 hover，采购页品牌蓝 hover |
| D16 | **表单控件** | 令牌 `--radius-input:12px`、边框 `--color-border-light` | 乙组 `.sc-input/.ps-input/.rw-confirm-input/.sc-select`：`height:32px;border:1px solid var(--color-border-strong,#c9cdd4);border-radius:6px;font-size:14px`；甲组 `.brt-select`：`border:2px solid var(--color-border-light);border-radius:9px;font:12px/600` | 乙组输入旧范式(r6/边框强/14px)；甲组输入是描边式。统一到 `--radius-input` |
| D17 | **开关** | `--color-primary-*` / `--radius-input` 风格 | `.sc-switch{36×20;r999}`、`.sc-switch.on{background:var(--color-primary,#2f7bff)}` | 旧蓝开关，未用新令牌 |
| D18 | **单选框 accent** | `accent-color:var(--color-primary-600)` | `.ps-radio input{accent-color:var(--color-primary,#2f7bff)}` | 旧蓝 |
| D19 | **路径块** | `--radius-sm(10px)` / `--color-surface` | `.ps-path{background:var(--color-surface-muted,#f2f3f5);border-radius:6px}` | 旧浅灰底(r6)，非令牌 |
| D20 | **模态框(还原向导)** | 全局 `UiDialog`：遮罩 `bg-black/50 backdrop-blur-sm`、内容 `rounded-2xl(24px)/bg-surface-card #fff/shadow-lg/animate-slide-up` | `.rw-dialog`：`max-width:720px;background:var(--color-surface,#f4f6fc);border-radius:12px;box-shadow:0 16px 40px rgba(0,0,0,.14)`；遮罩 `rgba(0,0,0,.32)` **无模糊** | 模态圆角(12 vs 28)、背景(浅蓝 vs 白)、遮罩(无模糊 vs blob)、入场动画差异大 |
| D21 | **步骤条(向导)** | 采购页无同名，但用语义 token | `.rw-step-dot` 当前态 `color-primary #2f7bff`、完成态 `--color-success #10b981`；`.rw-go...` | 旧蓝/旧绿 stepper |
| D22 | **按钮区/工具栏** | 采购页 header `padding:14px 24px`、区块 toolbar `padding 16px 24px 12px` | `.brt-toolbar{padding:24px}`、`.bk-actions-row{gap:12px;margin-bottom:8px}` | 内边距口径不一致 |
| D23 | **选中态** | `.pc-row-selected` `rgba(0,148,191,.06)` | `.rw-point.checked{background:#e6f0ff}` | 采购页用半透明品牌蓝，备份页硬编码浅蓝 #e6f0ff |
| D24 | **等宽字体** | `'SF Mono','Fira Code','Consolas',monospace`（采购 `.pc-barcode-text`） | `var(--font-mono, Consolas, monospace)` | 采购页更专业等宽栈，备份页回退 Consolas |
| D25 | **卡片内边距** | `.page-card-body` body `padding:20px 24px`；单卡 `padding:24px` | 乙组卡 `padding:20px`；甲组卡 `padding:24px` | 基本一致，乙组略小 |

**差异项合计：D1–D25，共 25 项差异**（其中 D1 为结构级，D3–D9/D20 为观感最大项）。

---

## 三、重构方案（对齐采购页 / Plush Cute）

> 铁律：**不改业务逻辑**。所有改动仅限 `<style scoped>` 与模板的 class/结构（结构改动仅限外层骨架，不触碰 `backupApi`、`useBackupTask`、分页、还原确认事件）。

### P0 — 骨架与全局身份（决定性，观感提升最大）

| 条目 | 当前值 | 目标值(采购页) | 改动文件 |
|------|--------|----------------|----------|
| P0-1 外层骨架 | `.bk-center{max-width:1440px;margin:0 auto;padding:24px}` | 外套 `.page-card.page-card-main` + `.page-card-header` + `.page-card-body`；最外层容器 `width:100%;height:100%;padding:0;display:flex;flex-direction:column` | `BackupView.vue` |
| P0-2 标题/头部 | `.bk-head` 28px/600 黑标题 | 移入 `.page-card-header`：标题 16px/700 `var(--color-text)`（参考 `coq-title`）+ 副标题 `var(--color-text-secondary)` + 右侧操作按钮 | `BackupView.vue` |
| P0-3 卡片圆角 | 甲组 9px / 乙组 8px | 全部 `border-radius:18px`（对齐 `.page-card`）；或统一用 `var(--radius-card,24px)` | `BackupOverviewCards.vue`、`BackupActions.vue`、`BackupRecordTable.vue`、`ScheduleConfig.vue`、`PathSettings.vue` |
| P0-4 卡片背景 | 乙组 `var(--color-surface,#f4f6fc)` | `background:#fff`（`--color-surface-card`） | `ScheduleConfig.vue`、`PathSettings.vue`、`RestoreWizard.vue` |
| P0-5 卡片阴影 | 甲组 `0 1px 3px/.04,0 4px 12px/.06` / 乙组无 | 统一 `.page-card` 阴影 `0 1px 3px rgba(0,0,0,.04),0 4px 12px rgba(0,0,0,.06)`（甲组已近似，乙组补上）；hover `translateY(-2px)` | 5 个卡片组件 |

### P1 — 令牌与语义色统一（色板对齐）

| 条目 | 当前值 | 目标值(采购页) | 改动文件 |
|------|--------|----------------|----------|
| P1-1 进度填充 | `#6366f1`（靛蓝） | `var(--color-primary-500, #5b8def)`；成功态 `var(--gradient-success)` | `BackupOverviewCards.vue`（`.boc-fill-primary`）、`BackupActions.vue`（`.ba-fill-processing`） |
| P1-2 危险实色 | `var(--color-danger,#ef4444)` | `var(--color-danger-500, #ea5455)` | 3 个组件全部危险填充/文字 |
| P1-3 品牌主色 | `var(--color-primary,#2f7bff)` | `var(--color-primary-600, #3a6bd6)`（按钮/选中）；hover `var(--color-primary-500, #5b8def)` | `ScheduleConfig.vue`、`PathSettings.vue`、`RestoreWizard.vue` |
| P1-4 成功实色 | `var(--color-success,#10b981)` | `var(--color-success-500, #28c76f)`；浅底 `--color-success-50` | `ScheduleConfig.vue`、`PathSettings.vue`、`RestoreWizard.vue` |
| P1-5 徽章语义色 | `#e6faf1/#047857`、`#e9eafe/#4338ca`、`#ffece8/#b91c1c`、`#fef6e6/#b45309`、`#f2f3f5/#6b7280` | `--color-success-50/600`、`--color-primary-50/700`、`--color-danger-50/600`、`--color-warning-50/600`、`--color-border-light/text-secondary` | `BackupActions.vue`（`.ba-badge-*`）、`BackupRecordTable.vue`（`.brt-badge-*`）、`RestoreWizard.vue`（stepper） |
| P1-6 文字色 | `--color-text-primary/#1d2129`、`--color-text-secondary/#4e5969`、`--color-text-tertiary/#86909c` | `--color-text #1a1a2e`、`--color-text-secondary #475569`、`--color-text-muted #64748b`、`--color-text-tertiary #595959` | 全部 6+ 备份组件（批量替换 fallback） |
| P1-7 边框 | `--color-border-strong/#c9cdd4`、`--color-border/#e5e6eb`、`--color-border-light/#e2e8f0` | `--color-border #e4e7ed`、`--color-border-light #f0f2f5` | 全部备份组件 |
| P1-8 表格 hover | `#f7f8fa` | `var(--color-primary-50, #eff5ff)` | `BackupRecordTable.vue` |
| P1-9 表格单元格 | `td{padding:0 24px;border-top}` | `td{padding:10px 14px;border-bottom:1px solid var(--color-border-light)}`；表头 `bg:var(--color-surface);color:var(--color-text-secondary)` | `BackupRecordTable.vue`、`RestoreWizard.vue`（`.rw-table`） |

### P2 — 组件细节与动效（打磨）

| 条目 | 当前值 | 目标值(采购页) | 改动文件 |
|------|--------|----------------|----------|
| P2-1 还原模态框 | `.rw-dialog` r12px/`#f4f6fc`/`rgba(0,0,0,.14)`/无模糊遮罩 | 改用全局 `UiDialog.vue`（rounded-2xl、bg-surface-card、backdrop-blur-sm、animate-slide-up）；或最小改动：r24px、bg `#fff`、shadow `var(--shadow-lg)`、遮罩加 `backdrop-filter:blur(2px)` | `RestoreWizard.vue` |
| P2-2 输入/下拉 | 乙组 `h:32px;border:1px solid var(--color-border-strong);r6px;font14`；甲组 `border:2px solid var(--color-border-light);r9px;font12/600` | 统一 `--radius-input(12px)`、边框 `var(--color-border-light)`、`font-size:14px`、hover/focus `border-color:var(--color-primary-300)` | `ScheduleConfig.vue`、`PathSettings.vue`、`RestoreWizard.vue`、`BackupRecordTable.vue` |
| P2-3 按钮统一 | 甲组 ".pc-btn 式"/乙组 "h32 r6 实底蓝" | 统一 `.pc-btn` 规格（`padding:7px 14px;border:2px solid var(--color-border-light);r9px;font:12px/600`），语义色用 `--color-success-*`（全量）、`--color-primary-*`（增量/还原） | 全部备份组件 |
| P2-4 选中态 | `.rw-point.checked{background:#e6f0ff}` | `background:var(--color-primary-50)` + `border-color:var(--color-primary-400)` | `RestoreWizard.vue` |
| P2-5 路径块 | `.ps-path` `#f2f3f5`/r6 | `var(--color-surface)`/`var(--radius-sm,10px)` | `PathSettings.vue` |
| P2-6 等宽字体 | `Consolas,monospace` | `'SF Mono','Fira Code','Consolas',monospace` | 各 `.mono` |
| P2-7 开关/单选 | `var(--color-primary,#2f7bff)` | `var(--color-primary-600)` | `ScheduleConfig.vue`、`PathSettings.vue` |
| P2-8 hover/动效 | 卡片仅 `translateY(-1px)`；按钮仅色变 | 采购式 `transition:.3s ease` + hover `translateY(-1px)`/`box-shadow`；或复用全局 `.card-hover` | 全部卡片组件 |

---

## 四、结论与文件清单

**采购页定位**：采购页就是**全局 Plush Cute 体系**的样板实现（`.page-card` + `primary-*`/`success-*` 令牌 + 大圆角 + 蓝色调阴影 + 渐变）。它没有独立于全局体系的专属风格。

**备份页定位**：备份页是**旧风格**（非 Plush Cute），且混用两代旧令牌（甲组接近新令牌但有 indigo `#6366f1` 与旧徽章色；乙组直接用旧蓝 `#2f7bff`/旧表面色）。

**重构核心动作（4 条）**：
1. 备份页套上 `.page-card.page-card-main/.page-card-header/.page-card-body` 外层骨架（改 `BackupView.vue`）。
2. 全部卡片圆角 8/9px → 18px，背景统一纯白（乙组去掉 `#f4f6fc` 底）。
3. 把所有旧令牌 `--color-primary/--color-success/--color-danger/--color-warning/--color-text-*/--color-border-*`（单数、旧 hex）批量替换为 Plush Cute 新令牌（`-50…-900` 系）。
4. 进度条 `#6366f1` → `primary-500`；徽章旧 2023 色 → Plush Cute `-50/-600` 语义色；还原模态框对齐全局 `UiDialog`。

**涉及文件清单（8 个 Vue 组件）**：
| 文件 | 改动重点 |
|------|----------|
| `src/views/backup/BackupView.vue` | 外层骨架 `.bk-center` → `.page-card` 系；标题/头部移入 `.page-card-header` |
| `src/components/backup/BackupOverviewCards.vue` | 卡 r9→18、进度 `#6366f1`→`primary-500`、语义色 |
| `src/components/backup/BackupActions.vue` | 卡/徽章/进度/按钮令牌统一 |
| `src/components/backup/BackupRecordTable.vue` | 表头 td、hover、徽章、输入框对齐 |
| `src/components/backup/ScheduleConfig.vue` | 卡 r8/底、`#2f7bff`→`primary-600`、输入/开关 |
| `src/components/backup/PathSettings.vue` | 卡底/`#2f7bff`、路径块、单选 accent |
| `src/components/backup/RestoreWizard.vue` | 模态框对齐 UiDialog、stepper/选中/按钮语义色 |
| （对照）`src/views/purchase/PurchaseView.vue` + `order-panels.scss` + `src/styles/app.css` | 仅作基准，不修改 |

> 注 1：不改 `app.css`（全局体系本身是基准，无需动）。
> 注 2：`src/components/backup/composables/*`、`src/views/backup/composables/*` 纯业务，**零改动**。
> 注 3：`BackupRecordList.vue / BackupSaveResultCard.vue / BackupDbOverview.vue / RestoreProgressBar.vue` 若仍在用，一并按 P1-6/7、P0-3 套令牌即可。

**验收口径**：改完后备份页应与采购页同属一套观感——单张大 `page-card` 骨架、18px 圆角、`primary-500/600/700` 品牌蓝、`success-50/600` 等语义徽章、`primary-50` 行 hover、蓝色调阴影、无靛蓝/无 `#2f7bff`/无 `#f4f6fc` 卡片底。