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
import { DataTable, Column } from 'primevue'
import type { DataTableSortEvent } from 'primevue'
import { ref, watch, computed } from 'vue'

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
    selection?: T[] | null
    rowKey?: string
    striped?: boolean
    emptyMessage?: string
  }>(),
  {
    loading: false,
    paginator: false,
    rows: 20,
    pageSizeOptions: () => [10, 20, 50, 100],
    totalRecords: 0,
    rowKey: 'id',
    striped: true,
    emptyMessage: '暂无数据',
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
const currentPage = ref(1)
const totalPages = computed(() => {
  const total = props.totalRecords || props.data.length
  return Math.max(1, Math.ceil(total / props.rows))
})

watch(
  () => props.totalRecords,
  () => { currentPage.value = 1 },
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

function onRowSelect(event: { data: T[] }) {
  emit('update:selection', event.data)
}
</script>

<template>
  <div class="ui-data-table-wrapper rounded-xl border border-border overflow-hidden">
    <!-- 表格 -->
    <DataTable
      :value="data"
      :loading="loading"
      :paginator="false"
      :selectionMode="selection != null ? 'multiple' : undefined"
      :selection="selection"
      :dataKey="rowKey"
      :stripedRows="striped"
      :rowHover="true"
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

    <!-- 统一分页器：与 outsource/beile-order 等视图共享 UiPagination 样式 -->
    <UiPagination
      v-if="paginator"
      :current-page="currentPage"
      :total-pages="totalPages"
      :total-items="totalRecords || data.length"
      :page-size="rows"
      :page-size-options="pageSizeOptions"
      @update:current-page="onPage"
      @update:page-size="onPageSizeChange"
    />
  </div>
</template>
