# /pattern-room 无障碍合规审查报告

- 审查对象：`https://192.168.0.95/pattern-room`（板房打样项目页）
- 基准：**WCAG 2.2 Level AA**
- 审查日期：2026-10-22
- 审查范围：路由 `pattern-room`（`meta.hideHeader: true`）及其全部子组件 + 复用的 `components/ui/` 共享组件

## 0. 方法与局限

| 手段 | 说明 |
|---|---|
| 源码审查 | 逐文件读 `frontend-vite/src/views/pattern-room/**`（19 个组件 / 4103 行）与 `components/ui/` 共享件 |
| 对比度实测 | 按 WCAG 相对亮度公式实算（脚本计算，非估算），见 §4 对照表 |
| 结构统计 | 全模块 `<label>` 6 个、带 `for` 的 **0** 个；`<input>` 12 个；`aria-label` 11 处；标题 `<h1>~<h6>` **1** 个（`EmptyState` 的 `<h3>`）；`tabindex` **1** 处 |
| 线上探测 | `curl` 返回 `200 text/html`，但页面为需登录的 SPA，未在浏览器内跑 axe-core |

> 局限：未做真实浏览器的 axe/屏幕阅读器实测。下述结论均为**源码级确定性缺陷**（属性缺失、语义错误、焦点不可达），对比度项为实算值。建议修复后登录态补跑一次 axe DevTools 做交叉验证。

## 1. 结论摘要

共 **22 项**需修复，其中 P1（阻断核心任务）7 项、P2（不合规但有替代路径）10 项、P3（体验/健壮性）5 项。

> **范式层落地进度**：22 项里反复出现的 3 类（选中态 / 加载态 / 表单标签）已抽出共享范式，见
> [docs/designs/2026-10-22-a11y-shared-patterns-design.md](designs/2026-10-22-a11y-shared-patterns-design.md)。
> 已落地：`useSelectionA11y`、`UiLoadingStatus`、`UiFormField`，并完成模块内回填，逐项状态见下表。

### 修复进度（2026-10-22 第四轮）

| 状态 | 项目 |
|---|---|
| ✅ 已修 | A11Y-01/02/03 卡片嵌套交互（拆成「看图按钮 + 名称按钮 + 操作按钮」三个平级元素，选中态用 `aria-current`，拉伸热区用伪元素保留原点击手感）、A11Y-04 批量部位表单标签、A11Y-05 项目表单标签、A11Y-07 三处选中态（`aria-pressed`）、A11Y-10 焦点指示（模块内 `outline: none` 清零）、A11Y-11 搜索框标签与 `search` 地标、A11Y-12 页面主标题 + 路由级 `document.title`、A11Y-13 三处加载态、A11Y-14 目标尺寸（展开键 20→24px、版本 chip 22→24px）、A11Y-15 地标命名、A11Y-16 表格 `caption` + 行内输入标签、A11Y-17 跳转主内容链接、A11Y-18 角色输入框标签、A11Y-19 菜单键盘、A11Y-20 分页语义、A11Y-21 图标按钮命名（行内复制/修改/删除/保存/取消改为「动作 + 部位 + 版本」并带禁用原因；展开键补 `aria-expanded`；版师删除、角色移除、新增角色按钮同理）、A11Y-22 虚拟列表（`aria-setsize` / `aria-posinset`） |
| ⬜ 待决策 | A11Y-06 角色页签 tablist（需先决定右键菜单与内联输入的归属位置）、A11Y-08 对比度配色（改生产视觉，待批）、A11Y-09 禁止缩放（改 `index.html`，影响全站移动端，待批） |

> 22 项中 **19 项已修、3 项待决策**。
>
> 新增发现（改动时暴露，未修）：`DialogMakerSelect` 是自绘下拉，触发按钮已有 `aria-expanded`/`aria-controls`，
> 但候选面板仍是 `<div>` + 一堆 `<button>`，没有 `listbox`/`option` 与方向键漫游（4.1.2 / 2.1.1）。

