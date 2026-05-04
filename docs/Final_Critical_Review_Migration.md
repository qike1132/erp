# Shadcn-Vue + PrimeVue Unstyled 混合方案：最终批判性审查

## 0. 审查立场

本文不预设结论，而是以**反对派视角**逐一攻击混合方案，只有经得住攻击的方案才值得采用。

---

## 1. 攻击点 1: 两个库共存的技术风险

### 1.1 冲突场景分析

| 风险点 | 具体问题 | 严重度 | 实际影响 |
|--------|---------|--------|---------|
| 全局注册冲突 | PrimeVue 需要 `app.use(PrimeVue)` 注册，Shadcn-Vue 通过 unplugin 自动注册 | 低 | 两者注册机制不冲突，PrimeVue 注册的是自己的组件前缀 `P`/`Prime`，Shadcn-Vue 用 `Ui` |
| CSS 优先级 | 两者都用 Tailwind 类名，可能类名重复 | 低 | Tailwind 类名是全局的，同一类名指向同一样式，不会冲突 |
| DOM 事件冒泡 | PrimeVue 的 Dialog/Overlay 可能与 Shadcn-Vue 的 Dialog/Overlay 在 z-index 上冲突 | **中** | 两个库都有自己的 Portal/Overlay 管理，可能出现遮罩层叠加问题 |
| Tree Shaking | 两个库各自独立 tree-shake | 低 | 按需引入，不影响 |
| TypeScript 类型 | PrimeVue 和 Shadcn-Vue 各自生成类型 | 低 | 两者命名空间不同，不冲突 |
| Reka UI 重复打包 | Shadcn-Vue 底层依赖 Reka UI，PrimeVue 不依赖 | 无 | 无重复 |

**结论**: 技术共存风险**可控**，唯一需注意 z-index 和 Overlay 层叠问题，可通过统一的 z-index 管理策略解决。

### 1.2 包体积影响

| 库 | 预估 gzip 体积 | 说明 |
|----|----------------|------|
| Shadcn-Vue (copy-paste, 10 个组件) | ~15KB | 仅引入使用的组件代码 + Reka UI 按需部分 |
| PrimeVue Unstyled (5 个 ERP 组件) | ~40KB | DataTable + Column + AutoComplete + DatePicker + Form |
| Reka UI (现有) | ~8KB | 当前已使用的 6 个组件部分 |
| **总计增量** | **~47KB** | 相比当前仅增加 PrimeVue 部分 |

**结论**: 包体积增量可接受。PrimeVue Unstyled 模式下不包含任何 CSS，体积比 styled 模式更小。

---

## 2. 攻击点 2: 为什么不直接用 PrimeVue Unstyled 覆盖全部?

这是最关键的反问。混合方案的复杂度 > 单一库方案，需要充分论证为什么不用 PrimeVue 做全部。

### 2.1 Shadcn-Vue 的不可替代性

| 维度 | PrimeVue Unstyled | Shadcn-Vue | 差异是否关键 |
|------|-------------------|-----------|-------------|
| Dialog 原语 | PrimeVue Dialog (功能完整) | Reka UI DialogRoot (当前已用) | **不关键** — PrimeVue Dialog 可以完全替代 |
| Combobox | PrimeVue AutoComplete (远程搜索) | Reka UI ComboboxRoot (当前已用) | **不关键** — AutoComplete 功能更全 |
| Checkbox | PrimeVue Checkbox | Reka UI CheckboxRoot | **不关键** — 功能等价 |
| Tabs | PrimeVue Tabs/TabList/Tab/TabPanels | Reka UI TabsRoot/TabsList/TabsTrigger/TabsContent | **不关键** — 结构更接近当前项目 |
| 迁移成本 | 需重写所有 6 个组件的内部实现 | 6 个组件几乎零成本迁移 (同源) | **关键** — 这是混合方案存在的核心理由 |

### 2.2 如果只用 PrimeVue Unstyled

**迁移路径**: 6 个 Reka UI 组件 → PrimeVue Unstyled 对应组件

