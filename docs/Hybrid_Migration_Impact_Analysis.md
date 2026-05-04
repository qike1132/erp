# Shadcn-Vue + PrimeVue Unstyled 混合方案：提升量与影响分析

---

## 一、核心结论

| 问题 | 回答 |
|------|------|
| 比现在能提升多少？ | **显著提升**，尤其在 ERP 核心场景 (表格/表单/选择器)，减少约 60% 的重复自建代码 |
| 迁移后交互会变化吗？ | **基础交互零变化** (Shadcn-Vue 同源 Reka UI)，**新增交互更丰富** (PrimeVue 补齐) |
| UI 效果/界面会变化吗？ | **"Plush Cute" 风格完全保留**，所有视觉特征 (圆角/阴影/渐变/海洋色) 原样迁移 |

---

## 二、提升量详细分析

### 2.1 当前痛点与混合方案的解决程度

#### 痛点 1: 表格 — UiTable 是空壳，每个视图自建

**现状** (基于代码审查):
- `UiTable.vue` 仅 15 行，实质是 `<div><table><slot /></table></div>`
- **8 个视图**各自手写 `<table>` HTML + CSS + 行为逻辑
- 行选择: `PendingOrdersPanel`、`ActiveOrdersPanel` 各自手动实现 `selectedIds`/`toggleAll`
- 排序: `PurchasePlanView` 手动实现 `toggleSkuSort()`
- 分页: `ActiveOrdersPanel`、`CompletedOrdersPanel` 各自手写 `visiblePages`
- 内联编辑: `SummaryModal` 手写 `<input type="number">` 嵌入 `<td>`
- 空状态: 每个表格视图手动 `v-if="data.length === 0"` + `<UiEmpty>`

**混合方案 (PrimeVue DataTable)**:

| 功能 | 当前 (自建) | 迁移后 (PrimeVue DataTable) | 代码量变化 |
|------|------------|---------------------------|-----------|
| 行选择 (checkbox) | 每个视图 ~30 行 | `<Column selectionMode="multiple">` 1 行 | **-90%** |
| 列排序 | 每个视图 ~20 行 | `<Column sortable>` 1 行 | **-95%** |
| 分页 | 每个视图 ~25 行 | `<DataTable paginator :rows="10">` 1 行 | **-96%** |
| 内联编辑 | `SummaryModal` ~40 行 | `<Column editor>` + InputTemplate | **-70%** |
| 空状态集成 | 每个视图 ~5 行 | `<template #empty>` 1 行 | **-80%** |
| 虚拟滚动 | 不可能实现 | `<DataTable virtualScroll>` 1 行 | 从不可能→**零成本** |
| 列固定/冻结 | 不可能实现 | `<Column frozen>` 1 行 | 从不可能→**零成本** |
| Excel 导出 | 不可能实现 | `DataTable.exportCSV()` 1 行 | 从不可能→**零成本** |

**提升估算**: 8 个视图的表格相关代码约 **800-1000 行**，迁移后可压缩至 **150-200 行**，且获得虚拟滚动、列固定、导出等当前不可能实现的功能。

---

#### 痛点 2: 选择器 — UiSelect 功能严重不足

**现状**:
- 仅支持单选、本地过滤、`{ value: string, label: string }` 简单选项
- **产品搜索完全绕过 UiSelect** — `StockOutTab` 自建 `autocomplete-dropdown` (20+ 行 HTML + 30 行逻辑)，`CreateShipmentPlanDialog` 自建 `csd-suggest-list` (24 行 HTML + 40 行逻辑)
- 无法显示选项附加信息 (产品搜索需显示条码+库存，UiSelect 做不到)
- 无远程搜索、无分组选项、无多选

**混合方案 (Shadcn-Vue Combobox + PrimeVue Select)**:

| 功能 | 当前 | 迁移后 | 提升 |
|------|------|--------|------|
| 简单选择 | UiSelect (Reka Combobox) | Shadcn-Vue Combobox (同源 Reka UI) | 零差异，代码更规范 |
| 产品搜索 (远程) | 自建 autocomplete (~50 行/处) | PrimeVue AutoComplete + PT 样式 | **-80% 代码量** |
| 选项显示多字段 | 不可能 | PrimeVue AutoComplete 自定义 item template | 从不可能→**零成本** |
| 级联选择 | 不可能 | PrimeVue CascadeSelect | 从不可能→**零成本** |
| 树形选择 | 不可能 | PrimeVue TreeSelect | 从不可能→**零成本** |
| 多选 | 不可能 | PrimeVue MultiSelect | 从不可能→**零成本** |