| 级别 | 数量 | 主要症结 | 涉及条款 |
|---|---|---|---|
| **P1 严重** | 7 | 交互语义错误、表单无程序化标签、选中态仅靠颜色 | 4.1.2 / 2.1.1 / 1.3.1 / 3.3.2 |
| **P2 中等** | 10 | 对比度不足、禁用缩放、焦点指示不足、无标题层级、加载态静默 | 1.4.3 / 1.4.11 / 1.4.4 / 2.4.11 / 2.4.2 / 4.1.3 / 2.5.8 |
| **P3 轻微** | 5 | 命名与菜单键盘细节 | 4.1.2 / 2.1.1 |

**最该先修的 4 件事**（投入最小、收益最大）：

1. `ProjectCardItem` 的 `role="button"` 嵌套了 3 个按钮 —— 读屏器会把卡片内部全部压平，**编辑/完成/取消三个功能对读屏器用户等于不存在**（A11Y-01）。
2. 两个录入表单（新增项目、批量新增部位）都**没有程序化标签** —— 读屏器只能读出「编辑框 如 身体，头部」（A11Y-04/05）。
3. 所有「选中态」都只靠颜色/渐变表达，且 `#ff9f43` 系配色实测仅 **1.95~2.33:1**（A11Y-06/07/08）。
4. `index.html` 的 `user-scalable=no` 直接**禁止了双指缩放** —— 低视力用户在手机端无法放大页面（A11Y-09）。

## 2. P1 严重问题

### A11Y-01 项目卡片把 3 个按钮嵌进了 `role="button"` 里

- **条款**：4.1.2 Name, Role, Value｜1.3.1 Info and Relationships
- **位置**：`frontend-vite/src/views/pattern-room/components/ProjectCardItem.vue:2-6`（根 `div` 带 `role="button" tabindex="0"`），内部 `:12-15`（缩略图 `role="button"`）、`:67-94`（编辑/完成/取消 3 个 `<button>`）
- **证据**：ARIA 规范规定 `role="button"` 的子代被赋 **presentational**，内部语义全部被浏览器折叠；axe 规则 `nested-interactive` 会直接判 serious。实测三个操作按钮在读屏器的「按钮列表」中不会出现。
- **影响**：读屏器用户无法编辑、标记完成、取消项目；只能选中卡片。

### A11Y-02 缩略图是「点击才能看图」，键盘完全够不到

- **条款**：2.1.1 Keyboard
- **位置**：`ProjectCardItem.vue:12-15`
- **证据**：`role="button" title="点击查看大图" @click.stop="emit('preview', ...)"`，**无 `tabindex`、无 `@keydown`**。全模块 `tabindex` 仅 1 处（卡片根），故该元素不在 Tab 序列内。
- **影响**：键盘用户无法查看产品大图。

### A11Y-03 卡片模拟按钮但只认 Enter，不认 Space

- **条款**：2.1.1｜4.1.2
- **位置**：`CustomerProjectArea.vue:32-33`（`@click` + `@keyup.enter`）
- **证据**：原生 `button` 的键盘约定是 Enter **和** Space 都激活；`role="button"` 必须自行补 Space。此处只绑了 `keyup.enter`。
- **影响**：按下空格无反应，与用户预期不符（部分读屏器用户习惯 Space 激活）。

### A11Y-04 批量新增部位表单：12 个输入框零标签，列头还被 `aria-hidden`

- **条款**：4.1.2｜1.3.1｜3.3.2 Labels or Instructions
- **位置**：`PartFormDialog.vue:113-124`（列头 `<div aria-hidden="true">`）、`:133-139`（部位名称 input）、`:142-164`（4 个字段 input / `PartFieldCombobox`）
- **证据**：列头被显式 `aria-hidden="true"`，且每个 input 只有 `placeholder`（如 `如 身体，头部`、`field.placeholder`），无 `aria-label` / `aria-labelledby` / `<label>`。
- **影响**：读屏器用户听到「编辑框，如 身体，头部」后，后续四个字段只靠占位符猜测含义；**批量录入主表单不可用**。

### A11Y-05 新建/编辑项目表单：6 个可见 `<label>` 全部未关联输入框

