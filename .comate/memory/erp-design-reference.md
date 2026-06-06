---
name: erp-ui-design-spec
description: ERP 系统 UI 设计规范（强制性）。所有页面的 UI 设计和改造必须遵守此规范，无例外。
type: reference
---

# ERP 系统 UI 设计规范

> **强制性规范**：本规范为所有 ERP 前端页面的 UI 设计标准。当用户说"参考设计"、"参考UI"、"按设计规范"时，必须严格遵守此规范。任何新页面开发、现有页面改造都必须遵守，无例外。
>
> **参考实现**：`frontend-vite/src/views/material-calculator/MaterialCalculatorView.vue`

## 一、整体风格定位

**现代卡片式仪表盘风格（Modern Card Dashboard）**，受 Tailwind UI / Shadcn 设计系统影响，企业级 SaaS 风格。

## 二、核心设计规范

### 1. 页面容器（沉浸式全屏）
```css
.{prefix}-container {
  padding: 8px;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
```

**强制规则**：
- 使用 `height: 100%` 填充父容器，禁止使用 `height: 100vh`（会与 `DefaultLayout` 的 `overflow` 冲突导致双重滚动）
- 禁止设置 `max-width`，卡片全宽展示
- 必须添加 `box-sizing: border-box`

### 2. 整体布局：灵活卡片布局
- **布局不强制**，根据具体页面的内容和交互决定卡片数量与分栏方式：
  - 单卡单栏（表格为主的管理页：供应商、采购）
  - 单卡双栏（左右分栏的选择+详情）
  - 单卡三栏（流程式：选择→输入→结果，如物料计算器）
  - 多卡片纵向排列（Dashboard 概览，如来料进度监控面板）
- **不设独立页面标题区**，标题集成在主卡片头部（可选，无标题时可省略标题组）
- 侧边栏 LOGO 作为返回首页入口（`<router-link to="/dashboard">`）

```css
.{prefix}-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
```

### 3. 卡片（Card）
- **白底圆角卡片**，不使用 UiCard 组件包裹，用原生 div + scoped CSS
- `background: white; border-radius: 18px`
- `border: 1px solid var(--color-border-light, #e2e8f0)`
- `box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06)`
- **悬浮动画仅增强阴影，禁止位移**（见第19节动效规范）
- **禁止在卡片元素上设置 `overflow: hidden`**（会裁剪悬浮阴影），内容裁剪由 `.{prefix}-card-main` 处理

**卡片 overflow 规则**：
```css
.{prefix}-card {
  /* 不设置 overflow，允许阴影溢出 */
}
.{prefix}-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;  /* 内容裁剪在此层处理 */
}
```

### 4. 卡片头部 / 区块标题
- **白色背景融合进卡片主体**，不使用灰色背景
- `padding: 14px 24px 10px`
- `background: transparent`（继承卡片白色背景）
- `display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap`
- **两种布局方式**：
  1. **标准布局**：HeaderTabs（第一行）+ 标题 + 操作按钮（第二行）
  2. **左右分栏布局**：左侧 HeaderTabs / 标题，右侧页面TAB按钮/操作按钮（适用于采购页面等需要独立TAB切换的场景）
- 左侧标题：`font-size: 14px; font-weight: 700; color: var(--color-text)` + 图标
- 右侧：操作按钮组（badge + action buttons + status badge）
- **快捷切换标签栏 `<HeaderTabs />`** 必须作为 `card-header` 的第一个子元素（标准布局）或左侧栏的内容（左右分栏布局）
- **左右分栏布局规则**：
  - 左侧栏：`.{prefix}-header-left`，`flex: 1; display: flex; align-items: center;`，放置 HeaderTabs 或标题
  - 右侧栏：`.{prefix}-header-right`，`display: flex; align-items: flex-start; justify-content: flex-end;`，放置页面 TAB 按钮或操作按钮
  - 卡片头部 `align-items` 根据右侧内容调整：为右侧栏对齐时使用 `align-items: flex-start`

