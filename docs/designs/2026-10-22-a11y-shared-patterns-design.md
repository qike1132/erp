# 无障碍共享范式设计（选中态 / 加载态 / 表单标签）

- 日期：2026-10-22
- 来源：`docs/pattern-room-a11y-audit-2026-10-22.md` 的 22 项问题中，3 类反复出现（A11Y-06/07 选中态、A11Y-13 加载态、A11Y-04/05/18 表单标签）
- 结论：**只补共享层缺的 3 件，不重造已有件**

## 1. 为什么不是「逐页补」

同一类缺陷在 `/pattern-room` 内重复出现 3~5 次。逐页补的代价是：每页各写一遍 `aria-pressed` 字面量、各自拼 `id`，下次新增页面照旧漏。范式法把「正确」收敛到唯一出口，页面只消费 API —— 漏写的成本从「静默不合规」变成「编译/测试就报错」。

## 2. 决策表：先查有没有，再决定用哪个

| 场景 | 用什么 | 不要用 |
|---|---|---|
| 点击切换**下方面板内容**（角色页签、订单页签） | `components/ui/UiTabs.vue` + `UiTabTrigger` + `UiTabContent` | 自己写 `<button>` + `:class="active"` |
| 一组**互斥筛选选项**（状态胶囊、版师列表、版本 chip） | `useSelectionA11y()` 的 `itemAttrs()` | 手写 `aria-pressed="true"` 字面量 |
| 异步取数中/完成的状态提示 | `components/ui/UiLoadingStatus.vue` | 裸 `div` + 文字、`v-if` 包住的提示 |
| 带可见标签的表单字段 | `components/ui/UiFormField.vue` | 手写 `<label>` 不写 `for` |
| 无可见标签的搜索框 | 控件上 `aria-label` + 外层 `role="search"` | 只给 `placeholder`（placeholder 会消失） |
| 装饰性图标 | `aria-hidden="true"` | 让图标进可访问名 |

**已在共享层、不要重造的两处**（这次审查确认）：

- `UiTabs` 内部是 reka-ui `TabsRoot`，已自带 `role="tablist"/"tab"/"tabpanel"`、`aria-selected` 与 ←/→ 方向键。要 tab 语义就用它。
- `UiInput` / `SearchBox` 已把 `aria-label` 兜底成 `label || placeholder`。但它们不产出**可见**标签与 `for` 关联，也不处理 hint/error —— 这才是 `UiFormField` 要补的位。

## 3. 范式一：选中态 `useSelectionA11y`

`src/composables/useSelectionA11y.ts`

```ts
const { itemAttrs, isActive } = useSelectionA11y(() => props.statusFilter)

<button v-for="opt in OPTIONS" :key="opt.value" v-bind="itemAttrs(opt.value)" type="button">
```

**契约**

1. **只返回字符串 `'true' | 'false'`**，不返回 boolean。`aria-pressed` 属性「缺省」表示「这不是切换按钮」，与「是切换按钮但未按下」是两种语义；返回 boolean 时任何一环（`v-bind` 合并、attrs 透传、SSR 水合）把它吃成缺省，语义就静默降级了。
2. **只能挂在 `<button>`（或 `role="button"`）上**。挂到普通 `div` 上会让读屏器读出「切换按钮」却没有键盘行为，比不加还糟。
3. 互斥组建议包一层 `role="group"` + `aria-label`，让读屏器能报出「按项目状态筛选 组，进行中 已按下」。

**何时别用它**：切换的是**面板内容**时用 `UiTabs`（tablist + `aria-selected` + 方向键），`aria-pressed` 表达不出「控制着哪块区域」。

## 4. 范式二：加载态 `UiLoadingStatus`

`src/components/ui/UiLoadingStatus.vue`

```vue
<UiLoadingStatus :loading="loading" label="加载中…" />
```

**三条硬契约**（违反任一条就白做）

1. **容器必须常驻 DOM，不能用 `v-if` 包**。首次渲染就得在无障碍树里，否则「先挂载、再填字」某些读屏器不播报。
2. `role="status"` + `aria-live="polite"` + `aria-atomic="true"` 同时写全（`role="status"` 隐含 polite，但旧读屏器认显式属性）。
3. **live region 自身绝不能加 `aria-busy`**。部分实现会把播报推迟到 busy 变 `false`，等于把「加载中」这句话吞掉。这是最容易被顺手"优化"错的地方，测试里专门有一条守着。