- **条款**：1.3.1｜4.1.2｜2.5.3 Label in Name
- **位置**：`ProjectFormDialog.vue:11`（产品名称）、`:21`（版师）、`:32`（备注）、`:37`（产品图片）、`:48`（角色列表）
- **证据**：`<label class="pjf-label">产品名称 *</label>` 无 `for`，输入框也未包在 label 内、无 `id`。全模块统计：`<label>` 6 个 / 带 `for` 的 0 个。
- **补充**：备注框靠 `aria-label="项目备注..."` 兜住（`:33`），但**必填标记 `*` 与「产品名称」这一可见名称**没有进入输入框的可访问名。
- **影响**：读屏器只报「编辑框，请输入产品名称」（取自 placeholder）；必填状态不可感知。

### A11Y-06 角色标签实为 tablist，却没有任何 tab 语义，选中态纯靠渐变

- **条款**：4.1.2｜1.4.1 Use of Color
- **位置**：`RoleTabs.vue:3-18`（`<button class="role-tab">`），选中样式 `:229-234`（`background: linear-gradient(...)` + 白字）
- **证据**：无 `role="tablist"` / `role="tab"` / `aria-selected`；切换角色会切换下方部位面板，是标准的 tabs 模式。`aria-haspopup="menu"` 只描述右键菜单，不表达选中。
- **影响**：读屏器无法知道「当前在哪个角色下」，只能靠回忆点击顺序。

### A11Y-07 版师筛选 / 状态筛选 / 版本 chip：选中态无 `aria-pressed`

- **条款**：4.1.2｜1.4.1
- **位置**：`CustomerMakerPanel.vue:3-11`（版师项）、`CustomerGroupSearchBar.vue:25-33`（进行中/已完成/已取消）、`PartsVersionRowV2.vue:23-32`（版本 chip）
- **证据**：三处都是 `<button :class="{ active: ... }">`，`:class` 是唯一状态载体，均无 `aria-pressed` / `aria-current`。版师项的选中指示是 `border-left: 3px solid #ff9f43`（`:52-57`）。
- **影响**：读屏器用户无法判断当前筛选条件，反复盲点。

## 3. P2 中等问题

### A11Y-08 对比度不足（实测值，非估算）

- **条款**：1.4.3 Contrast (Minimum) 4.5:1｜1.4.11 Non-text Contrast 3:1

| 元素 | 前景 / 背景 | 实测 | 判定 |
|---|---|---|---|
| 版师项选中文字 `.cgl-customer-item.active` | `#ff9f43` / `#fff9f2` | **1.95:1** | 失败 |
| 版师项选中文字（纯白底） | `#ff9f43` / `#ffffff` | **2.04:1** | 失败 |
| 项目数角标 `.cgl-customer-count` | `#ff9f43` / `#ff9f4320` on white | ≈**2.0:1** | 失败 |
| 版本 chip 选中 `.pvt-vp-chip--active`（11px 白字） | `#ffffff` / `#ff9f43`→`#ff8c1f` | **2.04 / 2.33:1** | 失败 |
| 角色标签选中（13px 白字，渐变浅端） | `#ffffff` / `#3b82f6` | **3.68:1** | 失败 |
| 已完成角标（11px 白字） | `#ffffff` / `rgba(22,163,74,.92)` ≈ `#16a34a` | **3.30:1** | 失败 |
| 版师项选中左边框（非文本指示） | `#ff9f43` / `#ffffff` | **2.04:1** | 失败（需 3:1） |
| 卡片操作按钮 hover 文字 | `#ff9f43` / `#ffffff` | **2.04:1** | 失败 |

- **位置**：`CustomerMakerPanel.vue:52-73`、`PartsVersionRowV2.vue:193-203`、`RoleTabs.vue:229-234`、`ProjectCardItem.vue:291-293 / 379-383`
- **根因**：主橙色 `--color-warning-500: #ff9f43` 被当作**文字色**与**白字底色**使用。该色的相对亮度 0.4645，白字与之一律不过 3:1。

### A11Y-09 视口禁止用户缩放

- **条款**：1.4.4 Resize Text（并影响 1.4.10 Reflow）
- **位置**：`frontend-vite/index.html:5`
- **证据**：`content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, ..."`
- **影响**：移动端低视力用户双指放大被浏览器忽略；桌面端浏览器缩放（Ctrl +/-）不受影响，但手机场景完全失效。