**强制规则**：区块标题（如"审核订单"、"采购中订单"等）不使用灰色背景，不使用 uppercase，标题直接融入卡片白色主体，靠字号和字重区分层级。所有页面的 `card-header` 必须添加 `flex-wrap: wrap` 以支持 HeaderTabs 换行布局。

### 5. 多栏主体（Body Grid，按需使用）
- 仅在页面内容适合多栏并排时使用，单栏页面无需 grid
- 三栏示例：`grid-template-columns: 1fr 1fr 1fr`
- 双栏示例：`grid-template-columns: 1fr 1fr`
```css
.{prefix}-body {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr; /* 按实际需求调整 */
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
```

### 6. 栏目（Column）
```css
.{prefix}-col {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}
.{prefix}-col + .{prefix}-col {
  border-left: 1px solid var(--color-border-light, #f1f5f9);
}
```

### 7. 栏目标题（Column Title）
```css
.{prefix}-col-title {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border-light, #f1f5f9);
  flex-shrink: 0;
}
.{prefix}-col-title i {
  font-size: 14px;
  color: var(--color-primary-500);
}
```

**强制规则**：栏目标题不使用灰色背景、不使用 uppercase，白色背景融合进栏目。

### 8. 图标色块（Icon Box）
- 46×46px 圆角方块，`border-radius: 13px`
- 预设色系：
  - 蓝（primary）：`background: linear-gradient(135deg, --color-primary-100, --color-primary-200)`
  - 绿（success）：`background: linear-gradient(135deg, --color-success-100, --color-success-200)`
  - 紫（purple）：`background: linear-gradient(135deg, --color-purple-100, --color-purple-200)`
  - 橙（warning）：同上模式用 warning 色系
- 图标：`font-size: 19px`

### 9. 徽章/标签（Badge）
- 胶囊形：`border-radius: 20px; padding: 6px 14px`
- 渐变背景：`background: linear-gradient(135deg, var(--color-primary-500), var(--color-primary-700))`
- 白色文字：`color: white; font-size: 13px; font-weight: 600`

### 10. 操作按钮（Action Button）
- 扁平圆角按钮，`border-radius: 9px; padding: 7px 14px`
- `border: 2px solid var(--color-border-light); background: white; font-size: 12px; font-weight: 600`
- `transition: all 0.3s ease`
- 主操作（primary）：`color: var(--color-primary-600)`; hover: `background: var(--color-primary-50); border-color: var(--color-primary-300); transform: translateY(-1px)`
- 危险操作（danger）：`color: var(--color-danger-500)`; hover: `background: var(--color-danger-50); border-color: var(--color-danger-200); transform: translateY(-1px)`
- 禁用态：`opacity: 0.4; cursor: not-allowed`

### 11. 搜索框
- `padding: 12px 40px 12px 42px`（左侧留出图标空间）
- `border: 2px solid var(--color-border-light, #e2e8f0); border-radius: 11px`
- `background: white`
- `transition: all 0.3s ease`
- focus：`border-color: var(--color-primary-400); background: white; box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1)`
- 右侧清除按钮：圆形 `border-radius: 50%`
- 下拉建议框：`border: 2px solid var(--color-primary-200); border-radius: 12px; box-shadow: 0 10px 40px rgba(0, 0, 0, 0.12)`

### 12. 筛选按钮栏
- `display: flex; gap: 8px`
- 按钮：`flex: 1; padding: 9px 14px; background: white; border: 2px solid var(--color-border-light); border-radius: 9px; font-size: 13px; font-weight: 600; transition: all 0.2s ease`
- 激活态：`background: var(--color-primary-50); border-color: var(--color-primary-400); color: var(--color-primary-700)`
- hover：`transform: translateY(-1px)`

### 13. 列表项（Product / Order）
- `display: flex; align-items: center; gap: 12px`
- `padding: 14px 16px`（产品项）/ `padding: 10px 14px`（订单项）
- `border: 2px solid var(--color-border-light); border-radius: 12px / 10px`
- `transition: all 0.3s ease`
- hover：`border-color: var(--color-primary-300); transform: translateX(4px)`（产品列表项滑移）/ `transform: translateY(-1px)`（订单项微浮）
- 选中态：`border-color: var(--color-primary-500); background: var(--color-primary-50); box-shadow` 加深

