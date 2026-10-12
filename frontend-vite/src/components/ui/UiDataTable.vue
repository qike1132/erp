<script setup lang="ts" generic="T extends object">
/**
 * UiDataTable — 统一数据表格
 *
 * 基于 PrimeVue DataTable，统一 13 个视图的手写表格。
 * 内置排序、分页、行选择、列固定、加载态、空态。
 *
 * Props:
 *   data         - 数据数组
 *   columns      - 列定义: { field, header, sortable?, width?, align?, fixed? }[]
 *   loading      - 加载状态
 *   paginator    - 是否显示分页（默认 false）
 *   rows         - 每页行数（默认 20）
 *   totalRecords - 总记录数（服务端分页时使用）
 *   selection    - v-model:selection 选中行
 *   rowKey       - 行唯一键字段（默认 'id'）
 *   striped      - 斑马纹（默认 true）
 *   emptyMessage - 空数据文本
 *   virtual      - 启用虚拟滚动（默认 false）。开启后表格主体由 VirtualList 渲染，
 *                  DOM 节点从 O(n) 降到 O(可视区)，适用于单页渲染 200+ 行的场景。
 *                  注意：虚拟模式下分页仍可用，但建议配合服务端分页使用。
 *   virtualHeight - 虚拟滚动容器高度（px）。不给则取容器自适应高度。
 *   rowHeight    - 虚拟模式下行高（px），需与实际行高一致（默认 48）
 *
 * Emits:
 *   update:selection  - 选中行变化
 *   page              - 分页变化: { page, rows }
 *   sort              - 排序变化: { field, order }
 *   rowClick          - 行点击: (row: T) => void
 *
 * Slots:
 *   column-body-{field}  - 自定义列模板（field 为 columns[].field）
 *   empty                - 自定义空态
 *   loading              - 自定义加载态
 *
 * 示例：
 *   <UiDataTable
 *     :data="products"
 *     :columns="columns"
 *     :loading="isLoading"
 *     paginator
 *     :rows="20"
 *     @rowClick="openDetail"
 *   >
 *     <template #column-body-status="{ row }">
 *       <UiStatusBadge :status="row.status" />
 *     </template>
 *   </UiDataTable>
 */
// 按组件深导入（PrimeVue 官方推荐写法）：显式声明依赖，无需解析 barrel 入口。
// 注：实测对 vendor-primevue chunk 体积无影响 —— 该 chunk 的体积由 DataTable
// 内部的静态依赖（Paginator / VirtualScroller / 选择列 Checkbox 等）决定，
// 与是否走 barrel 无关（Rollup 对 barrel 已能正确 tree-shake）。
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import type { DataTableSortEvent } from 'primevue/datatable'
import { ref, watch, computed, nextTick } from 'vue'
import VirtualList from './VirtualList.vue'
import UiSkeleton from './UiSkeleton.vue'
import { useTableVirtualScroll } from '@/composables/useTableVirtualScroll'

// ============================================================
// Column definition
// ============================================================
export interface TableColumn {
  field: string
  header: string
  sortable?: boolean
  width?: string
  align?: 'left' | 'center' | 'right'
  fixed?: 'left' | 'right'
  /** 单位后缀（如 '件', '元'） */
  unit?: string
}

// ============================================================
// Props
// ============================================================
const props = withDefaults(
  defineProps<{
    data: T[]
    columns: TableColumn[]
    loading?: boolean
    paginator?: boolean
    rows?: number
    /** 每页条数可选项（透传给 UiPagination 的每页条数选择器） */
    pageSizeOptions?: number[]
    totalRecords?: number
    /**
     * 受控页码（1 基）。传入后页码由父组件掌控：组件不再于 totalRecords 变化时
     * 自动复位到第 1 页 —— 服务端分页下那会造成「表格显示第 N 页数据、指示器却
     * 显示 1 / N」的失步（父组件仍按旧页码回源）。
     */
    currentPage?: number
    /** 只有一页时隐藏整条分页器（默认 false，保持既有 13 个视图的渲染不变） */
    hidePaginatorOnSinglePage?: boolean
    /** 分页器「共 N ？？」的量词，透传给 UiPagination（默认「条」） */
    itemUnit?: string
    selection?: T[] | null
    rowKey?: string
    striped?: boolean
    emptyMessage?: string
    /** 启用虚拟滚动：DOM 节点从 O(n) 降到 O(可视区) */
    virtual?: boolean
    /** 虚拟滚动容器高度(px)，不传则自适应父容器 */
    virtualHeight?: number
    /** 虚拟模式行高(px)，需与实际行高一致 */
    rowHeight?: number
    /**
     * 行分组模式（透传 PrimeVue）：'rowspan' 会把 `groupRowsBy` 指定的列在相邻同值行间合并成跨行格。
     * 不传则行为与原来完全一致（本组件被 13 个视图共用，透传必须是纯可选的）。
     * ⚠️ 合并判据是**按值相等**，不是按分组 id —— 若分组列的原始值可能跨组重复
     * （例如多笔订单的日期都是同一天），必须让该列的 `field` 指向一个**组内唯一**的值，
     * 否则会把相邻的不同组并成一个大格。
     */
    rowGroupMode?: 'subheader' | 'rowspan'
    /** 参与行分组的列 field（与 rowGroupMode='rowspan' 搭配） */
    groupRowsBy?: string | string[]
  }>(),
  {
    loading: false,
    paginator: false,
    rows: 20,
    pageSizeOptions: () => [10, 20, 50, 100],
    totalRecords: 0,
    currentPage: undefined,
    hidePaginatorOnSinglePage: false,
    itemUnit: '条',
    rowKey: 'id',
    striped: true,
    emptyMessage: '暂无数据',
    virtual: false,
    virtualHeight: undefined,
    rowHeight: 48,
    rowGroupMode: undefined,
    groupRowsBy: undefined,
    selection: undefined,
  },
)