空闲时用 `.is-idle` 剪裁塌陷（`position:absolute` + `clip-path`，**不是** `display:none`）—— 留在无障碍树里，视觉不占位。

**顺带修掉的既有缺陷**：`UiSpinner` 的模板是 `<span><slot>加载中…</slot></span>`，默认文案恒在。原 `CustomerGroupList` 写 `<UiSpinner size="sm" /><span>加载中...</span>`，实际渲染出「加载中…加载中...」两个文案；且 `UiSpinner` 根本没有 `size` prop（全仓十几处 `size="sm"` 都不生效，落到 HTML 属性上了）。改用 `UiLoadingStatus` 后两问题一并消失。

> `UiSpinner` 自身未改（存量调用点太多）。若要清理，单独一个任务：给它补 `size` prop 并去掉默认插槽文案。

## 5. 范式三：表单字段 `UiFormField`

`src/components/ui/UiFormField.vue`

```vue
<UiFormField v-slot="field" label="产品名称" required hint="不超过 200 字" :error="errors.product_name">
  <input v-bind="field" v-model="form.product_name" class="pjf-input" placeholder="请输入产品名称" />
</UiFormField>
```

**契约**

1. 控件 id 由组件生成（`useId()`），`<label for>` 自动指向它 —— 调用方**不再手写 id**。
2. 必填：同时产出原生 `required`（浏览器校验）与 `aria-required="true"`（读屏播报），`*` 标记 `aria-hidden`（避免念「星号」）。
3. `hint` / `error` 的 id 自动进 `aria-describedby`，顺序 hint → error；空字符串视为未提供（不产生悬空 id 引用）。
4. `error` 存在时置 `aria-invalid="true"` 且渲染块带 `role="alert"`。
5. slot 以 `v-bind="field"` 展开，`input` / `textarea` / `UiSelect` 通用。

**注意**：`useId()` 唯一性范围是**单个 Vue app**。本仓只挂一个 `#app`，够用；将来若同页并存多个 app（微前端/嵌入式），需各自设 `app.config.idPrefix`，否则 id 重复、label 串台。

**不适用**：批量新增部位那种「N 行 × M 列」的表单，逐框包 `UiFormField` 会得到一屏重复标签。正确做法是改成真 `<table>` 用 `<th scope="col">`，或退一步给每框 `aria-label="第 N 行 列名"`。

## 6. 迁移清单（回填顺序 = 风险从低到高）

已完成（2026-10-22 两轮）：

| 位置 | 改动 |
|---|---|
| `views/pattern-room/components/CustomerGroupSearchBar.vue` | 状态胶囊接 `itemAttrs`；外层 `role="search"`；搜索框补 `aria-label`；`:focus` 改 `:focus-visible` 不再压掉全局焦点环 |
| `views/pattern-room/components/CustomerGroupList.vue` | 加载态换 `UiLoadingStatus`（顺带修掉重复文案） |
| `views/pattern-room/components/CustomerMakerPanel.vue` | 版师项接 `selectionItemAttrs` + `role="group"`；项目数改为 `aria-hidden` + `sr-only`「N 个项目」（避免读出孤零零的数字） |
| `views/pattern-room/components/PartsVersionRowV2.vue` | 版本 chip 接 `selectionItemAttrs`；行内编辑输入补 `aria-label="部位 版本 字段名"`；焦点改 `:focus-visible` |
| `views/pattern-room/components/PartsVersionTableV2.vue` | 表体加载换 `UiLoadingStatus`；补 `<caption class="sr-only">` |
| `views/pattern-room/components/CustomerProjectArea.vue` | 测高占位态换 `UiLoadingStatus`（原 `UiSpinner` 的默认插槽文案会重复） |
| `views/pattern-room/components/ProjectFormDialog.vue` | 产品名称/备注改用 `UiFormField`；版师改 `<span id>` + `aria-labelledby`；图片/角色列表的无效 `<label>` 改 `<span>`；焦点改 `:focus-visible` |
| `views/pattern-room/components/PartFormDialog.vue` | 批量行逐框 `aria-label="第 N 行 列名"`；删除按钮 `aria-label="删除第 N 行"`；焦点改 `:focus-visible` |
| `views/pattern-room/components/DialogRoleEditor.vue` | 每个角色输入补 `aria-label="角色名称 N"`；焦点改 `:focus-visible` |
| `views/pattern-room/components/DialogMakerSelect.vue` | 新增 `labelledby` prop；触发按钮补 `aria-expanded` / `aria-controls`；删掉触发按钮与被覆盖输入框的 `outline: none` |
| `views/pattern-room/components/PartFieldCombobox.vue` | 新增 `ariaLabel` prop（`role="combobox"` 此前完全无名）+ `aria-controls` 指向 `listbox`；删掉 `outline: none` |
| `views/pattern-room/components/RoleTabs.vue` | 新增角色输入补 `aria-label`；删掉被覆盖的 `outline: none` |
| `views/pattern-room/components/PatternRoomSplitBody.vue` | 地标 `aria-label="链接"` → `"打样项目列表"` |