### 14. 表格
- 不使用自定义类名如 `plush-table`，直接在卡片内用原生 table
- 表头：`padding: 10px 14px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; background: var(--color-surface); border-bottom: 2px solid var(--color-border-light)`
- 表体：`padding: 10px 14px; font-size: 13px; border-bottom: 1px solid var(--color-border-light, #f1f5f9); transition: background 0.2s ease`
- 行 hover：`background: var(--color-primary-50)`
- 表格外层：`border-radius: 10px; overflow: hidden; border: 1px solid var(--color-border-light)`

### 15. 分类折叠块（Category Block）
- 头部按钮：`padding: 12px 16px; border-radius: 11px; width: 100%; text-align: left; transition: all 0.3s ease`
- 色系变体（.mc-cat-filling / fabric / accessory / packaging）：
  - filling：`background: linear-gradient(135deg, --color-info-50, --color-surface-card)`; 图标/标签色 `--color-primary-700`
  - fabric：`background: linear-gradient(135deg, --color-success-50, --color-surface-card)`; 色系 `--color-success-700`
  - accessory：`background: linear-gradient(135deg, --color-warning-50, --color-surface-card)`; 色系 `--color-warning-800`
  - packaging：`background: linear-gradient(135deg, --color-purple-50, --color-surface-card)`; 色系 `--color-purple-800`
- 展开箭头：`margin-left: auto; transition: transform 0.25s`; 展开时 `transform: rotate(180deg)`

### 16. 汇总面板（Summary Panel）
- `background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100))`
- `border-radius: 13px; border: 1px solid var(--color-primary-200)`
- `display: flex; justify-content: space-between; align-items: center`
- 数字：`font-size: 32px; font-weight: 800; color: var(--color-primary-600)`

### 17. 状态徽章（Status Badge）
- `padding: 5px 12px; border-radius: 16px; font-size: 12px; font-weight: 600`
- 计算中：`background: var(--color-warning-50); color: var(--color-warning-600)`
- 完成：`background: var(--color-success-50); color: var(--color-success-600)`

### 18. 空状态/加载状态
- 居中纵向排列：`flex-direction: column; align-items: center; gap: 10px`
- `padding: 40px 20px`
- 图标：`font-size: 28px; opacity: 0.5`
- 文字：`font-size: 14px; color: var(--color-text-muted)`

### 19. 动效规范（强制）

**三档过渡速度，必须严格遵守：**

| 速度 | 缓动函数 | 适用场景 |
|------|---------|---------|
| **0.2s ease** | ease | 行hover、小按钮、输入框focus、表格行 |
| **0.3s ease** | ease | 操作按钮、表单控件、列表项、筛选按钮、分类头部、TAB按钮 |
| **0.4s cubic-bezier(0.4, 0, 0.2, 1)** | Material Design | 主卡片hover |

**卡片悬浮动画（主卡片上浮 + 阴影增强）：**
```css
.card {
  border: 1px solid var(--color-border-light, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}
.card:hover {
  box-shadow: 0 8px 24px rgba(0,0,0,0.06), 0 24px 80px rgba(0,0,0,0.08);
  transform: translateY(-6px);
}
```

**统计卡片悬浮动画（轻阴影增强，禁止位移）：**
```css
.stat-card {
  transition: box-shadow 0.3s ease;
}
.stat-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.06);
}
```

