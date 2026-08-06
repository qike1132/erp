<script setup lang="ts" generic="T extends Record<string, unknown>">
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
import { DataTable, Column, Paginator } from 'primevue'
import type { DataTablePageEvent, DataTableSortEvent } from 'primevue'

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
    totalRecords: 0,
    selection: () => null,
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
// Handlers
// ============================================================
function onPage(event: DataTablePageEvent) {
  emit('page', { page: event.page, rows: event.rows })
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
      :selectionMode="selection !== null ? 'multiple' : undefined"
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

    <!-- 分页器（独立渲染，样式完全受 PT 控制） -->
    <Paginator
      v-if="paginator"
      :rows="rows"
      :totalRecords="totalRecords || data.length"
      :rowsPerPageOptions="[10, 20, 50, 100]"
      @page="onPage"
    />
  </div>
</template>
