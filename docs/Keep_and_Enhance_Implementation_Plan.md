# 渐进式增强架构 (Keep & Enhance) — 完整实施方案

> 核心原则: **不动现有代码，只补缺。** 每个 Phase 独立可交付，随时可停。

---

## Phase 0: 基础设施 — 引入 PrimeVue Unstyled

**目标**: 安装 PrimeVue Unstyled 模式，不影响任何现有页面。

### 0.1 安装依赖

```bash
cd d:\erp_system\frontend-vite
npm install primevue @primevue/themes
```

### 0.2 创建 PT 主题配置

新建 `src/styles/primevue-pt.ts`:

```typescript
/**
 * "Plush Cute" PrimeVue Pass Through Preset
 *
 * 所有 PrimeVue Unstyled 组件的样式集中定义在此文件。
 * 使用 Tailwind CSS 类名 + 项目 design tokens。
 * 此文件是唯一需要维护的 PrimeVue 样式入口。
 */
import type { PrimePT } from 'primevue/config'

// 公共输入框样式 — 与 UiInput/UiSelect/UiDatePicker 视觉一致
const inputBase = [
  'w-full py-2.5 px-4 text-sm bg-slate-50',
  'border-2 border-ocean-light rounded-[var(--radius-input)]',
  'transition-all duration-300 outline-none min-h-[44px] box-border font-sans',
  'text-text placeholder:text-text-muted',
  'focus:bg-white focus:border-ocean-deep focus:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)]',
  'hover:border-ocean-deep',
  'disabled:opacity-50 disabled:cursor-not-allowed',
].join(' ')

// 公共下拉面板样式
const overlayPanel = [
  'absolute z-[9999] bg-white border border-border rounded-xl shadow-lg',
  'max-h-[240px] overflow-y-auto py-1',
].join(' ')

// 公共选项样式
const overlayItem = ({ context }: { context: { focused?: boolean; selected?: boolean; disabled?: boolean } }) => ({
  class: [
    'px-3 py-2 text-[13px] cursor-pointer rounded-md mx-1 outline-none transition-colors flex items-center',
    context.focused ? 'bg-primary-50 text-primary-700' : 'text-text hover:bg-ocean-light/30',
    context.selected ? 'font-semibold text-primary-700' : '',
    context.disabled ? 'opacity-50 cursor-not-allowed' : '',
  ],
})

export const plushCutePT: PrimePT = {
  // ===== E1: UiAutocomplete 使用 =====
  autocomplete: {
    root: 'relative',
    input: inputBase + ' pr-10',
    panel: overlayPanel + ' w-full min-w-full',
    list: 'm-0 p-0 list-none',
    option: overlayItem,
    optiongroup: 'px-3 py-2 text-[11px] font-semibold text-text-muted uppercase tracking-wider',
    emptymessage: 'px-3 py-2 text-[13px] text-text-muted',
    loader: 'hidden',
  },

  // ===== E3: UiDataTable 使用 =====
  datatable: {
    root: 'rounded-2xl overflow-hidden border border-border-light',
    header: 'bg-surface px-6 py-4 border-b border-border-light',
    table: 'w-full border-collapse',
    thead: 'bg-surface',
    headercell: 'px-4 py-3 text-xs font-semibold text-text-secondary text-center uppercase tracking-wider border-b-2 border-border',
    tbody: 'bg-surface-card',
    row: ({ context }: { context: { selected?: boolean; striped?: boolean } }) => ({
      class: [
        'transition-colors duration-150',
        context.selected ? 'bg-primary-50' : '',
        !context.selected ? 'hover:bg-ocean-light/20' : '',
      ],
    }),
    bodycell: 'px-4 py-3 text-sm text-text border-b border-border-light text-center',
    footercell: 'px-4 py-3 text-sm font-semibold text-text-secondary bg-surface border-t border-border-light',
    footer: 'bg-surface',
    emptymessage: 'px-4 py-8 text-center text-text-muted',
    // 分页器
    paginator: {
      root: 'flex items-center justify-between px-4 py-3 bg-surface border-t border-border-light',
      pages: 'flex items-center gap-1',
      pagebutton: ({ context }: { context: { active?: boolean } }) => ({
        class: [
          'w-8 h-8 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer border-none',
          context.active
            ? 'bg-gradient-primary text-white shadow-sm'
            : 'text-text-secondary hover:bg-ocean-light/30',
        ],
      }),
      first: 'w-8 h-8 rounded-xl text-sm text-text-secondary hover:bg-ocean-light/30 cursor-pointer border-none bg-transparent',
      prev: 'w-8 h-8 rounded-xl text-sm text-text-secondary hover:bg-ocean-light/30 cursor-pointer border-none bg-transparent',
      next: 'w-8 h-8 rounded-xl text-sm text-text-secondary hover:bg-ocean-light/30 cursor-pointer border-none bg-transparent',
      last: 'w-8 h-8 rounded-xl text-sm text-text-secondary hover:bg-ocean-light/30 cursor-pointer border-none bg-transparent',
      rowperpagedropdown: {
        root: 'text-sm text-text-secondary',
        input: 'w-16 px-2 py-1 text-sm border border-border rounded-lg bg-white',
        panel: overlayPanel,
        option: overlayItem,
      },
    },
    // 列排序
    sort: {
      root: 'ml-1 inline-flex flex-col text-[10px] leading-none text-text-muted',
      asc: 'text-primary-500',
      desc: 'text-primary-500',
    },
    // 行选择 checkbox
    column: {
      headercell: ({ context }: { context: { sorted?: boolean } }) => ({
        class: [
          'px-4 py-3 text-xs font-semibold text-text-secondary text-center uppercase tracking-wider border-b-2 border-border',
          context.sorted ? 'bg-primary-50' : 'bg-surface',
        ],
      }),
      bodycell: 'px-4 py-3 text-sm text-text border-b border-border-light text-center',
      headercheckbox: {
        root: 'w-[18px] h-[18px] rounded border-2 flex items-center justify-center cursor-pointer transition-all duration-200 border-border hover:border-primary-500',
        input: 'sr-only',
        icon: 'text-xs text-white',
      },
      checkbox: {
        root: ({ context }: { context: { checked?: boolean } }) => ({
          class: [
            'w-[18px] h-[18px] rounded border-2 flex items-center justify-center transition-all duration-200 cursor-pointer flex-shrink-0',
            context.checked ? 'bg-primary-500 border-primary-500 text-white' : 'bg-white border-border hover:border-primary-500',
          ],
        }),
        input: 'sr-only',
        icon: 'text-xs',
      },
    },
  },

  // ===== E2: UiDrawer 使用 =====
  drawer: {
    root: 'fixed inset-0 z-[9999]',
    mask: 'bg-black/50 backdrop-blur-sm transition-opacity duration-300',
    content: {
      class: [
        'fixed top-0 right-0 h-full bg-surface-card shadow-lg',
        'w-[480px] max-w-[90vw] flex flex-col',
        'transition-transform duration-300 ease-out',
      ],
    },
    header: 'px-6 py-5 border-b border-border-light flex justify-between items-center',
    title: 'text-lg font-semibold m-0 text-text',
    closobutton: 'w-8 h-8 border-none bg-surface rounded-full cursor-pointer flex items-center justify-center text-text-secondary transition-all duration-200 hover:bg-danger-50 hover:text-danger-500',
    body: 'p-6 overflow-y-auto flex-1',
    footer: 'px-6 py-4 border-t border-border-light flex justify-end gap-2',
  },

  // ===== E4: UiDateRangePicker 使用 =====
  datepicker: {
    root: 'relative',
    input: inputBase + ' pr-10 cursor-pointer',
    panel: 'bg-surface-card rounded-2xl shadow-lg border border-border-light p-4',
    calendar: {
      root: 'w-full',
      header: 'flex items-center justify-between mb-2',
      title: 'text-sm font-semibold text-text',
      prev: 'w-8 h-8 rounded-full border-none bg-transparent cursor-pointer hover:bg-ocean-light/30 text-text-secondary transition-colors',
      next: 'w-8 h-8 rounded-full border-none bg-transparent cursor-pointer hover:bg-ocean-light/30 text-text-secondary transition-colors',
    },
    dayview: {
      root: 'w-full',
      weekheader: 'flex',
      weekheadercell: 'flex-1 text-center text-[11px] font-semibold text-text-muted py-1',
      week: 'flex',
      day: ({ context }: { context: { selected?: boolean; today?: boolean; disabled?: boolean } }) => ({
        class: [
          'flex-1 text-center py-1.5 text-sm rounded-lg cursor-pointer transition-colors',
          context.selected ? 'bg-gradient-primary text-white font-semibold' : 'hover:bg-ocean-light/30 text-text',
          context.today && !context.selected ? 'border border-primary-300 font-semibold' : '',
          context.disabled ? 'opacity-40 cursor-not-allowed' : '',
        ],
      }),
    },
    monthview: {
      month: ({ context }: { context: { selected?: boolean } }) => ({
        class: [
          'py-2 text-sm rounded-lg cursor-pointer transition-colors',
          context.selected ? 'bg-gradient-primary text-white font-semibold' : 'hover:bg-ocean-light/30 text-text',
        ],
      }),
    },
    yearview: {
      year: ({ context }: { context: { selected?: boolean } }) => ({
        class: [
          'py-2 text-sm rounded-lg cursor-pointer transition-colors',
          context.selected ? 'bg-gradient-primary text-white font-semibold' : 'hover:bg-ocean-light/30 text-text',
        ],
      }),
    },
    separator: 'mx-2 text-text-muted self-center',
    rangeSeparator: 'mx-2 text-text-muted',
  },

  // ===== E8: CascadeSelect / TreeSelect [P2] =====
  cascadeselect: {
    root: 'relative',
    input: inputBase + ' pr-10 cursor-pointer',
    panel: overlayPanel,
    list: 'm-0 p-0 list-none',
    option: overlayItem,
  },
  treeselect: {
    root: 'relative',
    input: inputBase + ' pr-10 cursor-pointer',
    panel: overlayPanel,
    tree: 'p-1',
    node: 'px-3 py-2 text-[13px] cursor-pointer rounded-md transition-colors text-text hover:bg-ocean-light/30',
  },
}
```