| 当前组件 | PrimeVue 替代 | 迁移复杂度 | 与当前行为差异 |
|----------|-------------|-----------|--------------|
| UiDialog (Reka DialogRoot) | PrimeVue Dialog + PT | 中 | 遮罩/关闭/动画需通过 PT 重新实现 |
| UiSelect (Reka ComboboxRoot) | PrimeVue AutoComplete + PT | 中 | 搜索逻辑需重写，但功能更强 |
| UiCheckbox (Reka CheckboxRoot) | PrimeVue Checkbox + PT | 低 | 功能等价 |
| UiTabs (Reka TabsRoot) | PrimeVue TabList/Tab/TabPanels + PT | 中 | 结构不同但功能等价 |
| UiTabTrigger (Reka TabsTrigger) | PrimeVue Tab + PT | 低 | 功能等价 |
| UiTabContent (Reka TabsContent) | PrimeVue TabPanel + PT | 低 | 功能等价 |

**额外 PT 配置工作量**: 每个组件需编写 PT Tailwind preset，约 20-30 行/组件，6 个组件共 ~150 行 PT 配置。

### 2.3 单一 PrimeVue 方案的真实成本

| 维度 | 混合方案 | 纯 PrimeVue Unstyled |
|------|---------|---------------------|
| 6 个基础组件迁移 | **~0 行改动** (Shadcn-Vue 同源 Reka UI) | ~150 行 PT 配置 + ~200 行组件重写 |
| ERP 组件 | PrimeVue Unstyled | PrimeVue Unstyled |
| 维护的库数量 | 2 个 | 1 个 |
| 学习成本 | 2 套 API | 1 套 API |
| 团队约定复杂度 | 需要明确 "哪些用 Shadcn，哪些用 PrimeVue" | 无需约定 |
| 长期一致性 | 可能出现 "这个组件该用哪个库" 的团队争议 | 无争议 |

**关键判断**: 纯 PrimeVue Unstyled 方案的额外成本约 **350 行代码 + 1 次 6 组件重写**，换来的是**单一库的架构简洁性**。

---

## 3. 攻击点 3: Volt 的成熟度问题

### 3.1 Volt 当前状态

| 维度 | 状态 |
|------|------|
| 版本 | 2025 年底发布，仍为早期版本 |
| 组件数 | 50+ (vs PrimeVue 90+) |
| 生产案例 | 官网展示 demo，未见大规模生产案例 |
| 文档 | 基础文档已有，但缺少深入指南 |
| 维护方 | PrimeTek (商业公司) |

**风险**: Volt 可能不够成熟，直接用于生产有稳定性风险。

**缓解**: 可以不用 Volt，直接使用 PrimeVue Unstyled + 手写 PT 配置。Volt 本质是 PT 配置的预制包装，不使用 Volt 不影响 PrimeVue Unstyled 的核心功能。

**结论**: **混合方案不应依赖 Volt**。正确做法是用 PrimeVue Unstyled 核心 + 手写 PT 配置，Volt 仅作为参考。

---

## 4. 攻击点 4: Shadcn-Vue 的 Copy-Paste 模式风险

### 4.1 Copy-Paste 模式的长期问题

| 问题 | 影响 | 缓解 |
|------|------|------|
| 上游 bug 修复不自动同步 | 需手动 diff 合并 | 项目有 30 个自定义 Ui* 组件，已经不依赖自动更新 |
| 组件漂移 | 本地修改与上游 diverge | 当前项目已深度定制，漂移已发生且可接受 |
| 版本锁定 | 无法通过 npm update 获取修复 | Shadcn-Vue 底层 Reka UI 可通过 npm 更新 |

**关键认知**: 当前项目已经采用 Copy-Paste 模式！30 个 Ui* 组件全在 `src/components/ui/` 下，不是从 npm 引入的。Shadcn-Vue 的 Copy-Paste 模式与当前架构完全一致，不是新风险。

**结论**: 此攻击点不成立。

---

## 5. 攻击点 5: Shadcn-Vue 的 DataTable 不是真正的 DataTable

### 5.1 Shadcn-Vue DataTable 的真实面貌

Shadcn-Vue 的 DataTable 是**基于 TanStack Table 的组合式方案**，不是预封装组件:

```
需要手动组装: Table + TableHeader + TableRow + TableHead + TableBody + TableCell
需要手动引入: @tanstack/vue-table
需要手动实现: 排序/筛选/分页/行选择 的逻辑
需要手动连接: 每个功能需要写 columnDef + 事件处理
```