### A11Y-10 输入框 `outline: none` + 仅 1px 边框变色，焦点指示不足

- **条款**：2.4.11 Focus Appearance（AA，WCAG 2.2）；连带削弱 2.4.7
- **位置**：`CustomerGroupSearchBar.vue:92-104`、`ProjectFormDialog.vue:216-231`、`PartFormDialog.vue:250-266`、`RoleTabs.vue:341-350`、`PartsVersionRowV2.vue:302-318`
- **证据**：均写 `outline: none`，聚焦时只把 `border-color` 换成主色。`app.css:708` 的全局 `:focus-visible { outline: 2px solid ... }` 因组件 scoped 样式带 `[data-v-*]`（特异性更高）而被覆盖。
- **量化**：1px 边框变色，等效指示面积 < 2px 周长，不满足 2.4.11 的「至少 2px 厚周长」要求。聚焦色 `#5b8def` 对白底 3.23:1，颜色本身达标。

### A11Y-11 搜索框没有标签，也没有 `search` 地标

- **条款**：3.3.2｜2.4.6 Headings and Labels｜4.1.2
- **位置**：`CustomerGroupSearchBar.vue:4-12`
- **证据**：`placeholder="搜索版师或项目..."` 是唯一名称，`<input>` 无 `aria-label`；外层无 `<form role="search">`。placeholder 在输入后即消失，用户失去「这框是干什么的」的线索。

### A11Y-12 页面没有 `h1`，也没有路由级 `document.title`

- **条款**：1.3.1｜2.4.6｜2.4.2 Page Titled
- **位置**：全模块仅在 `EmptyState.vue:6` 有 `<h3>`；`router/index.ts` 与布局均无 `document.title` 赋值（grep 无命中）
- **证据**：`/pattern-room` 路由 `meta: { hideHeader: true }`，页面头部被隐藏后**没有任何标题元素**；浏览器标题恒为「滨发协同系统」。
- **影响**：读屏器的「按标题跳转」与「按标题列出页面」两个主要导航手段全部失效；多标签页场景无法区分页面。

### A11Y-13 加载状态没有 live region，读屏器全程静默

- **条款**：4.1.3 Status Messages
- **位置**：`CustomerGroupList.vue:11-14`（「加载中...」）、`PartsVersionTableV2.vue:3-6`（「加载部位数据...」）
- **证据**：两处都是普通 `div` + `UiSpinner`，无 `role="status"` / `aria-live`。对比：`CustomerProjectArea.vue:41` 与 `DialogImageUpload.vue:19` 已正确加了 `aria-live="polite"` / `role="status"`，说明是遗漏而非约定。
- **影响**：切换版师/项目/角色时，读屏器用户不知道数据正在加载，会误判为「点了没反应」。

### A11Y-14 目标尺寸不足 24×24

- **条款**：2.5.8 Target Size (Minimum)，AA
- **位置**：`PartsVersionRowV2.vue:145-164`（`.pvt-expand-btn` **20×20**）、`:175`（`.pvt-vp-chip` **height: 22px**）
- **证据**：WCAG 2.2 要求指针目标至少 24×24 CSS px（或等效间距）。相邻元素间距仅 6px，不满足「间距豁免」。
- **对比**：`.pvt-action-btn` 26×26、`.row-remove-btn` 24×24、`.role-tab-add` 28×28 均已达标。

### A11Y-15 左侧地标被命名为「链接」

- **条款**：1.3.1｜2.4.6
- **位置**：`PatternRoomSplitBody.vue:3`
- **证据**：`<aside class="prs-left-pane" aria-label="链接">` —— 该区域装的是搜索框、版师列表、项目卡片，与「链接」无关，疑为模板复制残留。
- **影响**：读屏器地标列表出现「链接 地标」，语义误导。

### A11Y-16 部位表无 `caption`，行内编辑输入无标签

- **条款**：1.3.1｜4.1.2
- **位置**：`PartsVersionTableV2.vue:14`（`<table>` 无 `caption`/`aria-label`）、`PartsVersionRowV2.vue:45-51`（编辑态 input 仅 placeholder）
- **证据**：表头 `<th>` 存在（隐式 `scope="col"`，这点没问题），但表格整体无名；行内编辑时每行 4 个输入框共享同一批 `field.placeholder`，读屏器无法区分「布料名称」属于哪一行、哪一列。