### 0.3 注册 PrimeVue

修改 `src/main.ts`:

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import PrimeVue from 'primevue/config'
import { plushCutePT } from './styles/primevue-pt'
import './styles/app.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)

app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue Error]', info, err)
}

app.use(createPinia())
app.use(router)
app.use(PrimeVue, {
  unstyled: true,
  pt: plushCutePT,
})
app.use(VueQueryPlugin, {
  queryClientConfig: {
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  },
})

app.mount('#app')

// FontAwesome 异步加载
import('@fortawesome/fontawesome-free/css/all.min.css')
```

### 0.4 验证

```bash
npm run dev
# 打开浏览器，验证所有现有页面零变化
# PrimeVue Unstyled 模式不注入任何 CSS，不会影响现有组件
```

---

## Phase 1: UiAutocomplete — 消除 664 行重复

### 1.1 创建组件

新建 `src/components/ui/UiAutocomplete.vue`:

```vue
<template>
  <div class="relative" ref="containerRef">
    <AutoComplete
      :model-value="modelValue"
      :suggestions="suggestions"
      :placeholder="placeholder"
      :disabled="disabled"
      :delay="debounceMs"
      :option-label="optionLabel"
      :option-value="optionValue"
      :multiple="multiple"
      :loading="loading"
      dropdown
      @update:model-value="$emit('update:modelValue', $event)"
      @complete="onComplete"
    >
      <template #option="{ option }">
        <slot name="option" :option="option">
          <span>{{ option[optionLabel] }}</span>
        </slot>
      </template>
      <template #header>
        <slot name="header" />
      </template>
      <template #footer>
        <slot name="footer" />
      </template>
      <template #empty>
        <span class="px-3 py-2 text-[13px] text-text-muted">{{ emptyText }}</span>
      </template>
    </AutoComplete>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import AutoComplete from 'primevue/autocomplete'