// ============================================================
// Slots
// ============================================================
defineSlots<{
  [K in `column-body-${string}`]: (props: { row: T; column: TableColumn; index: number }) => unknown
} & {
  empty: () => unknown
  loading: () => unknown
}>()

// ============================================================
// Emits
// ============================================================
const emit = defineEmits<{
  'update:selection': [value: T[]]
  page: [event: { page: number; rows: number }]
  sort: [event: { field: string; order: number }]
  rowClick: [row: T]
}>()

// ============================================================
// Pagination state
// ============================================================
const currentPage = ref(props.currentPage ?? 1)
const totalPages = computed(() => {
  const total = props.totalRecords || props.data.length
  return Math.max(1, Math.ceil(total / props.rows))
})

// 受控模式：父组件传了 currentPage 就以它为准，组件不自行改页码
watch(
  () => props.currentPage,
  (v) => { if (v != null) currentPage.value = v },
)

// 非受控模式才在总数变化时回到第 1 页；受控模式的复位由父组件决定
watch(
  () => props.totalRecords,
  () => { if (props.currentPage == null) currentPage.value = 1 },
)

// ============================================================
// Handlers
// ============================================================
function onPage(page: number) {
  currentPage.value = page
  emit('page', { page: page - 1, rows: props.rows })
}

/** 每页条数变化：回到首页并以新条数通知父级重新拉取 */
function onPageSizeChange(size: number) {
  currentPage.value = 1
  emit('page', { page: 0, rows: size })
}

function onSort(event: DataTableSortEvent) {
  emit('sort', { field: event.sortField as string, order: event.sortOrder as number })
}

// PrimeVue 的 `update:selection` 事件**载荷就是选择值本身**（value: T[] | T | undefined），
// 不是 `{ data }` 包装对象（那是 `@row-select` 事件的形状）。
// 原先写 `event.data` 恒为 undefined → update:selection 永远发 undefined，
// 任何调用方勾选行后选择态立刻被清空、批量操作拿不到行。
function onRowSelect(value: T[]) {
  emit('update:selection', value ?? [])
}

// ============================================================
// Virtual scroll
// ============================================================
const vsContainerRef = ref<HTMLElement | null>(null)
const vsHeaderRef = ref<HTMLElement | null>(null)

const { bodyHeight: vsBodyHeight, remeasure: vsRemeasure } = useTableVirtualScroll(
  vsContainerRef,
  vsHeaderRef,
  { rowHeight: props.rowHeight },
)

/** 虚拟区实际高度：优先用显式传入的 virtualHeight，否则用测量值 */
const vsHeight = computed(() => props.virtualHeight ?? vsBodyHeight.value)

/** 虚拟列表 itemKey，兼容 rowKey 为嵌套路径的情况 */
function vsItemKey(row: T, index: number) {
  const k = (row as Record<string, unknown>)[props.rowKey]
  return k != null ? String(k) : index
}

/** 数据变化后重测高度（加载完成后容器高度可能变化） */
watch(
  () => [props.data.length, props.loading],
  async () => {
    if (!props.virtual) return
    await nextTick()
    vsRemeasure()
  },
)
</script>