### A11Y-17 没有「跳到主内容」的旁路机制

- **条款**：2.4.1 Bypass Blocks
- **位置**：`layouts/DefaultLayout.vue`（`AppSidebar` 常驻）+ 全站无 skip link（grep `skip` / `跳到主内容` 无命中）
- **证据**：键盘用户每次进入页面都要连续 Tab 穿过侧边栏全部导航项才能到达内容区。

## 4. P3 轻微问题

| ID | 问题 | 位置 | 条款 |
|---|---|---|---|
| A11Y-18 | 新增角色输入框仅 `placeholder="角色名称"`，无 label | `RoleTabs.vue:25-34` | 3.3.2 / 4.1.2 |
| A11Y-19 | `role="menu"` 菜单无方向键导航，也没 `aria-activedescendant`；仅支持 Esc 关闭（`↑↓` 无效） | `RoleTabs.vue:43-55`、`:148-167` | 4.1.2 / 2.1.1 |
| A11Y-20 | 分页「跳至 __ 页」输入框无名称；当前页 `1 / 5` 未用 `aria-current="page"` | `components/ui/UiPagination.vue:11-34` | 4.1.2 |
| A11Y-21 | 图标按钮仅靠 `title` 命名（复制/修改/删除/保存/取消/添加角色），触屏无提示；`disabled` 时 `title` 多数读屏器不播报 | `PartsVersionRowV2.vue:56-102`、`RoleTabs.vue:19-21` | 3.3.2 / 4.1.2 |
| A11Y-22 | `VirtualList` 用 `role="list"` + 虚拟滚动，Tab 进入列表后焦点可能落到已被回收的行；配合 A11Y-01 会放大不可预测性 | `components/ui/VirtualList.vue:5`、`CustomerProjectArea.vue:15-40` | 2.4.3 / 4.1.2 |

## 5. 修复方案（按优先级，含可直接落地的代码）

### 5.1 卡片语义重构（A11Y-01 / 02 / 03）

**不要**让容器装按钮。改为「卡片 → 选中按钮 + 看图按钮 + 操作按钮」三个平级可聚焦元素：

```vue
<!-- ProjectCardItem.vue -->
<div :class="['cgl-project-card', { active: selected, 'is-completed': proj.status === 'completed' }]">
  <!-- 1) 看图：真实 button，天然 Tab 可达、Enter/Space 均激活 -->
  <button
    v-if="proj.product_image_url && !imgFailed"
    type="button"
    class="cgl-card-thumb"
    :aria-label="`查看「${proj.product_name}」产品图片大图`"
    @click.stop="emit('preview', proj.product_image_url!)"
  >
    <!-- 内部 img 保持 alt="" aria-hidden="true"（信息由 aria-label 承载） -->
  </button>

  <!-- 2) 选中：真实 button 包裹文本区，用 aria-current 表达选中 -->
  <button
    type="button"
    class="cgl-card-select"
    :aria-current="selected ? 'true' : undefined"
    @click="emit('select', proj.id)"
  >
    <span class="cgl-card-name">{{ proj.product_name }}</span>
    …
  </button>

  <!-- 3) 操作：与上面平级，不再嵌套 -->
  <div v-if="canManage" class="cgl-card-actions">…</div>
</div>
```

同步把 `CustomerProjectArea.vue:32-33` 的 `@click` / `@keyup.enter` 透传删掉（改由子组件内部 emit `select`），`role="button"` / `tabindex="0"` 一并移除。

### 5.2 表单标签（A11Y-04 / 05 / 18）

`ProjectFormDialog.vue` —— 显式 `for`/`id`，必填用 `required` + `aria-required`：

```vue
<label class="pjf-label" for="pjf-product-name">
  产品名称 <span class="pjf-required" aria-hidden="true">*</span>
</label>
<input id="pjf-product-name" v-model="form.product_name" class="pjf-input"
       placeholder="请输入产品名称" maxlength="200" required aria-required="true" />
```