**交互微动效（必须实现）：**
- 列表项滑移：`transform: translateX(4px)` 用于产品/订单列表项hover
- 按钮微浮：`transform: translateY(-1px)` 用于操作按钮hover
- TAB按钮微浮：`transform: translateY(-1px)` 用于TAB按钮hover（含active态）
- 搜索框focus环：`box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1)`
- 表格行hover：`background: var(--color-primary-50); transition: background 0.2s ease`
- **滚动列表项hover/选中（禁止位移）**：用于弹窗内的计划详情、客户卡片等滚动容器内的列表项，`transform` 会导致裁剪：
```css
.list-item {
    border: 1px solid var(--color-border-light);
    border-radius: 10px;
    background: white;
    transition: background 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}
.list-item:hover {
    border-color: var(--color-primary-500);
    background: var(--color-primary-50);
    box-shadow: 0 2px 8px rgba(91, 141, 239, 0.15);
}
```
  - **禁止 transform**：滚动容器内 `translateY`/`scale` 会裁剪
  - **选中态同 hover**：`border-color: var(--color-primary-500)` + `background: var(--color-primary-50)` + 蓝色阴影

**禁令：**
- **禁止**在统计卡片（`.stat-card`）上使用 `transform: translateY(-6px)` 或任何位移效果
- **禁止**从 `opacity: 0` 开始的入场动画（已确认会导致闪屏）
- **禁止**在卡片头部/区块标题使用灰色背景
- **禁止**硬编码色值，必须使用 CSS 变量

### 20. 表单输入框（强制统一）
所有表单输入控件必须使用统一视觉风格，包括 UiSelect、UiDatePicker、原生 input、原生 textarea：

```css
/* 统一输入框样式 */
input, textarea, select, .ui-select-input, .date-input {
  width: 100%;
  padding: 0.625rem 2.5rem 0.625rem 1rem;  /* 右侧留出图标/箭头空间 */
  font-size: 0.9375rem;
  line-height: 1.5;
  color: var(--color-heading);
  background: white;
  border: 2px solid var(--color-ocean-light);
  border-radius: var(--radius-input);  /* 12px */
  transition: all 0.3s ease;
  outline: none;
  min-height: 44px;
  box-sizing: border-box;
  font-family: inherit;
}
/* focus 统一 */
input:focus, textarea:focus, select:focus, .ui-select-input:focus, .date-input:focus {
  background: var(--color-surface-card);
  border-color: var(--color-ocean-deep);
  box-shadow: 0 0 0 0.2rem rgba(135, 206, 235, 0.25);
}
/* hover 统一 */
input:not(:disabled):hover, textarea:not(:disabled):hover, select:not(:disabled):hover,
.ui-select-input:not(:disabled):hover, .date-input:not(:disabled):hover {
  border-color: var(--color-ocean-deep);
}
/* disabled 统一 */
input:disabled, textarea:disabled, select:disabled, .ui-select-input:disabled, .date-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

**强制规则**：
- UiSelect 的 `ComboboxInput` 禁止使用 Tailwind 类（`rounded-lg` 等），必须使用自定义 `.ui-select-input` CSS 类
- 所有输入框的 `border-radius` 必须使用 `var(--radius-input)`，禁止硬编码或使用 Tailwind 的 `rounded-*` 类
- 所有输入框的 border 宽度统一 `2px`，颜色统一 `var(--color-ocean-light)`，背景统一 `var(--color-slate-50)`

**Placeholder 样式强制规则**：
浏览器默认为 `::placeholder` 伪元素添加 `opacity: 0.54`（Chrome），导致即使设置了相同颜色值，placeholder 文本也比普通文本更浅/更细。必须显式覆盖：

```css
textarea::placeholder,
input::placeholder {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 400;
  opacity: 1;  /* 强制覆盖浏览器默认 opacity: 0.54 */
}
```

当其他元素需要与 placeholder 保持一致的视觉风格（如拖拽上传提示文字）时，必须使用与 `::placeholder` 完全相同的属性值：
```css
/* 提示文字（等同于 placeholder 视觉效果） */
.{prefix}-droppable-label {
  font-size: 14px;
  font-weight: 400;
  color: var(--color-text-muted);
}
```

### 21. 可折叠区块标题（输入框风格）
表单内的可折叠区块标题栏（如"批量导入"、"OCR 识别导入"）使用与输入框相同的视觉风格，让区块标题融入表单：

```css
.{prefix}-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  min-height: 40px;
  box-sizing: border-box;
  cursor: pointer;
  transition: all 0.3s ease;
}
.{prefix}-section-header:hover {
  border-color: var(--color-ocean-deep);
  background: white;
}
.{prefix}-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.{prefix}-section-title i {
  font-size: 13px;
  color: var(--color-danger-500);
}
```

**强制规则**：可折叠区块标题禁止使用 `border-top` 分隔线 + 透明背景的旧模式，必须使用输入框风格的边框 + 圆角 + 白色背景。

### 22. 拖拽上传区（Upload Area）
文件上传使用"标题栏即拖拽区"模式，标题栏本身是可点击/可拖拽的文件输入区域，禁止使用 UiUpload 组件：

```css
/* 标题栏即拖拽区 */
.{prefix}-section-header.{prefix}-droppable {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: white;
  border: 2px solid var(--color-border-light, #e2e8f0);
  border-radius: var(--radius-input, 12px);
  min-height: 40px;
  cursor: pointer;
  transition: all 0.3s ease;
}
.{prefix}-droppable:hover {
  border-color: var(--color-ocean-deep);
  background: white;
}
/* 拖拽悬浮态 - success 变体 */
.{prefix}-droppable.{prefix}-drag-over {
  border-color: var(--color-success-400);
  background: var(--color-success-50);
}
/* 拖拽悬浮态 - danger 变体（OCR/PDF） */
.{prefix}-droppable-danger.{prefix}-drag-over {
  border-color: var(--color-danger-400);
  background: var(--color-danger-50);
}
/* 提示文字（与 placeholder 视觉一致，见 Section 20） */
.{prefix}-droppable-label {
  font-size: 14px;
  font-weight: 400;
  color: var(--color-text-muted);
  display: flex;
  margin-bottom: 0;
  cursor: pointer;
}
.{prefix}-droppable-label .label-icon {
  color: var(--color-text-muted);
}
/* 标题栏上方的小标签 */
.{prefix}-section-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-secondary);
  padding: 8px 0 4px;
}
/* 内联操作按钮 */
.{prefix}-inline-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}
.{prefix}-inline-btn {
  padding: 3px 8px;
  border: 1px solid;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}