对比 PrimeVue DataTable:

```
<DataTable :value="data" paginator :rows="10" sortMode="multiple">
  <Column field="name" header="Name" sortable />
  <Column field="price" header="Price" sortable />
</DataTable>
```

| 维度 | Shadcn-Vue + TanStack Table | PrimeVue DataTable |
|------|---------------------------|-------------------|
| 声明式程度 | 低 (需手动组合) | **高 (一个组件搞定)** |
| 排序 | 需写 columnDef + getSortedRowModel | `<Column sortable>` |
| 分页 | 需写 getPaginationRowModel + 手动分页 UI | `paginator :rows="10"` |
| 行选择 | 需写 getFilteredRowModel + checkbox 模板 | `selectionMode="multiple"` |
| 虚拟滚动 | 需引入 vue-virtual-scroller + 手动集成 | `virtualScrollerOptions` |
| 内联编辑 | 需手写 cell renderer + editor 模板 | `<Column editor>` |
| Excel 导出 | 不支持 | `exportCSV()` |
| 列固定 | 不支持 | `<Column frozen>` |
| 列分组 | 需手写 colspan 逻辑 | `<ColumnGroup>` |
| 学习曲线 | **陡峭** (TanStack Table API 复杂) | **平缓** (声明式 API) |
| 灵活性 | **极高** (完全控制) | 高 (PT + template 自定义) |

**关键发现**: Shadcn-Vue 的 DataTable 本质上是 **HTML table + TanStack Table 逻辑层**，对 ERP 场景而言，**开发效率和功能覆盖度远不如 PrimeVue DataTable**。

这意味着: 如果选混合方案，DataTable 必须用 PrimeVue，不能用 Shadcn-Vue 的方案。这进一步削弱了 Shadcn-Vue 在 ERP 场景中的价值。

---

## 6. 攻击点 6: PrimeVue PT 配置的真实复杂度

### 6.1 一个组件的 PT 配置有多复杂?

以 **DataTable** 为例，实现 "Plush Cute" 风格需要配置的 PT sections:

```typescript
const dataTablePT = {
  root: 'rounded-2xl overflow-hidden shadow-sm border border-border-light',
  header: 'bg-surface px-6 py-4 border-b border-border-light',
  table: 'w-full',
  thead: 'bg-surface',
  headercell: 'px-4 py-3 text-sm font-semibold text-text-secondary border-b border-border',
  tbody: 'bg-surface-card',
  row: ({ context }) => ({
    class: [
      'transition-all duration-200',
      context.selected ? 'bg-primary-50' : '',
      'hover:bg-ocean-light/30',
    ]
  }),
  bodycell: 'px-4 py-3 text-sm text-text border-b border-border-light',
  footer: 'px-6 py-3 bg-surface border-t border-border-light',
  paginator: {
    root: 'flex items-center justify-between px-6 py-3 bg-surface border-t border-border-light',
    pages: 'flex gap-1',
    pagebutton: ({ context }) => ({
      class: [
        'w-8 h-8 rounded-xl text-sm font-medium transition-all duration-200',
        context.active ? 'bg-gradient-primary text-white shadow-sm' : 'text-text-secondary hover:bg-ocean-light/30',
      ]
    }),
  },
  emptymessage: 'px-4 py-8 text-center text-text-muted',
}
```

**约 30 行配置一个 DataTable 的核心外观**。

### 6.2 全部组件的 PT 配置量估算

| 组件 | PT 配置行数 (估算) | 说明 |
|------|-------------------|------|
| DataTable + Column | ~40 行 | 最复杂，含子组件 |
| AutoComplete | ~25 行 | 输入框 + 下拉 + 选项 |
| DatePicker | ~25 行 | 输入框 + 日历 + 导航 |
| Form + Field | ~15 行 | 表单布局 + 错误信息 |
| Drawer | ~15 行 | 遮罩 + 面板 |
| CascadeSelect | ~20 行 | 触发器 + 层级面板 |
| TreeSelect | ~20 行 | 触发器 + 树面板 |
| **合计** | **~160 行** | 可提取为全局 PT preset |

**结论**: PT 配置量不大，但需要**理解每个组件的 section 结构**。学习曲线存在，但一次性投入。

---

