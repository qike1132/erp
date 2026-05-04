# 渐进式增强架构 (Keep & Enhance) — 最终判定

## 结论：是最优解

Keep & Enhance 是本项目唯一同时满足 **零风险、高收益、可持续** 三个条件的方案。

---

## 一、Keep & Enhance 的精确定义

```
Keep  = 不动现有 30 个 Ui* 组件 + Reka UI + Tailwind CSS v4 + "Plush Cute" 设计系统
Enhance = 仅在当前能力空白处，用 PrimeVue Unstyled 补充新组件
```

**核心原则**: 不替换任何现有工作代码。只新增。

---

## 二、为什么是最优解 — 基于项目实证

### 2.1 现有组件工作良好，替换无收益

| 组件 | 状态 | 替换的收益 |
|------|------|-----------|
| UiDialog (Reka UI) | 正常工作，17+ 视图使用 | **零** — 功能满足，样式自定义 |
| UiSelect (Reka UI) | 正常工作，6+ 视图使用 | **零** — 简单选择够用 |
| UiCheckbox (Reka UI) | 正常工作，4+ 视图使用 | **零** |
| UiTabs 系列 (Reka UI) | 正常工作，3+ 视图使用 | **零** |
| UiButton/Input/Switch 等 (24 个) | 正常工作 | **零** — 全是自定义 Tailwind |

**替换这 30 个组件的唯一理由是"架构纯洁性"，而非功能需求。在工程决策中，这不够充分。**

### 2.2 真正的痛点是"缺组件"，不是"组件差"

项目实证数据:

| 痛点 | 重复实现次数 | 总代码量 | 影响 |
|------|------------|---------|------|
| 产品搜索 autocomplete | **5 处** | **664 行** 重复代码 | 最大痛点 |
| 自定义 Drawer | 1 处 | **468 行** | 第二大痛点 |
| 手写表格 (不用 UiTable) | **13 个视图** | 大量重复 | 第三大痛点 |
| 双日期选择器 (无范围选择) | **7 个视图** / 9 对 | 每对 2 个组件 | 中等痛点 |
| 自定义搜索输入框 | **8 个视图** | 中等重复 | 中等痛点 |
| `fa-spinner fa-spin` 替代 UiSpinner | **41 处** / 13 视图 | 不一致 | 低痛点 |
| 手写 errorMsg 表单验证 | 多处 | 分散 | 低痛点 |

**这些痛点全部可以通过"新增组件"解决，不需要"替换现有组件"。**

### 2.3 Keep & Enhance vs 竞争方案的实质差异

| 方案 | 现有代码改动 | 新增组件来源 | 风险 |
|------|------------|------------|------|
| **Keep & Enhance** | **零** | PrimeVue Unstyled (仅补缺) | **最低** |
| 纯 PrimeVue Unstyled | 重写 6 个 Reka UI 组件 (~350 行) | PrimeVue Unstyled (全部) | 中 — 现有组件行为需验证 |
| Shadcn-Vue + PrimeVue | 替换 6 个组件封装 | 两个库 | 中 — 两套 API 共存 |
| Element Plus | 重写 30 个组件 + 样式覆盖 | Element Plus | 高 — 设计系统冲突 |
| 保持现状 + 自建 | 零 | 全部手写 (~1450 行) | 高 — 自建质量风险 |

---

## 三、Enhance 清单 — 精确到行号

### 3.1 必须增强 (P0) — 消除最大重复

#### E1: UiAutocomplete — 消除 664 行重复

新建 `src/components/ui/UiAutocomplete.vue`，基于 PrimeVue AutoComplete + PT

**消除目标**:

| 视图 | 当前行数 | 替换后 |
|------|---------|--------|
| StockOutTab.vue | 99 行 autocomplete | ~5 行 `<UiAutocomplete>` |
| CustomerOrderView.vue | 156 行 (2 处) | ~10 行 (2x `<UiAutocomplete>`) |
| CaseStockTab.vue | 99 行 | ~5 行 |
| ProductListView.vue | 163 行 (含键盘导航) | ~5 行 |
| CreateShipmentPlanDialog.vue | 147 行 | ~5 行 |
| **合计** | **664 行 → ~30 行** | **-95%** |

UiAutocomplete 需支持:
- 远程搜索 (debounce + API 调用)
- 自定义选项模板 (条码 + 库存 + 名称)
- 键盘导航 (Arrow/Enter/Escape)
- 多实例 (CreateShipmentPlanDialog 每行一个)

#### E2: UiDrawer — 消除 468 行自建

新建 `src/components/ui/UiDrawer.vue`，基于 PrimeVue Drawer + PT

**消除目标**: PlanDetailDrawer.vue 的 468 行 → 保留业务逻辑 (~60 行)，UI 框架部分 (~408 行) 由 UiDrawer 替代

#### E3: UiDataTable — 统一 13 个视图的表格

新建 `src/components/ui/UiDataTable.vue`，基于 PrimeVue DataTable + PT