export interface AutocompleteOption {
  [key: string]: unknown
}

const props = withDefaults(
  defineProps<{
    modelValue?: unknown
    suggestions?: AutocompleteOption[]
    placeholder?: string
    disabled?: boolean
    debounceMs?: number
    optionLabel?: string
    optionValue?: string
    multiple?: boolean
    loading?: boolean
    emptyText?: string
    /** 远程搜索函数 — 输入时调用，返回建议列表 */
    searchFn?: (query: string) => Promise<AutocompleteOption[]>
  }>(),
  {
    suggestions: () => [],
    debounceMs: 300,
    optionLabel: 'label',
    optionValue: 'value',
    emptyText: '无匹配项',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
}>()

const containerRef = ref<HTMLElement>()
const loading = ref(false)

async function onComplete(event: { query: string }) {
  if (!props.searchFn) return
  loading.value = true
  try {
    const results = await props.searchFn(event.query)
    // PrimeVue AutoComplete 的 suggestions 需要通过 props 传入
    // 这里通过触发事件让父组件更新 suggestions
    emit('update:suggestions' as never, results)
  } finally {
    loading.value = false
  }
}
</script>
```

### 1.2 使用示例 — 替换 StockOutTab.vue 的自建 autocomplete

**替换前** (StockOutTab.vue, ~99 行):
```vue
<!-- 自建: 23 行模板 + 44 行脚本 + 32 行 CSS -->
<div class="relative">
  <input v-model="productKeyword" @input="onSearchInput" @focus="onProductFocus"
         class="so-product-input" placeholder="搜索产品名称或69码..." />
  <div v-if="showSuggestions && productSuggestions.length > 0" class="autocomplete-dropdown">
    <div v-for="p in productSuggestions" :key="p.id" class="autocomplete-item"
         @mousedown.prevent="selectProduct(p)">
      <span>{{ p.name }}</span>
      <span class="barcode-hint">{{ p.barcode }}</span>
    </div>
  </div>
</div>
```

**替换后** (~5 行):
```vue
<UiAutocomplete
  v-model="selectedProductId"
  :suggestions="productSuggestions"
  option-label="name"
  option-value="id"
  :search-fn="searchProducts"
  placeholder="搜索产品名称或69码..."
  empty-text="无匹配产品"
>
  <template #option="{ option }">
    <div class="flex justify-between items-center w-full">
      <span>{{ option.name }}</span>
      <span class="text-[11px] text-text-muted">{{ option.barcode }}</span>
    </div>
  </template>
</UiAutocomplete>
```

### 1.3 迁移清单

| 视图 | 自建行数 | 替换后行数 | 说明 |
|------|---------|-----------|------|
| StockOutTab.vue | 99 | ~5 | 产品搜索 |
| CustomerOrderView.vue | 156 (2处) | ~10 | 产品搜索 x2 |
| CaseStockTab.vue | 99 | ~5 | 产品搜索 |
| ProductListView.vue | 163 | ~5 | BOM 复制搜索 (需键盘导航) |
| CreateShipmentPlanDialog.vue | 147 | ~5 | 每行一个 autocomplete |
| **合计** | **664** | **~30** | **-95%** |

---

## Phase 2: UiDrawer — 消除 468 行自建

### 2.1 创建组件

新建 `src/components/ui/UiDrawer.vue`:

```vue
<template>
  <Drawer
    :visible="open"
    :position="position"
    :modal="modal"
    @update:visible="$emit('update:open', $event)"
  >
    <template #header>
      <div class="flex items-center gap-2 flex-1">
        <slot name="title-icon" />
        <h3 class="text-lg font-semibold m-0 text-text">
          <slot name="title">{{ title }}</slot>
        </h3>
      </div>
    </template>
    <slot />
    <template v-if="$slots.footer" #footer>
      <slot name="footer" />
    </template>
  </Drawer>
</template>

<script setup lang="ts">
import Drawer from 'primevue/drawer'

withDefaults(
  defineProps<{
    open: boolean
    title?: string
    position?: 'left' | 'right'
    modal?: boolean
  }>(),
  {
    position: 'right',
    modal: true,
  },
)

defineEmits<{ 'update:open': [value: boolean] }>()
</script>
```

### 2.2 使用示例 — 替换 PlanDetailDrawer

**替换前**: 468 行全自建 (109 行模板 + 58 行脚本 + 298 行 CSS)

**替换后** (~60 行):
```vue
<UiDrawer v-model:open="showDrawer" title="计划详情">
  <div class="drw-section">
    <h4>基本信息</h4>
    <div class="grid grid-cols-2 gap-3 text-sm">
      <div><span class="text-text-muted">客户:</span> {{ plan?.customer }}</div>
      <div><span class="text-text-muted">日期:</span> {{ plan?.date }}</div>
      <!-- 其余信息字段 -->
    </div>
  </div>
  <div class="drw-section mt-4">
    <h4>明细</h4>
    <!-- 明细卡片 -->
  </div>
</UiDrawer>
```

---

## Phase 3: UiDataTable — 统一 13 个视图的表格

### 3.1 创建组件

新建 `src/components/ui/UiDataTable.vue`:

```vue
<template>
  <DataTable
    :value="data"
    :paginator="paginator"
    :rows="rows"
    :rows-per-page-options="rowsPerPageOptions"
    :sort-field="sortField"
    :sort-order="sortOrder"
    :selection="selection"
    :selection-mode="selectionMode"
    :loading="loading"
    :scrollable="scrollable"
    :scroll-height="scrollHeight"
    :virtual-scroller-options="virtualScrollOptions"
    :row-class="rowClass"
    :empty-message="emptyText"
    @update:selection="$emit('update:selection', $event)"
    @sort="$emit('sort', $event)"
    @row-click="$emit('rowClick', $event)"
  >
    <slot />
    <template #empty>
      <div class="py-8 text-center text-text-muted">
        <i class="fas fa-inbox text-2xl mb-2 block opacity-40" />
        <p>{{ emptyText }}</p>
      </div>
    </template>
  </DataTable>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import DataTable from 'primevue/datatable'

const props = withDefaults(
  defineProps<{
    data: unknown[]
    paginator?: boolean
    rows?: number
    rowsPerPageOptions?: number[]
    sortField?: string
    sortOrder?: number
    selection?: unknown
    selectionMode?: 'single' | 'multiple'
    loading?: boolean
    scrollable?: boolean
    scrollHeight?: string
    virtualScroll?: boolean
    virtualItemSize?: number
    emptyText?: string
    rowClass?: (data: unknown) => string | object
  }>(),
  {
    paginator: false,
    rows: 20,
    rowsPerPageOptions: () => [10, 20, 50],
    sortOrder: 1,
    emptyText: '暂无数据',
    virtualItemSize: 44,
  },
)

defineEmits<{
  'update:selection': [value: unknown]
  'sort': [event: unknown]
  'rowClick': [event: unknown]
}>()

const virtualScrollOptions = computed(() =>
  props.virtualScroll ? { itemSize: props.virtualItemSize } : undefined,
)
</script>
```

### 3.2 创建 UiDataColumn 辅助组件

新建 `src/components/ui/UiDataColumn.vue`:

```vue
<template>
  <Column
    :field="field"
    :header="header"
    :sortable="sortable"
    :frozen="frozen"
    :align-frozen="alignFrozen"
    :selection-mode="selectionMode"
    :style="columnStyle"
  >
    <template v-if="$slots.body" #body="{ data, index }">
      <slot :data="data" :index="index" />
    </template>
    <template v-if="$slots.header" #header>
      <slot name="header" />
    </template>
  </Column>
</template>

<script setup lang="ts">
import Column from 'primevue/column'

withDefaults(
  defineProps<{
    field?: string
    header?: string
    sortable?: boolean
    frozen?: boolean
    alignFrozen?: 'left' | 'right'
    selectionMode?: 'single' | 'multiple'
    width?: string
  }>(),
  {
    sortable: false,
    frozen: false,
    alignFrozen: 'left',
  },
)

const columnStyle = defineModel<string>('width')
</script>
```

### 3.3 使用示例

**替换前** (PurchasePlanView.vue, ~50 行模板 + 手动排序 ~30 行脚本):
```vue
<table class="sp-sku-table">
  <thead>
    <tr>
      <th class="sp-sku-th-sortable" @click="toggleSkuSort('plan')">计划量 ↕</th>
      <th class="sp-sku-th-sortable" @click="toggleSkuSort('shipped')">已发量 ↕</th>
      ...
    </tr>
  </thead>
  <tbody>
    <tr v-for="item in sortedSkuList" :key="item.id">
      <td>{{ item.plan }}</td>
      <td>{{ item.shipped }}</td>
      ...
    </tr>
  </tbody>
</table>
```

**替换后** (~10 行):
```vue
<UiDataTable :data="skuList" paginator :rows="10" sort-field="plan" :sort-order="-1">
  <UiDataColumn field="plan" header="计划量" sortable />
  <UiDataColumn field="shipped" header="已发量" sortable />
  <UiDataColumn field="remain" header="剩余量" sortable />
  <UiDataColumn header="操作">
    <template #body="{ data }">
      <UiButton variant="ghost" size="sm" @click="editItem(data)">编辑</UiButton>
    </template>
  </UiDataColumn>
</UiDataTable>
```

### 3.4 迁移顺序 (由简到难)

| 顺序 | 视图 | 复杂度 | 说明 |
|------|------|--------|------|
| 1 | ProductionView | 最简 | 纯展示，无排序/选择 |
| 2 | ApprovalView | 简单 | + 客户端搜索过滤 |
| 3 | InventoryTab | 简单 | + 简单筛选 |
| 4 | ReportView | 中等 | + 分页 |
| 5 | CustomerView | 中等 | + 分页 + 搜索 |
| 6 | ProductListView | 中等 | + 排序 + 操作按钮 |
| 7 | PurchasePlanView | 复杂 | + 排序 + 进度条 + 自定义列 |
| 8 | CustomerOrderView | 复杂 | + 分组行 + 图片 + 操作 |
| 9 | StockOutTab | 复杂 | + 分组 + 折叠 + 图片 |
| 10-13 | 其余视图 | 中等 | 逐个迁移 |

---

## Phase 4: P1 增强 — 体验统一

### 4.1 UiDateRangePicker

新建 `src/components/ui/UiDateRangePicker.vue`:

```vue
<template>
  <div class="flex items-center gap-2">
    <DatePicker
      :model-value="modelValue"
      selection-mode="range"
      :placeholder="placeholder"
      :disabled="disabled"
      :min-date="minDate"
      :max-date="maxDate"
      date-format="yy-mm-dd"
      show-icon
      @update:model-value="$emit('update:modelValue', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import DatePicker from 'primevue/datepicker'

withDefaults(
  defineProps<{
    modelValue?: (Date | null)[]
    placeholder?: string
    disabled?: boolean
    minDate?: Date
    maxDate?: Date
  }>(),
  {
    placeholder: '选择日期范围',
  },
)

defineEmits<{ 'update:modelValue': [value: (Date | null)[]] }>()
</script>
```

**迁移目标**: 7 个视图的 9 对双 UiDatePicker → 各 1 个 `<UiDateRangePicker>`

### 4.2 UiSearchInput (不依赖 PrimeVue)

新建 `src/components/ui/UiSearchInput.vue`:

```vue
<template>
  <div class="relative">
    <input
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      class="w-full py-2 pl-9 pr-8 text-sm bg-slate-50 border-2 border-ocean-light rounded-[var(--radius-input)] transition-all duration-300 outline-none min-h-[40px] text-text placeholder:text-text-muted focus:bg-white focus:border-ocean-deep focus:shadow-[0_0_0_0.2rem_rgba(135,206,235,0.25)] disabled:opacity-50 disabled:cursor-not-allowed"
      @input="$emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keydown.enter="$emit('search')"
    />
    <i class="fas fa-search absolute left-3 top-1/2 -translate-y-1/2 text-text-muted text-sm" />
    <button
      v-if="modelValue"
      class="absolute right-2 top-1/2 -translate-y-1/2 w-5 h-5 rounded-full border-none bg-transparent cursor-pointer text-text-muted hover:text-text-secondary text-xs flex items-center justify-center"
      @click="$emit('update:modelValue', ''); $emit('search')"
    >
      <i class="fas fa-times" />
    </button>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    disabled?: boolean
  }>(),
  {
    placeholder: '搜索...',
  },
)