## 7. 攻击点 7: 保持 Reka UI + 按需扩展 是否更简单?

### 7.1 当前架构的真实问题

| 问题 | 严重度 | 仅靠 Reka UI 能否解决 |
|------|--------|---------------------|
| UiTable 空壳 | 高 | 不能 — Reka UI 没有 Table 组件 |
| 无 DataTable | 高 | 不能 — 需自建或用 TanStack Table |
| 无远程搜索选择器 | 高 | 不能 — 需自建 |
| 无日期范围选择 | 中 | 不能 — 需自建 |
| 无级联选择 | 中 | 不能 — 需自建 |
| 无表单验证 | 中 | 可用 VeeValidate/Zod，但需手写集成 |
| 无抽屉 | 低 | 需自建 (当前已自建 468 行) |
| Dialog/Checkbox/Tabs | 无问题 | 当前已用 Reka UI 实现，无痛点 |

### 7.2 保持 Reka UI + 按需自建的真实成本

| 需自建的组件 | 估算代码量 | 难度 | 对标 PrimeVue |
|-------------|-----------|------|-------------|
| DataTable (排序/分页/选择/虚拟滚动) | ~500 行 | **极高** | 1 行 `<DataTable>` |
| 远程搜索选择器 | ~200 行 | 高 | `<AutoComplete>` |
| 日期范围选择器 | ~300 行 | 高 | `<DatePicker selectionMode="range">` |
| 级联选择器 | ~250 行 | 高 | `<CascadeSelect>` |
| 表单验证框架 | ~150 行 | 中 | `<Form>` + Zod |
| 抽屉 (替代 468 行自建) | ~50 行 | 低 | `<Drawer>` |
| **合计** | **~1450 行** | | |

**对比**: 使用 PrimeVue Unstyled 的话，这些组件的 PT 配置总量约 **160 行**，差距近 **9 倍**。

**结论**: 保持 Reka UI + 自建方案在基础交互上没问题，但 ERP 核心组件的自建成本极高，且自建质量难以与 PrimeVue 这种经过多年迭代的商业级组件相比。

---

## 8. 终极对比: 三个可行方案

经过以上 7 轮攻击，淘汰了 Element Plus、Naive UI、Ant Design Vue 等方案后，剩余三个可行方案:

### 8.1 方案 A: 纯 PrimeVue Unstyled (单一库)

```
架构: PrimeVue Unstyled + PT 配置 + Tailwind CSS v4
基础交互: PrimeVue Dialog/Checkbox/Tabs/Select + PT
ERP 组件: PrimeVue DataTable/AutoComplete/DatePicker/CascadeSelect + PT
```

| 优点 | 缺点 |
|------|------|
| 单一库，无架构复杂度 | 6 个 Reka UI 组件需重写 (~350 行) |
| 一致的 PT 配置模式 | Dialog/Select 的交互需从 Reka UI 迁移到 PrimeVue API |
| 长期维护简单 | PT 学习曲线一次性投入 |
| 无"该用哪个库"的团队争议 | PrimeVue Tabs 结构与当前不同，视图层需调整 |

### 8.2 方案 B: Shadcn-Vue + PrimeVue Unstyled (混合)

```
架构: Shadcn-Vue (基础交互) + PrimeVue Unstyled (ERP 数据) + Tailwind CSS v4
基础交互: Shadcn-Vue Dialog/Checkbox/Tabs/Select (同源 Reka UI，零迁移)
ERP 组件: PrimeVue DataTable/AutoComplete/DatePicker/CascadeSelect + PT
```

| 优点 | 缺点 |
|------|------|
| 6 个 Reka UI 组件零迁移成本 | 两个库，需团队约定分工 |
| 基础交互行为零变化 | 两套 API 模式共存 (Shadcn Vue 组件式 vs PrimeVue PT 式) |
| 各取所长 | z-index/Overlay 管理需统一 |
| Shadcn-Vue 代码在项目中，完全可控 | Shadcn-Vue 的 DataTable 不是真 DataTable，ERP 组件必须用 PrimeVue |

### 8.3 方案 C: 保持 Reka UI + 按需自建

```
架构: Reka UI + 自建组件 + Tailwind CSS v4
基础交互: 当前 6 个 Reka UI 组件 (不变)
ERP 组件: 自建 DataTable/AutoComplete/DatePicker 等 (~1450 行)
```

