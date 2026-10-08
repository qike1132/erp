<template>
  <UiDrawer
    :visible="open"
    centered
    :dismissable="false"
    title="生产明细"
    width="1360px"
    @update:visible="emit('update:open', $event)"
  >
    <!-- rec-scope：只放大本面板内的表格/控件，不影响全站其它表格（见下方 scoped 样式） -->
    <div class="rec-scope">
      <RecordFilterBar
        :filters="filters"
        :departments="departments"
        :created-by-options="createdByOptions"
        @update:filters="emit('update:filters', $event)"
        @search="emit('search')"
        @export="emit('export')"
      />

      <div
        data-test="drawer-summary"
        class="flex flex-wrap items-center gap-4 border-b border-border-light px-4 py-3 text-sm font-semibold text-text-secondary"
      >
        <!-- 总条数不在这一行重复：表格底部的 UiPagination 已带「共 N 条」 -->
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
            <span class="rounded bg-surface px-2 py-0.5 text-[13px] font-bold">
              {{ deptLabel(row.department) }}
            </span>
          </template>
          <template #column-body-production_date="{ row }">{{ row.production_date }}</template>
          <template #column-body-quantity="{ row }">
            <strong class="tabular-nums">{{ formatNumber(row.quantity) }}</strong>
          </template>
          <template #column-body-production_value="{ row }">{{ formatCurrency(row.production_value) }}</template>
          <template #column-body-actions="{ row }">
            <span data-test="record-row" class="flex items-center justify-center gap-2">
              <button
                type="button"
                data-test="record-edit"
                class="rec-act rec-act--edit"
                title="编辑这条记录"
                @click="emit('edit', row)"
              >
                <FontAwesomeIcon icon="pen-to-square" aria-hidden="true" />
                <span>改</span>
              </button>
              <button
                type="button"
                data-test="record-delete"
                class="rec-act rec-act--del"
                title="删除这条记录"
                @click="askDelete(row)"
              >
                <FontAwesomeIcon icon="trash-can" aria-hidden="true" />
                <span>删</span>
              </button>
            </span>
          </template>
        </UiDataTable>
      </div>
    </div>

    <!-- 删除二次确认：后端是物理删除且不可恢复，必须写明「删的是哪一条」。
         复用共享的 UiConfirmDialog —— 它自带焦点陷阱、Escape 关闭与滚动锁，
         这是全站最危险的操作，不能自建一个更弱的模态。
         抽屉是 PrimeVue 的 Drawer，其遮罩 z 由 PrimeVue 定为 2100（main.ts 的
         zIndex.modal=2100）。确认框必须落在超出该层的嵌套层级（--z-overlay/modal-nested，
         2200/2210），否则会被遮罩压住、点不到 —— 确认框在遮罩之下时，点击落在遮罩上
         反而直接把抽屉关了，删除护栏等于不存在。 -->
    <UiConfirmDialog
      :open="!!pendingDelete"
      type="danger"
      text="确认删除这条生产记录？"
      :sub="deleteSummary"
      overlay-z-class="z-[var(--z-overlay-nested)]"
      content-z-class="z-[var(--z-modal-nested)]"
      @confirm="confirmDelete"
      @cancel="pendingDelete = null"
    />
  </UiDrawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import UiConfirmDialog from '@/components/ui/UiConfirmDialog.vue'
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
// 两者并列属重复信息，而居中面板可用宽度约 1100px，十列会挤到每列都要截断。
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
  export: []
  edit: [record: DailyProductionRecord]
  'confirm-delete': [id: number]
}>()

const pendingDelete = ref<DailyProductionRecord | null>(null)

/**
 * 本面板可被 Esc / 右上角 ✕ 关闭（点遮罩空白有意不关，见模板的 :dismissable="false"），
 * 而本组件由父级无条件渲染、关闭后并不卸载。若不清空 pendingDelete，
 * 重开抽屉会对一条已失去上下文的记录弹出删除确认 —— 对不可恢复的物理删除
 * 来说这是不可接受的，故抽屉一关就丢弃待删除状态。
 */
watch(
  () => props.open,
  (open) => {
    if (!open) pendingDelete.value = null
  },
)

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

<style scoped>
/* 「操作」列按钮：原先只是纯文字链接，字号小、不像可点控件。改成按钮形态。 */
.rec-act {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.rec-act--edit {
  color: var(--color-primary-600);
  background: var(--color-primary-50);
  border-color: var(--color-primary-200);
}
.rec-act--edit:hover {
  color: #fff;
  background: var(--color-primary-600);
  border-color: var(--color-primary-600);
}
.rec-act--del {
  color: var(--color-danger-600);
  background: var(--color-danger-50);
  border-color: var(--color-danger-200);
}
.rec-act--del:hover {
  color: #fff;
  background: var(--color-danger-600);
  border-color: var(--color-danger-600);
}

/* 明细整体放大：只作用于本面板（.rec-scope 之内），全站其它表格不受影响 */
.rec-scope :deep(td) {
  padding: 16px 12px;
  font-size: 15px;
}
.rec-scope :deep(th) {
  padding: 14px 12px;
  font-size: 13px;
}
.rec-scope :deep(.ui-select-input) {
  height: 46px;
  font-size: 14px;
}
</style>