这是最复杂的增强，但收益最大:
- 内置排序、分页、行选择
- 统一 13 个视图的表格外观和交互
- 解锁虚拟滚动、列固定、Excel 导出等当前不可能的功能

**注意**: 13 个视图的表格迁移是渐进式的，可以逐个替换，不需要一次性全部迁移。

### 3.2 应该增强 (P1) — 提升体验一致性

#### E4: UiDateRangePicker — 统一 9 对双日期选择器

新建 `src/components/ui/UiDateRangePicker.vue`，基于 PrimeVue DatePicker `selectionMode="range"` + PT

**消除目标**: 7 个视图的 9 对双 UiDatePicker → 各 1 个 `<UiDateRangePicker>`

#### E5: UiSearchInput — 统一 8 个自定义搜索框

新建 `src/components/ui/UiSearchInput.vue`，基于现有 UiInput + 搜索图标 + 清除按钮

**不依赖 PrimeVue**，这是纯 Tailwind 增强。基于现有 UiInput 扩展。

#### E6: UiSpinner 替代 fa-spinner — 统一 41 处

将 `<i class="fas fa-spinner fa-spin" />` 统一为 `<UiSpinner />`。纯替换，不依赖 PrimeVue。

### 3.3 可选增强 (P2) — 长期基础设施

#### E7: 表单验证 — PrimeVue Form + Zod

为 `CreateShipmentPlanDialog` 等复杂表单提供结构化验证，替代手写 `errorMsg` ref。

#### E8: CascadeSelect / TreeSelect

当前无需求，但 ERP 系统迟早会需要 (如: 多级产品分类选择、组织架构选择)。

---

## 四、架构设计 — Ui* 包装层

### 4.1 组件分层

```
src/components/ui/
├── [现有 30 个 Ui* 组件]          ← Keep: 不动任何代码
│   ├── UiButton.vue               (原生 HTML + Tailwind)
│   ├── UiDialog.vue               (Reka UI + Tailwind)
│   ├── UiSelect.vue               (Reka UI + Tailwind)
│   ├── UiCheckbox.vue             (Reka UI + Tailwind)
│   ├── UiTabs.vue                 (Reka UI + Tailwind)
│   └── ... 其余 25 个
│
├── [新增增强组件]                  ← Enhance: PrimeVue Unstyled + PT
│   ├── UiAutocomplete.vue         (PrimeVue AutoComplete + PT)
│   ├── UiDataTable.vue            (PrimeVue DataTable + PT)
│   ├── UiDrawer.vue               (PrimeVue Drawer + PT)
│   ├── UiDateRangePicker.vue      (PrimeVue DatePicker range + PT)
│   ├── UiCascadeSelect.vue        (PrimeVue CascadeSelect + PT) [P2]
│   └── UiTreeSelect.vue           (PrimeVue TreeSelect + PT) [P2]
│
└── [纯 Tailwind 增强]             ← Enhance: 不依赖任何库
    ├── UiSearchInput.vue          (基于 UiInput 扩展)
    └── (UiSpinner 已存在，需统一使用)
```

### 4.2 PT 主题配置

所有 PrimeVue Unstyled 组件的 "Plush Cute" 样式集中在一个配置文件中:

```
src/styles/primevue-pt.ts          ← "Plush Cute" PT Preset
```

```typescript
// 示例结构 (实际约 160-200 行)
export const plushCutePT = {
  autocomplete: {
    root: 'relative',
    input: 'w-full py-2.5 px-4 text-sm bg-slate-50 border-2 border-ocean-light rounded-[var(--radius-input)] ...',
    panel: 'absolute z-[9999] bg-white border border-border rounded-xl shadow-lg ...',
    item: ({ context }) => ({
      class: [
        'px-3 py-2 text-[13px] cursor-pointer rounded-md transition-colors',
        context.focused ? 'bg-primary-50 text-primary-700' : 'text-text hover:bg-ocean-light/30',
      ]
    }),
    itemgroup: '...',
  },
  datatable: {
    root: 'rounded-2xl overflow-hidden shadow-sm border border-border-light',
    header: 'bg-surface px-6 py-4 border-b border-border-light',
    // ... ~40 行
  },
  drawer: {
    root: 'fixed inset-0 z-[9999]',
    mask: 'bg-black/50 backdrop-blur-sm',
    content: 'bg-surface-card shadow-lg w-[480px] h-full',
    // ... ~15 行
  },
  datepicker: {
    root: '...',
    panel: 'bg-surface-card rounded-2xl shadow-lg border border-border-light p-4',
    // ... ~25 行
  },
}
```

### 4.3 依赖关系图