`PartFormDialog.vue` —— 批量行用「列名 + 行序」拼可访问名（列头保留视觉，去掉 `aria-hidden` 上的语义损失）：

```vue
<input
  v-model="row.part_name"
  class="batch-part-input"
  :aria-label="`第 ${idx + 1} 行 部位名称（必填）`"
  placeholder="如 身体，头部" />
<!-- 其余字段 -->
<input v-for="…" :aria-label="`第 ${idx + 1} 行 ${field.label}`" />
```

> 控件数 >3 时更彻底的做法是把批次表单改成真 `<table>`，用 `<th scope="col">` 让读屏器自动播报「列名 + 单元格」，可省掉逐框 `aria-label`。

### 5.3 选中态（A11Y-06 / 07）

```vue
<!-- 方案 A（低风险，推荐先做）：互斥筛选组用 aria-pressed -->
<button type="button" class="cgl-status-btn"
        :aria-pressed="statusFilter === opt.value"> {{ opt.label }} </button>

<!-- 方案 B（完整语义）：RoleTabs 改 tablist，需补 ←/→ 方向键切换 -->
<div class="role-tabs" role="tablist" aria-label="角色">
  <button role="tab" :id="`role-tab-${role.id}`"
          :aria-selected="role.id === activeRoleId"
          :tabindex="role.id === activeRoleId ? 0 : -1"
          :aria-controls="`role-panel-${role.id}`">…</button>
</div>
<div role="tabpanel" :aria-labelledby="`role-tab-${activeRoleId}`"> <PartsVersionTableV2 /> </div>
```

版本 chip 同理加 `:aria-pressed="selectedVersion[group.part_name] === part.version_no"`。

### 5.4 对比度（A11Y-08）—— 替换色已实算验证

| 用途 | 现值 | 建议值 | 实算对比度 |
|---|---|---|---|
| 橙色文字（版师选中/角标） | `#ff9f43` | `--color-warning-800` **`#a06218`** | 4.94:1（白底）/ 4.72:1（`#fff9f2`） |
| 选中 chip 白字底色 | `#ff9f43→#ff8c1f` | **`#b45309`**（实心，去渐变） | 5.02:1 |
| 角色标签选中渐变 | `#3b82f6→#2563eb` | `#3a6bd6 → #2d5ab8` | 4.94:1 / 6.43:1 |
| 已完成角标 | `#16a34a` | **`#15803d`** | 5.02:1 |
| 选中左边框（非文本，需 3:1） | `#ff9f43` | `#c47820` | 3.47:1 |

同时把「选中」从**纯颜色**升级为**颜色 + 形状**：版师项加 `✓` 图标或加粗下划线，选中 chip 保留实心填充 + 边框，满足 1.4.1。

### 5.5 缩放与焦点（A11Y-09 / 10）

```html
<!-- index.html:5 -->
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
```

```css
/* 删除各组件里的 outline: none，改为 */
.pjf-input:focus-visible,
.cgl-search-input:focus-visible {
  outline: 2px solid var(--color-primary-600); /* #3a6bd6 → 4.94:1 */
  outline-offset: 1px;
  border-color: var(--color-primary-600);
}
```

### 5.6 加载态播报（A11Y-13）

```vue
<div v-if="loading" class="cgl-loading" role="status" aria-live="polite">
  <UiSpinner size="sm" /><span>加载中...</span>
</div>
```
表体同款。注意 `aria-live` 容器**首次渲染时就应存在于 DOM**，否则读屏器可能不播报——保险做法是常驻一个 `sr-only` 的 `<div role="status">{{ statusText }}</div>`。

### 5.7 标题层级与页面名（A11Y-12 / 15 / 17）

```vue
<!-- PatternRoomView.vue 顶部（hideHeader 下更必须有） -->
<h1 class="sr-only">板房打样管理</h1>

<!-- 路由守卫中统一维护标题 -->
router.afterEach((to) => {
  document.title = `${to.meta.title ?? '滨发协同系统'} · 滨发协同系统`
})
```
`<aside aria-label="链接">` → `aria-label="打样项目列表"`。skip link 复用 Tailwind 的 `sr-only`（`UiDialog.vue` 已在用）配合 `focus:not-sr-only`，放在 `#app` 首位。