**提升估算**: 消除 2 处自建 autocomplete (~100 行)，并解锁 5 种当前不可能实现的选择器模式。

---

#### 痛点 3: 日期选择 — 原生浏览器日期选择器

**现状**:
- `UiDatePicker` 本质是 `<input type="date">` + 图标
- 跨浏览器外观不一致 (Chrome/Edge/Firefox 各不同)
- 无日期范围选择 — 每次需要范围时用 2 个独立 UiDatePicker
- 无禁用日期、无时间选择、无日历弹窗

**混合方案 (PrimeVue DatePicker)**:

| 功能 | 当前 | 迁移后 |
|------|------|--------|
| 日期选择 | 原生浏览器控件 | **自定义日历弹窗** (统一跨浏览器) |
| 日期范围 | 2 个独立 UiDatePicker | **1 个 DatePicker selectionMode="range"** |
| 时间选择 | 不可能 | **DatePicker showTime** |
| 禁用日期 | 不可能 | **DatePicker disabledDates** |
| 外观一致性 | 各浏览器不同 | **完全统一** (PT + Tailwind 控制) |

**提升估算**: 消除约 6 处双日期选择器的冗余代码，统一外观。

---

#### 痛点 4: 表单验证 — 全手动

**现状**:
- 每个 Dialog 内的表单都用 `errorMsg` ref + `v-if` 条件渲染手动验证
- 无统一的表单规则定义，验证逻辑分散在各个视图中
- 无实时校验反馈 (blur 时校验)，只在提交时一次性校验

**混合方案 (PrimeVue Form + Zod)**:

| 功能 | 当前 | 迁移后 |
|------|------|--------|
| 验证规则定义 | 分散在各视图中 (~15 行/表单) | **Zod schema 集中定义** (~5 行) |
| 错误信息展示 | 手动 `v-if="errorMsg"` | **自动绑定到 Field** |
| 实时校验 | 无 | **blur 时自动校验** |
| 跨字段校验 | 手动 if-else | **Zod refine** |

---

#### 痛点 5: 抽屉 — 完全自建

**现状**:
- `PlanDetailDrawer` 是 468 行纯手写 (自定义 CSS + Transition)
- 无 `UiDrawer` 组件

**混合方案 (PrimeVue Drawer/Sidebar)**:
- `<Drawer>` 开箱即用，PT 样式控制外观
- 从 468 行自定义 → ~20 行配置式

---

### 2.2 提升量总结

| 维度 | 当前问题 | 混合方案提升 | 量化指标 |
|------|---------|-------------|---------|
| 表格功能 | 8 个视图各自手写 | DataTable 统一实现 | **-75% 表格代码量**，+5 项不可能功能 |
| 选择器功能 | 2 处自建 autocomplete，5 种模式不可用 | AutoComplete/CascadeSelect/TreeSelect | **-80% 搜索组件代码**，+5 种选择模式 |
| 日期选择 | 原生控件，跨浏览器不一致 | 自定义日历+范围选择 | **统一外观**，+4 项功能 |
| 表单验证 | 全手动，无实时校验 | Form + Zod 自动验证 | **-60% 验证代码**，+实时校验 |
| 抽屉 | 468 行自建 | Drawer 组件 | **-95% 代码量** |
| 新组件获取 | 每新增一种需从零开发 | 90+ 组件库直接使用 | **从数天→数小时** |
| **总代码量** | ~1200 行自建 UI 代码可被替代 | | **-60% ~ -70%** |

---

## 三、迁移后交互是否变化

### 3.1 基础交互组件 — 零变化

以下组件使用 **Shadcn-Vue** 替换 (底层同为 Reka UI)，交互行为 **完全一致**:

| 组件 | 当前交互 | 迁移后交互 | 差异 |
|------|---------|-----------|------|
| UiDialog | 点击遮罩不关闭 (当前未设，需确认)、X 按钮关闭、ESC 关闭 | **完全一致** | 无 |
| UiSelect (简单选择) | 输入框聚焦→展开下拉→输入搜索→点击选中→关闭 | **完全一致** (Shadcn Combobox 同为 Reka ComboboxRoot) | 无 |
| UiCheckbox | 点击切换、支持 indeterminate | **完全一致** | 无 |
| UiTabs | 点击 Tab 切换内容、v-model 受控 | **完全一致** | 无 |
| UiButton | hover 上浮+阴影、active 下沉、focus 蓝色环、disabled 灰色 | **完全一致** (相同的 Tailwind 类名) | 无 |
| UiInput | 聚焦→边框变深蓝+蓝色光晕、placeholder 样式 | **完全一致** | 无 |
| UiSwitch | 滑块滑动、轨道变色 | **完全一致** | 无 |
| UiToast | 右侧滑入、自动消失 | **完全一致** | 无 |