| 优点 | 缺点 |
|------|------|
| 零迁移成本 | 自建 ~1450 行代码，质量难保证 |
| 无新依赖 | DataTable 虚拟滚动/列固定/导出 几乎不可能实现 |
| 当前架构不变 | 未来每个新组件都需自建 |

---

## 9. 最终裁定

### 9.1 方案对比评分 (满分 10)

| 评估维度 | 权重 | A: 纯 PrimeVue | B: 混合方案 | C: 保持现状 |
|----------|------|---------------|-----------|-----------|
| ERP 组件功能 | 25% | 9 | 9 | 3 |
| 迁移成本 (反) | 20% | 6 | **9** | 10 |
| 架构简洁性 | 15% | **9** | 6 | 8 |
| 设计系统兼容性 | 15% | 9 | **9** | 9 |
| 长期维护性 | 15% | **9** | 7 | 4 |
| 团队认知负担 | 10% | 7 | 5 | **9** |
| **加权总分** | 100% | **8.15** | **7.70** | **6.25** |

### 9.2 裁定结果

**纯 PrimeVue Unstyled (方案 A) 以微弱优势胜出。**

核心理由:

1. **混合方案的核心卖点 — "6 个 Reka UI 组件零迁移" — 实际价值被高估了**。这 6 个组件的 PrimeVue 迁移量约 350 行代码，是一次性工作。而为了省这 350 行，引入了两个库共存的长期架构复杂度，不值得。

2. **Shadcn-Vue 在 ERP 场景中的价值有限**。它的 DataTable 是 TanStack Table 手动组装 (不是真 DataTable)，Select/AutoComplete/DatePicker 都不如 PrimeVue。真正对 ERP 有价值的组件必须来自 PrimeVue，Shadcn-Vue 只提供了最基础的 Dialog/Checkbox/Tabs。

3. **单一库的架构简洁性是长期优势**。无需团队约定 "哪些用 Shadcn，哪些用 PrimeVue"，所有组件用同一套 PT 配置模式，新人只需学一套 API。

4. **但差距是微弱的 (8.15 vs 7.70)**。如果团队特别看重 "基础交互零变化" 或对 Reka UI 有深度依赖，混合方案仍然是合理选择。

### 9.3 推荐的实施路径 (方案 A)

```
阶段 1: 基础设施 (1-2 天)
├── 安装 PrimeVue + 配置 Unstyled 模式
├── 编写 "Plush Cute" 全局 PT preset (~160 行)
└── 保留 Tailwind CSS v4 不变

阶段 2: 替换 6 个 Reka UI 组件 (3-5 天)
├── UiDialog → PrimeVue Dialog + PT (保持 UiDialog 包装接口)
├── UiCheckbox → PrimeVue Checkbox + PT
├── UiTabs/UiTabTrigger/UiTabContent → PrimeVue Tabs/Tab/TabPanels + PT
├── UiSelect → PrimeVue AutoComplete + PT (功能升级)
└── 验证所有视图的交互不变

阶段 3: 替换 ERP 关键组件 (5-7 天)
├── 各视图手写表格 → PrimeVue DataTable + PT
├── 自建 autocomplete → PrimeVue AutoComplete + PT
├── 原生日期控件 → PrimeVue DatePicker + PT
├── 自建 PlanDetailDrawer → PrimeVue Drawer + PT
└── 移除 UiTable 空壳组件

阶段 4: 清理 (1-2 天)
├── 移除 reka-ui 依赖
├── 移除 @internationalized/date
└── 更新 components.d.ts
```

### 9.4 如果选混合方案 (方案 B)

适用条件:
- 团队对 Reka UI 有深度依赖，不想改动基础交互
- 项目短期内不会新增大量 ERP 组件
- 团队规模小，"哪些用哪个库" 的争议可控

分工规则:
```
Shadcn-Vue 负责: Dialog, Checkbox, Tabs, Switch, Button, Input, Toast
PrimeVue Unstyled 负责: DataTable, AutoComplete, DatePicker, CascadeSelect, Drawer, Form
自定义组件保留: UiStatusBadge, UiFilterBar, UiStatCard, UiPageHeader
```