/* 选中文件行内标签 */
.{prefix}-file-inline {
  font-size: 13px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.{prefix}-file-inline-success { color: var(--color-success-600); }
.{prefix}-file-inline-danger { color: var(--color-danger-600); }
```

**HTML 模板**：
```html
<div class="{prefix}-section-label"><i class="fas fa-file-import"></i> 批量导入</div>
<div class="{prefix}-section-header {prefix}-droppable"
  :class="{ '{prefix}-drag-over': dragOver }"
  @click="fileInputRef?.click()"
  @dragover.prevent @dragleave @drop.prevent>
  <label class="form-label {prefix}-droppable-label">
    <i class="fas fa-file-excel label-icon"></i>
    <span v-if="selectedFile" class="{prefix}-file-inline {prefix}-file-inline-success">...</span>
    <span v-else>拖拽文件到标题栏 · 支持 .xlsx / .xls</span>
  </label>
  <div class="{prefix}-inline-actions">
    <button class="{prefix}-inline-btn" @click.stop="handleTemplate">模板</button>
    <button class="{prefix}-inline-btn {prefix}-inline-btn-success" @click.stop="handleImport">导入</button>
  </div>
  <input ref="fileInputRef" type="file" accept=".xlsx,.xls" style="display: none" @change="onFileSelect" />
</div>
```

**强制规则**：
- 文件上传必须使用原生 `<input type="file" style="display: none">` + 标题栏拖拽区，禁止使用 UiUpload 组件
- 标题栏本身即为拖拽区，禁止单独创建拖拽区域（如 dashed border 拖拽框）
- 提示文字必须与 `::placeholder` 视觉一致（`font-size: 14px; font-weight: 400; color: var(--color-text-muted)`），见 Section 20
- 内联操作按钮必须使用 `@click.stop` 阻止冒泡，防止触发标题栏的文件选择器
- 拖拽区支持两种主题：success（Excel 上传）和 danger（OCR/PDF 上传）
- 标题栏上方使用 `.{prefix}-section-label` 小标签标注分类

### 23. TAB 切换栏
- **两种位置**：
  1. 卡片头部右侧操作按钮区域（标准位置）
  2. 卡片头部右侧独立栏（左右分栏布局，适用于采购页面等场景）
- **TAB容器（侧边栏风格白色圆角容器）**：
  ```css
  .{prefix}-tab-group {
    display: inline-flex;
    gap: 4px;
    padding: 4px;
    border-radius: 12px;
    background: white;
    border: 1px solid var(--color-border-light);
    box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  }
  ```
- **TAB按钮样式（与侧边栏导航项造型一致）**：
  - `padding: 8px 14px; border: none; border-radius: 9px; background: transparent`
  - `font-size: 13px; font-weight: 600; color: var(--color-text-secondary)`
  - `transition: all 0.3s ease`
  - 激活态：`background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100)); color: var(--color-primary-700); box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2); transform: translateY(-1px)`
  - hover：`background: var(--color-primary-50); color: var(--color-primary-600); box-shadow: 0 4px 12px rgba(0,0,0,0.08); transform: translateY(-1px)`
- TAB按钮内容：纯文字，不强制使用图标
- 内容区用 `v-show` 切换，加 `.{prefix}-tab-content` 类
- **TAB角标**（可选，用于显示未处理数量）：
  ```css
  .{prefix}-tab-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    background: var(--color-danger-500);
    color: white;
    font-size: 10px;
    font-weight: 700;
    border-radius: 9px;
    line-height: 1;
  }
  ```

### 24. 弹窗表单
- 标签：`font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-text-secondary)`
- 输入框：`padding: 8px 12px; border: 2px solid var(--color-border-light); border-radius: 10px; font-size: 14px; transition: all 0.3s ease`
- focus：`border-color: var(--color-primary-400); background: white; box-shadow: 0 0 0 4px rgba(0, 148, 191, 0.1)`
- 关联字段双列：`display: grid; grid-template-columns: 1fr 1fr; gap: 16px`

### 25. 侧边栏卡片（Sidebar Card）

侧边栏整体作为**浮动卡片**，与主内容区之间留有间隙，通过 `app-layout` 背景色透出形成视觉分隔。

```css
.sb-sidebar {
  width: 280px;
  min-width: 68px;
  flex-shrink: 0;
  background: white;
  border-radius: 18px;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  height: calc(100vh - 24px);
  margin: 12px;
}
.sb-sidebar:hover {
  box-shadow: 0 8px 24px rgba(0,0,0,0.06), 0 24px 80px rgba(0,0,0,0.08);
}
```

**导航项卡片**：每个导航项也是独立的白色小卡片，hover 时微浮 + 阴影加深：
```css
.sb-nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  margin-bottom: 4px;
  border-radius: 12px;
  text-decoration: none;
  color: var(--color-text);
  font-weight: 600;
  font-size: 14px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  transition: all 0.3s ease;
}
.sb-nav-item:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
  transform: translateY(-1px);
  border-color: var(--color-primary-200);
}
.sb-nav-item.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  border-color: var(--color-primary-300);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 12px 32px rgba(0,0,0,0.1);
}
```

**导航图标**：32×32px 圆角方块，`border-radius: 9px`，背景 `var(--color-surface)`，激活态渐变：
```css
.sb-nav-icon {
  width: 32px; height: 32px; border-radius: 9px;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; color: var(--color-text-secondary);
  background: var(--color-surface); flex-shrink: 0;
  transition: all 0.3s ease;
}
.sb-nav-icon-active {
  background: linear-gradient(135deg, var(--color-primary-100), var(--color-primary-200));
  color: var(--color-primary-600);
}
```

**折叠态**：`width: 68px`，导航项居中仅显示图标，图标放大到 36×36px / `border-radius: 10px`。

**移动端**：`position: fixed; margin: 0; border-radius: 0; height: 100vh`，折叠态 `width: 0; min-width: 0; overflow: hidden`。

**强制规则**：
- 侧边栏整体必须是浮动卡片（`margin: 12px; border-radius: 18px`），禁止贴边
- 导航项必须是白底卡片（`background: white; border + box-shadow`），禁止使用透明/无边框模式
- 激活态必须使用渐变背景（`linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100))`）

### 26. 快捷切换标签栏（HeaderTabs）

嵌入在卡片头部标题上方的紧凑标签栏，用于多页面快速切换。仅当打开 2+ 页面时显示。

**组件**：`HeaderTabs.vue`，Pinia Store：`useTabStore`（`stores/tabs.ts`）

**布局规则**：
- `<HeaderTabs />` 作为 `card-header` 的**第一个子元素**
- `card-header` 必须设置 `flex-wrap: wrap`
- HeaderTabs 占据第一行（`width: 100%`），标题 + 操作按钮占据第二行

```css
.ht-bar {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 12px;
  background: white;
  border: 1px solid var(--color-border-light);
  box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 4px 12px rgba(0,0,0,0.06);
  overflow-x: auto;
  flex-shrink: 0;
  width: 100%;
}
```

**标签样式**（与 TAB 切换栏 `.tab-group` 造型一致，白底圆角容器+透明按钮+渐变激活态）：
```css
.ht-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 8px 14px;
  border: none;
  border-radius: 9px;
  background: transparent;
  text-decoration: none;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  transition: all 0.3s ease;
  flex-shrink: 0;
  cursor: pointer;
}
.ht-tab:hover {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateY(-1px);
}
.ht-tab.active {
  background: linear-gradient(135deg, var(--color-primary-50), var(--color-primary-100));
  color: var(--color-primary-700);
  box-shadow: 0 4px 12px rgba(0,0,0,0.08), 0 2px 8px rgba(91, 141, 239, 0.2);
  transform: translateY(-1px);
}
```

**关闭按钮**：
```css
.ht-tab-close {
  width: 16px; height: 16px; border-radius: 50%;
  border: none; background: transparent;
  color: var(--color-text-muted); font-size: 9px;
  transition: all 0.2s ease; padding: 0;
  display: flex; align-items: center; justify-content: center;
  opacity: 0.6;
}
.ht-tab-close:hover {
  background: var(--color-danger-50);
  color: var(--color-danger-500);
  opacity: 1;
}
```

**交互规则**：
- 标签使用 `<router-link>` 导航，关闭按钮使用 `@click.prevent.stop` 阻止冒泡
- 关闭当前激活标签时，自动切换到相邻标签
- 返回主页（`/dashboard`）时自动清除所有标签
- 最大标签数 15，超出时移除最早的标签
- 标签图标：11px，标签文字最大宽度 100px + `text-overflow: ellipsis`

**HTML 模板**：
```html
<div class="{prefix}-card-header">
  <HeaderTabs />  <!-- 第一个子元素，占据整行 -->
  <div class="{prefix}-card-title-group">...</div>
  <div class="{prefix}-header-actions">...</div>