```
PrimeVue Unstyled (新增)          Reka UI (现有)
    │                                  │
    ├── UiAutocomplete                 ├── UiDialog
    ├── UiDataTable                    ├── UiSelect
    ├── UiDrawer                       ├── UiCheckbox
    ├── UiDateRangePicker              ├── UiTabs/TabTrigger/TabContent
    └── UiCascadeSelect [P2]           └── (6 个组件，不再新增)
                                           
    └── 两者永不交叉 ──┘
    
    共同基础: Tailwind CSS v4 + "Plush Cute" design tokens
```

**关键设计决策**: 
- Reka UI 和 PrimeVue Unstyled **永远不会在同一个组件内部混用**
- Reka UI 管现有组件，PrimeVue 管新增组件
- 两者的样式统一通过 Tailwind CSS 实现，不通过库级别的集成

---

## 五、实施路径 — 严格渐进式

### 阶段 0: 基础设施 (不影响任何现有代码)

```
├── 安装 primevue (Unstyled 模式，不注入任何样式)
├── 创建 src/styles/primevue-pt.ts (Plush Cute PT 配置)
├── 在 main.ts 中 app.use(PrimeVue, { unstyled: true, pt: plushCutePT })
└── 验证: 现有页面零变化
```

### 阶段 1: UiAutocomplete (消除最大痛点)

```
├── 创建 UiAutocomplete.vue (基于 PrimeVue AutoComplete + PT)
├── 在 1 个视图中替换 (如 StockOutTab.vue)
├── 验证交互行为一致
├── 逐步替换其余 4 个视图
└── 删除各视图的自建 autocomplete 代码 (-664 行)
```

### 阶段 2: UiDrawer (消除第二大痛点)

```
├── 创建 UiDrawer.vue (基于 PrimeVue Drawer + PT)
├── 重构 PlanDetailDrawer.vue 使用 UiDrawer
├── 验证抽屉交互一致
└── PlanDetailDrawer 从 468 行 → ~80 行
```

### 阶段 3: UiDataTable (最复杂但收益最大)

```
├── 创建 UiDataTable.vue (基于 PrimeVue DataTable + PT)
├── 选择最简单的视图试水 (如 ProductionView.vue)
├── 逐步替换其余 12 个视图 (每次 1 个)
└── 每个视图替换后立即验证
```

### 阶段 4: P1 增强

```
├── UiDateRangePicker (替换 7 个视图的双日期选择器)
├── UiSearchInput (统一 8 个自定义搜索框)
└── 统一 UiSpinner 使用 (替换 41 处 fa-spinner)
```

### 阶段 5: P2 增强 (按需)

```
├── 表单验证 (PrimeVue Form + Zod)
├── CascadeSelect / TreeSelect
└── 其他按需新增
```

**每个阶段完全独立，可以在任何阶段停止，不影响已完成的工作。**

---

## 六、风险评估

| 风险 | 等级 | 说明 | 缓解 |
|------|------|------|------|
| PrimeVue Unstyled 与 Reka UI 冲突 | **极低** | 两者不共享任何运行时代码，不操作同一 DOM | 无需缓解 |
| PT 配置学习曲线 | **低** | 需理解 PrimeVue 组件的 section 结构 | 一次投入，约 1-2 天 |
| z-index 冲突 | **低** | Reka UI Dialog 和 PrimeVue Drawer 各自管理 z-index | 定义统一的 z-index 层级常量 |
| 包体积增长 | **极低** | PrimeVue Unstyled 按需引入，5 个组件约 +40KB gzip | 可接受 |
| "该用哪个库" 的团队争议 | **低** | 规则清晰: 现有组件用 Reka UI，新组件用 PrimeVue | 写入团队规范 |
| 渐进式迁移中途放弃 | **极低** | 每个阶段独立，不会留下半成品 | — |

---

## 七、为什么其他方案不如 Keep & Enhance

| 方案 | 一句话否决理由 |
|------|--------------|
| 纯 PrimeVue Unstyled | 为了"架构纯洁"重写 6 个工作正常的组件，是工程浪费 |
| Shadcn-Vue + PrimeVue | Shadcn-Vue 底层就是 Reka UI，替换 Reka UI 封装为 Shadcn-Vue 封装无实质收益 |
| Element Plus | 与 Tailwind + "Plush Cute" 设计系统正面冲突 |
| 保持现状 + 全自建 | 664 行 autocomplete 重复 + 468 行 Drawer + 未来每个新组件都需自建 |

---

## 八、最终结论

**Keep & Enhance 是最优解**，因为:

1. **零风险**: 不动现有 30 个组件，不引入任何破坏性变更
2. **最高 ROI**: 664 行 autocomplete 重复 + 468 行 Drawer + 13 个手写表格，通过 ~200 行 PT 配置 + ~300 行包装组件即可消除
3. **可持续**: 未来每个新 UI 需求都有成熟方案 (PrimeVue 90+ 组件)，不再需要从零自建
4. **可逆**: 任何阶段都可停止，已完成的增强不会成为负担
5. **架构自洽**: Reka UI 和 PrimeVue Unstyled 各管各的领域，通过 Tailwind + design tokens 统一视觉