defineEmits<{
  'update:modelValue': [value: string]
  'search': []
}>()
</script>
```

**迁移目标**: 8 个视图的自定义 `<input class="*-search-input">` → `<UiSearchInput>`

### 4.3 统一 UiSpinner 使用

全局替换 41 处 `<i class="fas fa-spinner fa-spin" />` → `<UiSpinner />`。
纯机械替换，不依赖任何新库。

---

## Phase 5: P2 增强 — 长期基础设施

### 5.1 表单验证

在需要复杂验证的表单中引入 PrimeVue Form:

```vue
<UiForm @submit="onSubmit" :resolver="zodResolver(schema)">
  <UiFormField name="customer" label="客户">
    <UiAutocomplete v-model="form.customer" :search-fn="searchCustomers" />
  </UiFormField>
  <UiFormField name="date" label="日期" required>
    <UiDatePicker v-model="form.date" />
  </UiFormField>
</UiForm>
```

### 5.2 CascadeSelect / TreeSelect

当业务出现多级分类、组织架构等需求时，直接使用:

```vue
<UiCascadeSelect v-model="category" :options="categoryTree" />
<UiTreeSelect v-model="department" :options="deptTree" />
```

---

## 文件结构总览

```
src/
├── components/ui/
│   ├── [30 个现有 Ui* 组件]         ← KEEP: 零改动
│   │
│   ├── UiAutocomplete.vue           ← NEW (Phase 1, PrimeVue AutoComplete)
│   ├── UiDataTable.vue              ← NEW (Phase 3, PrimeVue DataTable)
│   ├── UiDataColumn.vue             ← NEW (Phase 3, PrimeVue Column)
│   ├── UiDrawer.vue                 ← NEW (Phase 2, PrimeVue Drawer)
│   ├── UiDateRangePicker.vue        ← NEW (Phase 4, PrimeVue DatePicker range)
│   ├── UiSearchInput.vue            ← NEW (Phase 4, 纯 Tailwind)
│   ├── UiCascadeSelect.vue          ← NEW (Phase 5, PrimeVue CascadeSelect)
│   └── UiTreeSelect.vue             ← NEW (Phase 5, PrimeVue TreeSelect)
│
├── styles/
│   ├── app.css                      ← KEEP: 零改动
│   └── primevue-pt.ts               ← NEW (Phase 0, Plush Cute PT 配置)
│
└── main.ts                          ← MODIFY: 添加 PrimeVue 注册 (3 行)
```

**改动量统计**:

| 类型 | 数量 |
|------|------|
| 新增文件 | 9 个 (8 组件 + 1 PT 配置) |
| 修改文件 | 1 个 (main.ts, +3 行) |
| 删除代码 (Phase 1-4 完成后) | ~1200 行自建代码 |
| 现有组件改动 | **0** |

---

## 依赖增量

```json
{
  "dependencies": {
    "primevue": "^4.x",
    "@primevue/themes": "^4.x"
  }
}
```

预估 gzip 增量: **~40KB** (PrimeVue Unstyled 按需引入 5 个组件)

---

## 验证检查清单

每个 Phase 完成后必须验证:

- [ ] `npm run build` 无错误
- [ ] `npm run type-check` 无类型错误
- [ ] 所有现有页面视觉零变化
- [ ] 新组件在 "Plush Cute" 风格下正确渲染
- [ ] 新组件的 focus/hover/active 状态与现有组件一致 (ocean-light 边框、蓝色光晕)
- [ ] 新组件的圆角与对应类型一致 (input: 12px, card: 24px, button: 14px)