</div>
```

**强制规则**：
- 所有页面卡片头部必须包含 `<HeaderTabs />`
- HeaderTabs 必须是 card-header 的第一个子元素
- card-header 必须设置 `flex-wrap: wrap`
- 禁止将 HeaderTabs 放在 header-actions 内或作为独立组件使用

## 三、布局模式：沉浸式全屏 + 浮动卡片布局

所有页面采用**隐藏顶部导航栏、保留侧边栏**的沉浸式全屏布局：

1. 路由添加 `meta: { hideHeader: true }`
2. `DefaultLayout.vue` 根据 `route.meta.hideHeader` 条件隐藏 `<header class="top-header">`
3. 侧边栏始终显示（不隐藏）
4. 侧边栏 LOGO 可点击返回首页：`<router-link to="/dashboard" class="sidebar-logo">`
5. 页面自身不设"返回首页"按钮，依赖侧边栏 LOGO
6. `content-container` 使用 `no-padding` 类（padding: 0, overflow: visible 允许卡片阴影溢出）
7. 页面容器使用 `height: 100%` 填充父容器（禁止 `100vh`，避免双重滚动）

**防双重滚动规则**：
- 所有页面容器必须使用 `height: 100%`，禁止 `height: 100vh`
- `.content-container.no-padding` 设置 `overflow: visible`（允许卡片阴影溢出 + 避免双重滚动）
- `.main-content.immersive` 设置 `overflow: visible`（hideHeader 模式下允许阴影溢出）
- 卡片内部滚动由 `.{prefix}-card-main` 的 `overflow: hidden` + `.{prefix}-body` 的 `overflow-y: auto` 管理
- 禁止在 `.{prefix}-card` 上设置 `overflow: hidden`（会裁剪悬浮阴影）

**浮动卡片间距布局**：
- `app-layout` 设置 `background: var(--color-surface)` 作为间隙底色
- 侧边栏：`margin: 12px; border-radius: 18px` 形成浮动卡片（见第25节）
- 主内容区：`border-radius: 14px; margin: 4px 4px 4px 0` 形成独立卡片
- 两者之间的间隙通过 `app-layout` 的 `var(--color-surface)` 背景色透出，形成视觉分隔

```css
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
  position: relative;
  background: var(--color-surface);
  box-sizing: border-box;
}
.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, var(--color-surface) 0%, var(--color-border-light) 100%);
  border-radius: 14px;
  overflow: hidden;
  margin: 4px 4px 4px 0;
}
```

**注意**：布局方式（单栏/双栏/三栏/多卡片）不强制，根据页面具体内容灵活选择。

## 四、CSS 命名规范

- 每个页面用 2-3 字母前缀 + 短横线：`.mc-container` / `.sp-header` / `.pc-card`
- 布局组件前缀：`.sb-` 侧边栏（Sidebar）、`.ht-` 快捷切换标签（HeaderTabs）、`.app-` 全局布局
- BEM 简化风格：前缀-元素名，如 `mc-card-header`、`mc-search-input`
- 所有样式 `scoped`，不使用全局 CSS
- 颜色全部用 CSS 变量（`var(--color-primary-*)`），不硬编码色值

## 五、模板结构

> 布局不强制三栏，根据页面内容选择单栏/双栏/三栏/多卡片等结构。以下为三栏示例。

```
<div class="{prefix}-container">
  <div class="{prefix}-card {prefix}-card-main">

    <!-- 卡片头部：快捷切换标签 + 标题 + 操作 -->
    <div class="{prefix}-card-header">
      <HeaderTabs />
      <div class="{prefix}-card-title-group">  <!-- 可选，无标题时可省略 -->
        <div class="{prefix}-icon-box {prefix}-icon-blue">
          <i class="fas fa-xxx" />
        </div>
        <div>
          <h3>页面标题</h3>
          <small>页面描述</small>
        </div>
      </div>
      <div class="{prefix}-header-actions">
        <span class="{prefix}-badge">数量</span>
        <button class="{prefix}-action-btn {prefix}-action-btn-primary">操作</button>
      </div>
    </div>

    <!-- 多栏主体 -->
    <div class="{prefix}-body">
      <div class="{prefix}-col">
        <div class="{prefix}-col-title"><i class="fas fa-xxx" /> 栏目标题</div>
        <!-- 栏目内容 -->
      </div>
      <!-- 更多栏目... -->
    </div>

  </div>
</div>
```

## 六、关键交互规范

1. **多选列表**：点击项目切换选中态（checkbox + 高亮边框），选中态使用 `border-color: var(--color-primary-500)` + `background: var(--color-primary-50)`
2. **搜索建议**：输入 250ms 防抖后请求，下拉框 `mousedown.prevent` 选中（避免 blur 先触发），blur 150ms 延迟关闭
3. **数量输入**：`type="number"` + `@input="debounceCalc"` 350ms 防抖触发计算
4. **折叠分类**：点击分类头切换展开/收起，箭头旋转 180° 指示状态
5. **批量操作**：弹窗统一输入数量，应用到全部订单项
6. **删除项目**：使用 `Array.splice()` 而非 `Array.filter()` 避免 Vue 响应式数组替换闪烁
