<template>
  <UiDrawer
    :visible="open"
    title="生产明细"
    width="960px"
    @update:visible="emit('update:open', $event)"
  >
    <RecordFilterBar
      :filters="filters"
      :departments="departments"
      :created-by-options="createdByOptions"
      @update:filters="emit('update:filters', $event)"
      @search="emit('search')"
    />

    <div
      data-test="drawer-summary"
      class="flex flex-wrap items-center gap-3 border-b border-border-light px-4 py-2 text-xs font-semibold text-text-secondary"
    >
      <span>共 {{ total }} 条</span>
      <span>合计产量 {{ formatNumber(summaryQuantity) }} 件</span>
      <span>合计产值 {{ formatCurrency(summaryValue) }}</span>
      <span v-if="summarySku !== null">涉及 {{ summarySku }} 个品种</span>
    </div>

    <div class="flex min-h-0 flex-1 flex-col">
      <UiSkeleton v-if="loading" variant="table" :rows="6" />

      <UiEmpty
        v-else-if="!records.length"
        data-test="records-empty"
        icon="fas fa-inbox"
        text="当前筛选下暂无记录"
      />

      <UiDataTable
        v-else
        :data="records"
        :columns="COLUMNS"
        row-key="id"
        paginator
        :rows="filters.perPage"
        :total-records="total"
        @page="onPage"
      >
        <template #column-body-department="{ row }">
          <span class="rounded bg-surface-sunken px-1.5 py-0.5 text-[11px] font-bold">
            {{ deptLabel(row.department) }}
          </span>
        </template>
        <template #column-body-production_date="{ row }">{{ row.production_date }}</template>
        <template #column-body-quantity="{ row }">
          <strong class="tabular-nums">{{ formatNumber(row.quantity) }}</strong>
        </template>
        <template #column-body-production_value="{ row }">{{ formatCurrency(row.production_value) }}</template>
        <template #column-body-actions="{ row }">
          <span data-test="record-row" class="flex justify-center gap-2">
            <button data-test="record-edit" class="text-xs font-bold text-primary-600" @click="emit('edit', row)">改</button>
            <button data-test="record-delete" class="text-xs font-bold text-danger-600" @click="askDelete(row)">删</button>
          </span>
        </template>
      </UiDataTable>
    </div>

    <!-- 删除二次确认：后端是物理删除且不可恢复，必须写明「删的是哪一条」。
         UiConfirmDialog 经 reka-ui DialogPortal 传送内容到 body，且不暴露逐实例的
         测试锚点与自定义按钮，无法满足「确认文本含产品名/数量」的可测性要求，
         故此处内联一个语义等价的确认层。 -->
    <div
      v-if="pendingDelete"
      data-test="delete-confirm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="record-delete-title"
      class="fixed inset-0 z-[var(--z-modal)] flex items-center justify-center bg-black/40 p-4"
    >
      <div class="w-full max-w-[420px] rounded-2xl bg-surface-card p-6 shadow-lg">
        <div class="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-danger-50 text-xl text-danger-500">
          <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
        </div>
        <p id="record-delete-title" class="m-0 text-center text-base font-semibold text-heading">
          确认删除这条生产记录？
        </p>
        <p class="mb-0 mt-2 text-center text-sm text-text-secondary">{{ deleteSummary }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <UiButton variant="outline" data-test="delete-cancel" @click="pendingDelete = null">取消</UiButton>
          <UiButton variant="danger" data-test="delete-confirm-btn" @click="confirmDelete">确认删除</UiButton>
        </div>
      </div>
    </div>
  </UiDrawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

import UiButton from '@/components/ui/UiButton.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import UiDrawer from '@/components/ui/UiDrawer.vue'
import UiEmpty from '@/components/ui/UiEmpty.vue'
import UiSkeleton from '@/components/ui/UiSkeleton.vue'
import { formatCurrency, formatNumber } from '@/utils/format'
import type { DailyProductionRecord, ProductionRecordStats } from '@/types'
import { DEPT_LABELS } from '../composables/trendChartOption'
import RecordFilterBar from './RecordFilterBar.vue'
import type { RecordFilters } from '../composables/recordFilters'

// 规格 §4.2 的列清单里还有「单价」，此处有意不展示：产值 = 单价 × 数量，
// 两者并列属重复信息，而抽屉可用宽度约 960px，十列会挤到每列都要截断。
// 单价仍可在编辑弹窗里查看与修改（Task 10）。
const COLUMNS: TableColumn[] = [
  { field: 'production_date', header: '日期', width: '96px' },
  { field: 'department', header: '部门', width: '80px', align: 'center' },
  { field: 'product_name', header: '产品' },
  { field: 'barcode', header: '69 码', width: '110px' },
  { field: 'quantity', header: '数量', width: '80px', align: 'right' },
  { field: 'production_value', header: '产值', width: '100px', align: 'right' },
  { field: 'remark', header: '备注' },
  { field: 'created_by', header: '录单人', width: '90px' },
  { field: 'actions', header: '操作', width: '80px', align: 'center' },
]

const props = defineProps<{
  open: boolean
  filters: RecordFilters
  records: DailyProductionRecord[]
  total: number
  stats: ProductionRecordStats | null
  loading: boolean
  departments: string[]
  createdByOptions: Array<{ label: string; value: string }>
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'update:filters': [value: RecordFilters]
  search: []
  edit: [record: DailyProductionRecord]
  'confirm-delete': [id: number]
}>()

const pendingDelete = ref<DailyProductionRecord | null>(null)

/** stats 为 null（当前筛选无记录）时一律显示 0 —— 绝不显示 NaN 或空白 */
const summaryQuantity = computed(() => props.stats?.total_quantity ?? 0)
const summaryValue = computed(() => props.stats?.total_value ?? 0)
const summarySku = computed(() => props.stats?.total_sku ?? null)

const deleteSummary = computed(() => {
  const row = pendingDelete.value
  if (!row) return ''
  return `${row.product_name} · ${formatNumber(row.quantity)} 件 · ${row.production_date} · ${deptLabel(row.department)}`
})

function deptLabel(department: string): string {
  return DEPT_LABELS[department] ?? department
}

function askDelete(row: DailyProductionRecord) {
  pendingDelete.value = row
}

function confirmDelete() {
  if (pendingDelete.value) emit('confirm-delete', pendingDelete.value.id)
  pendingDelete.value = null
}

/**
 * UiDataTable 的 `page` 事件是 **0 基**（内部 `emit('page', { page: page - 1 })`），
 * 而 RecordFilters.page / 后端 `/records` 的 page 都是 **1 基**（后端 `offset = (page-1)*per_page`），
 * 故这里 +1。全仓库消费 UiDataTable 的视图都是这么转的。
 */
function onPage(event: { page: number; rows: number }) {
  emit('update:filters', { ...props.filters, page: event.page + 1, perPage: event.rows })
}
</script>