本轮结论：`views/pattern-room/` 下 **`outline: none` 已清零**（9 处），焦点指示全部回落全局 `:focus-visible` 2px 环。

待回填：

| 位置 | 用哪个范式 | 对应审查项 | 卡点 |
|---|---|---|---|
| `RoleTabs.vue` 角色页签 | `UiTabs` | A11Y-06 | 右键菜单与内联新增输入嵌在 `TabsList` 里不合法，须先把它们移出列表（或降级为 `aria-pressed` 并接受「不是 tab 语义」） |
| `PartsVersionRowV2.vue` 行内图标按钮 | — | A11Y-21 | 仍只有 `title`，需补 `aria-label`（`title` 在触屏与 disabled 时不播报） |
| `DialogMakerSelect.vue` 候选面板 | — | 新增 | 面板应改 `role="listbox"` + `role="option"` + 方向键漫游 + `aria-activedescendant` |

**不属于这三个范式的项**（单独立项做，别夹带进范式改动）：

- 已完成（2026-10-22 第三轮）：卡片嵌套交互（A11Y-01~03，拆成三个平级可聚焦元素 + 伪元素拉伸热区）、标题层级与页面标题（A11Y-12，`h1.sr-only` + 路由 `meta.title` 驱动 `document.title`）、目标尺寸（A11Y-14，展开键 20→24px、版本 chip 22→24px）、地标命名（A11Y-15）、跳过导航（A11Y-17，`#main-content` 加 `tabindex="-1"` 才能真把焦点移过去）、菜单键盘（A11Y-19）、分页语义（A11Y-20）、虚拟列表（A11Y-22，`aria-setsize`/`aria-posinset` 让读屏器报「第 3 项，共 40 项」而不管只渲染了 10 项）。
- 已完成（2026-10-22 第四轮）：图标按钮命名（A11Y-21）—— 行内复制/修改/删除/保存/取消的 `aria-label` 统一为「动作 + 部位 + 版本」，历史快照行额外带「历史快照，不可操作」；展开键补 `aria-expanded`；版师删除、角色移除、新增角色按钮同理。
- 待决策：角色页签 tablist（A11Y-06）、对比度配色（A11Y-08）、禁止缩放（A11Y-09）——三项都涉及视觉/全局行为变更，需 owner 批准。

## 7. 验收

```bash
cd frontend-vite
TEMP=$(pwd)/.vitest-tmp npx vitest run src/test/a11ySelection.test.ts \
  src/test/UiLoadingStatus.test.ts src/test/UiFormField.test.ts
npx eslint src/components/ui/UiLoadingStatus.vue src/components/ui/UiFormField.vue \
  src/composables/useSelectionA11y.ts src/views/pattern-room/components/
npx vue-tsc --noEmit
```

本次实测：**48 项测试全绿**（含受影响的 `RoleTabs.test.ts`、`patternRoomLayoutPrintMedia.test.ts`）；eslint 0 问题；`vue-tsc --noEmit` 0 错误。

**变异检查已做**（改坏行为 → 测试必须变红）：

| 变异 | 结果 |
|---|---|
| `aria-pressed` 未选中也返回 `'true'` | 8 条中 7 条变红 |
| `aria-live` 改 `off` | 1 条变红（专守该属性） |
| `<label for>` 指向错误 id | 13 条中 4 条变红 |

## 8. 未验证项（如实记录）

- 未在真实浏览器跑 axe / 读屏器：本轮是组件级单测 + 类型检查，**DOM 语义正确性**有保障，但「NVDA 实际念什么」仍需登录态实测。
- 未跑全量 `npm test`（仓内 1000+ 用例）与 CI 三 job；改动均为新增文件 + 2 个 pattern-room 组件，已跑受影响用例。推送前按 AGENTS.md 走 `review_packet.py` + 一次合并评审。
- `UiLoadingStatus` 的视觉与原 `.cgl-loading` 有 8px padding 差异（40px → 32px），不影响功能与对齐。