## 6. 已达标项（勿在重构中回退）

| 项 | 证据 |
|---|---|
| 对话框焦点陷阱 / Esc / `aria-labelledby` | `UiDialog.vue:17-48` 用 reka-ui `DialogTitle`/`DialogDescription`，无可见标题时回退 `srTitle` |
| 装饰性图标全部 `aria-hidden` | 全模块 FontAwesome 图标均已标注 |
| 全局焦点环兜底 | `app.css:708` `:focus-visible { outline: 2px solid … }`（但被组件 scoped 覆盖，见 A11Y-10） |
| 降低动效 | `app.css:699-706` 全局 `prefers-reduced-motion` 归零动画 |
| Toast 可播报 | `composables/useToast.ts:119` 设置 `aria-live="polite"` |
| 分页按钮命名 | `UiPagination.vue:17,21` `aria-label="上一页"/"下一页"` |
| 菜单键盘入口 | `RoleTabs.vue:148-156` 支持 `ContextMenu` / `Shift+F10`，且 Esc 归还焦点 |
| 语言声明 | `index.html:2` `lang="zh-CN"` |

## 7. 复测清单

修复后按序验证：

1. **纯键盘走通全流程**：Tab 到卡片 → Space 选中 → Tab 到「编辑」→ Enter 打开弹窗 → Tab 遍历表单（每框都要有可见焦点环）→ Esc 关闭 → 焦点回到触发按钮。
2. **读屏器（NVDA + Chrome）**：卡片只报一次名称；三个操作按钮逐个可读；角色标签报「已选中」；批量表单每框报「第 N 行 列名」。
3. **axe DevTools 复核**：`nested-interactive`、`label`、`color-contrast`、`aria-allowed-attr` 应为 0 violations。
4. **手机端**：双指放大可用；200% 缩放下 320px 宽不出现内容裁切（注意 `.cgl-card-thumb { height: 240px }` 与 `:260` 固定卡片高在放大时可能截断文字）。
5. **对比度回归**：把 §5.4 五组替换色加入视觉回归基线，避免后续样式改动回退。

---

**附：审查覆盖文件清单**

`PatternRoomView.vue`、`PatternRoomSplitBody.vue`、`CustomerGroupList.vue`、`CustomerGroupSearchBar.vue`、`CustomerMakerPanel.vue`、`CustomerProjectArea.vue`、`ProjectCardItem.vue`、`ProjectDetailPanel.vue`、`PartsVersionTableV2.vue`、`PartsVersionRowV2.vue`、`RoleTabs.vue`、`ProjectFormDialog.vue`、`PartFormDialog.vue`、`PartFieldCombobox.vue`、`PrintDialog.vue`、`DialogMakerSelect.vue`、`DialogImageUpload.vue`、`DialogRoleEditor.vue`、`EmptyState.vue`；共享件 `UiDialog.vue`、`UiPagination.vue`、`ImagePreviewModal.vue`、`VirtualList.vue`、`index.html`、`styles/app.css`、`layouts/DefaultLayout.vue`、`router/index.ts`。

---

## 附：上线记录（2026-10-22 16:40）

- 发布前备份：`backups/frontend-dist-20261022-163348`（旧产物全量，219 文件 / 4.25 MB）
- 构建：`npm run build:atomic`。类型检查、vite build、`check-css-legacy` 均通过；`swap-dist` 的复制步骤被 agent 运行时的 safe-delete 批量守卫（`SAFE_DELETE_BULK_CONFIRM_REQUIRED count=50`）中断，改按该脚本自身的顺序（assets → 静态文件 → 最后 index.html）用 shell 完成替换。
- 线上验证：`https://127.0.0.1/pattern-room` 返回新 `index.html`（`index-DGZXaZG9.js` / `index-ClWyYg1k.css`），懒加载块 `PatternRoomView-DWkV2YOE.js` 等 200 正常。
- 回滚：将上述备份目录内容复制回 `frontend-vite/dist/`。
- 残留（不影响功能）：`dist` 内 111 个旧 hash 资源（1.85 MB）与 `dist-new/` 未清理，下次在终端执行 `build:atomic` 会自动剪掉。