**为什么零变化**: Shadcn-Vue 的底层就是 Reka UI。当前 `UiDialog` 内部使用 `DialogRoot`/`DialogContent`，Shadcn-Vue 的 Dialog 内部也是 `DialogRoot`/`DialogContent`。替换的只是外层封装和样式类名，行为逻辑不变。

### 3.2 新增/增强交互组件 — 变化是正向的

以下组件使用 **PrimeVue Unstyled** 替换或新增，交互更丰富但需学习:

| 组件 | 当前交互 | 迁移后交互 | 变化性质 |
|------|---------|-----------|---------|
| UiDatePicker | 浏览器原生日历弹窗 | **PrimeVue 自定义日历弹窗** | 交互更流畅统一，但弹窗形态不同 |
| UiTable | 各视图自定义的 HTML 表格 | **DataTable 统一交互**: 列头点击排序、列拖拽调整宽度、行 checkbox 选择 | 新增交互，不破坏现有 |
| 产品搜索 | 自建 autocomplete (2 处) | **AutoComplete 统一交互**: 输入→远程搜索→下拉建议→选中 | 交互一致化 (2 处目前行为不同) |
| 级联选择 | 不存在 | **CascadeSelect 交互**: 层级展开→逐级选择 | 新增，不破坏现有 |
| 抽屉 | 自建 PlanDetailDrawer | **Drawer 统一交互**: 右侧滑入、ESC 关闭、遮罩关闭 | 替代自建，交互更标准 |
| 日期范围 | 2 个独立日期框 | **1 个范围选择器**: 点击起始→点击结束 | 更便捷，交互简化 |

### 3.3 需要用户适应的变化

| 变化点 | 影响程度 | 缓解措施 |
|--------|---------|---------|
| 日期选择器从浏览器原生变为自定义日历 | **低** — 用户习惯点击日历图标选日期 | 自定义日历体验通常优于原生 |
| 表格排序从无→点击列头排序 | **零** — 纯功能增加 | — |
| 日期范围从 2 个输入框→1 个范围选择器 | **低** — 操作步骤减少 | 可选：保持 2 个独立 DatePicker 的模式 |

---

## 四、UI 效果与界面变化

### 4.1 "Plush Cute" 设计特征 — 完全保留

以下所有视觉特征在混合方案中 **均可通过 Tailwind 类名或 PT 属性原样复现**:

| 设计特征 | 当前实现 | 混合方案实现 | 变化 |
|----------|---------|-------------|------|
| 大圆角 (card 24px, button 14px, input 12px) | `--radius-card/button/input` tokens | **相同的 CSS 变量 + Tailwind 类名** | 无 |
| 蓝色调阴影 (rgba(135,206,235,0.25)) | 自定义 `--shadow-*` tokens | **相同的 Tailwind shadow 类** | 无 |
| 海洋主题渐变按钮 | `--gradient-primary/success/...` | **相同的 CSS 渐变 + Tailwind bg-gradient 类** | 无 |
| Ocean-light 边框 (#d4f1f4) | `border-ocean-light` | **完全相同的 Tailwind 类** | 无 |
| 蓝色 focus 光晕 | `shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)]` | **完全相同的 Tailwind 类** | 无 |
| Dialog 滑入动画 | `animate-slide-up` | **相同的 CSS animation** | 无 |
| Toast 右侧滑入 | Vue Transition + scoped CSS | **相同的 Transition** | 无 |
| Button hover 上浮 | `hover:-translate-y-0.5 hover:shadow-md` | **完全相同的 Tailwind 类** | 无 |
| Noto Sans SC 字体 | `--font-sans` token | **相同的 CSS 变量** | 无 |
| 背景模糊遮罩 | `backdrop-blur-sm bg-black/50` | **完全相同的 Tailwind 类** | 无 |

**核心原因**: 两个库都支持 Unstyled/Tailwind-native 模式，样式完全由开发者控制。当前所有视觉效果的 Tailwind 类名和 CSS 变量在迁移后原封不动。

### 4.2 界面视觉变化对比

#### 场景 1: 按钮点击

| | 当前 | 迁移后 |
|---|------|--------|
| 默认状态 | 渐变背景 + shadow-sm | **相同** |
| Hover | 上浮 2px + shadow-md | **相同** |
| Active | 下沉回原位 | **相同** |
| Disabled | 半透明 + 禁止光标 | **相同** |

#### 场景 2: 对话框

| | 当前 | 迁移后 |
|---|------|--------|
| 遮罩 | 黑色半透明 + 背景模糊 | **相同** |
| 弹窗 | 白色圆角卡片 + 蓝色阴影 | **相同** |
| 动画 | slide-up 缩放进入 | **相同** |
| 关闭按钮 | 圆形按钮 + hover 变红 | **相同** |
| 标题栏 | 底部分割线 | **相同** |

#### 场景 3: 表格 (变化最大的区域)

| | 当前 | 迁移后 |
|---|------|--------|
| 表头 | 浅灰背景 (#f4f6fc) | **相同** (PT 配置) |
| 行 hover | 各视图不同 (有些无 hover) | **统一**: 浅蓝高亮 (PT 配置，可保持现有) |
| 选中行 | 仅部分视图有，实现各异 | **统一**: checkbox + 背景高亮 |
| 排序指示 | 无 | **新增**: 列头排序箭头 |
| 分页器 | 自建或 UiPagination | **统一**: DataTable 内置分页 (通过 PT 样式化) |
| 空状态 | 手动 v-if + UiEmpty | **统一**: `<template #empty>` |

#### 场景 4: 日期选择器 (唯一视觉变化)

| | 当前 | 迁移后 |
|---|------|--------|
| 输入框 | 海洋色边框 + focus 光晕 | **相同** (PT 配置) |
| 日历弹窗 | 浏览器原生 (Chrome 灰色方块日历) | **自定义日历**: 白色圆角卡片 + 海洋色选中 + 蓝色阴影 (PT + Tailwind) |
| 月份切换 | 浏览器原生 | **自定义左右箭头** (可样式化为 Plush Cute 风格) |
| 日期范围 | 2 个独立输入框 | **1 个输入框 + 范围高亮** |

**这是唯一用户可感知的视觉变化**，且是正向的 — 从浏览器原生控件变为品牌统一的自定义日历。

### 4.3 视觉变化总结

| 区域 | 视觉变化 | 方向 |
|------|---------|------|
| 所有基础组件 (Button/Input/Checkbox/Tabs/Switch/Dialog/Toast) | **零变化** | — |
| 表格 | 样式统一化 + 新增排序/选中指示 | **正向** — 更一致 |
| 日期选择器 | 从浏览器原生→自定义品牌化日历 | **正向** — 更统一美观 |
| 新增组件 (Drawer/CascadeSelect/AutoComplete) | 全新组件，按 "Plush Cute" 风格设计 | **正向** — 风格一致 |

---

## 五、最终回答

### 比现在能提升多少?

**量化提升**:
- 表格相关代码: -75% (8 个视图 ~1000 行 → ~200 行)
- 搜索/选择器: -80% 自建代码，+5 种选择器模式
- 日期选择: 统一外观 + 范围选择
- 表单验证: -60% 验证代码 + 实时校验
- 抽屉: -95% (468 行 → ~20 行)
- 新组件获取速度: 数天 → 数小时
- **解锁当前不可能的功能**: 虚拟滚动、列固定、Excel 导出、级联选择、树形选择、日期范围

### 迁移后交互会变化吗?

- **基础交互**: 零变化。Shadcn-Vue 底层同为 Reka UI，所有点击/聚焦/键盘行为完全一致
- **增强交互**: 正向变化。DataTable 排序/选中、AutoComplete 远程搜索、DatePicker 范围选择
- **用户适应成本**: 极低。唯一需适应的是日期选择器从浏览器原生变为自定义日历 (体验更好)

### UI 效果/界面会变化吗?

- **"Plush Cute" 风格**: 100% 保留。所有圆角、阴影、渐变、海洋色、动画均可通过 Tailwind/PT 原样复现
- **唯一视觉变化**: 日期选择器弹窗 (从浏览器原生灰色→自定义品牌化日历，正向变化)
- **整体观感**: 界面一致性更好 — 表格、选择器、分页器交互统一，不再各视图各自为政