<template>
  <div class="ui-data-table-wrapper border border-border overflow-hidden">
    <!-- ============ 虚拟滚动模式 ============ -->
    <div
      v-if="virtual"
      ref="vsContainerRef"
      class="flex flex-col"
      :style="virtualHeight ? { height: `${virtualHeight}px` } : undefined"
    >
      <!-- 表头：复用 DataTable 渲染列头，保证与普通模式视觉一致 -->
      <div ref="vsHeaderRef" class="ui-data-table-vs-header">
        <DataTable
          :value="[]"
          :scrollable="false"
          :responsive="false"
          class="ui-data-table-vs-head-table"
        >
          <Column
            v-for="col in columns"
            :key="col.field"
            :field="col.field"
            :header="col.header"
            :sortable="col.sortable ?? false"
            :style="{
              width: col.width,
              textAlign: col.align ?? 'center',
            }"
          />
        </DataTable>
      </div>

      <!-- 表体：虚拟列表，只渲染可视区行 -->
      <div class="flex-1 min-h-0">
        <UiSkeleton v-if="loading && !data.length" class="p-4" variant="table" :rows="6" />
        <VirtualList
          v-else-if="data.length"
          :items="data"
          :item-height="rowHeight"
          :container-height="vsHeight"
          :buffer="8"
          :item-key="vsItemKey"
          @visible-change="() => {}"
        >
          <template #default="{ item, index }">
            <div
              class="ui-data-table-vs-row flex items-center border-b border-border"
              :class="striped && index % 2 === 1 ? 'bg-surface-hover' : ''"
              :style="{ height: `${rowHeight}px` }"
            >
              <div
                v-for="col in columns"
                :key="col.field"
                class="px-3 truncate"
                :style="{
                  width: col.width,
                  textAlign: col.align ?? 'center',
                  flex: col.width ? 'none' : '1 1 0',
                }"
              >
                <slot
                  v-if="$slots[`column-body-${col.field}`]"
                  :name="`column-body-${col.field}`"
                  :row="item"
                  :column="col"
                  :index="index"
                />
                <template v-else>
                  {{ (item as Record<string, unknown>)[col.field] }}{{ col.unit ?? '' }}
                </template>
              </div>
            </div>
          </template>
        </VirtualList>
        <slot v-else name="empty">
          <div class="py-12 text-center text-sm text-text-muted">{{ emptyMessage }}</div>
        </slot>
      </div>
    </div>

    <!-- ============ 普通模式（默认，行为不变）============ -->
    <template v-else>
      <!-- 表格 -->
      <DataTable
        :value="data"
        :loading="loading"
        :paginator="false"
        :selection-mode="selection != null ? 'multiple' : undefined"
        :selection="selection"
        :data-key="rowKey"
        :row-group-mode="rowGroupMode"
        :group-rows-by="groupRowsBy"
        :striped-rows="striped"
        :row-hover="true"
        :scrollable="false"
        :responsive="true"
        :pt="{
          emptyMessage: 'py-12 text-center text-sm text-text-muted',
          loadingOverlay: 'absolute inset-0 bg-white/70 flex items-center justify-center z-10',
        }"
        @update:selection="onRowSelect"
        @sort="onSort"
      >
        <!-- 动态列 -->
        <Column
          v-for="col in columns"
          :key="col.field"
          :field="col.field"
          :header="col.header"
          :sortable="col.sortable ?? false"
          :style="{
            width: col.width,
            textAlign: col.align ?? 'center',
            position: col.fixed ? 'sticky' : undefined,
            [col.fixed ?? '']: col.fixed ? 0 : undefined,
            zIndex: col.fixed ? 1 : undefined,
          }"
        >
          <!-- 自定义列模板 -->
          <template v-if="$slots[`column-body-${col.field}`]" #body="slotProps">
            <slot
              :name="`column-body-${col.field}`"
              :row="slotProps.data"
              :column="col"
              :index="slotProps.index"
            />
          </template>
          <!-- 默认：直接取值 + 单位后缀 -->
          <template v-else #body="slotProps">
            {{ slotProps.data[col.field] }}{{ col.unit ?? '' }}
          </template>
        </Column>

        <!-- 空态 -->
        <template v-if="$slots.empty" #empty>
          <slot name="empty" />
        </template>

        <!-- 加载态 -->
        <template v-if="$slots.loading" #loading>
          <slot name="loading" />
        </template>
      </DataTable>
    </template>

    <!-- 统一分页器：与 outsource/beile-order 等视图共享 UiPagination 样式 -->
    <UiPagination
      v-if="paginator && !(hidePaginatorOnSinglePage && totalPages <= 1)"
      :current-page="currentPage"
      :total-pages="totalPages"
      :total-items="totalRecords || data.length"
      :item-unit="itemUnit"
      :page-size="rows"
      :page-size-options="pageSizeOptions"
      @update:current-page="onPage"
      @update:page-size="onPageSizeChange"
    />
  </div>
</template>