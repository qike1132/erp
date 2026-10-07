<template>
  <div class="rp-table-wrap">
    <div v-if="isFetching" class="rp-fetching-bar"><div class="rp-fetching-progress" /></div>
    <UiDataTable
      :data="logs"
      :columns="columns"
      :loading="isLoading && searched && !logs.length"
      :paginator="(pagination?.pages ?? 0) > 1"
      :rows="perPage"
      :total-records="pagination?.total ?? 0"
      row-key="id"
      @sort="emit('sort', $event)"
      @page="emit('page', $event)"
    >
      <template #empty>
        <div class="rp-empty">
          <FontAwesomeIcon icon="chart-line" aria-hidden="true" />
          <span>{{ isFetching ? '加载中…' : '暂无数据' }}</span>
        </div>
      </template>
      <template #column-body-date="{ row }">
        {{ cellText((row as Record<string, unknown>)[currentCfg.dateKey]) }}
      </template>
      <template #column-body-customer="{ row }">
        {{ cellText((row as Record<string, unknown>).customer) }}
      </template>
      <template #column-body-product_name="{ row }">
        {{ cellText((row as Record<string, unknown>).product_name) }}
      </template>
      <template #column-body-quantity="{ row }">
        <span class="rp-qty">{{ fmtQty((row as Record<string, unknown>).quantity) }}</span>
      </template>
      <template #column-body-note="{ row }">
        <span
          class="rp-note"
          :title="cellText((row as Record<string, unknown>)[currentCfg.noteKey])"
        >{{ cellText((row as Record<string, unknown>)[currentCfg.noteKey]) }}</span>
      </template>
      <template v-if="canEdit || canDelete" #column-body-actions="{ row }">
        <div class="rp-action-group">
          <button
            v-if="canEdit"
            class="rp-btn-icon rp-btn-edit"
            :aria-label="`编辑 ${cellText((row as Record<string, unknown>).customer)} ${cellText((row as Record<string, unknown>).product_name)}`"
            @click="emit('row-edit', row)"
          >
            <FontAwesomeIcon icon="pen-to-square" aria-hidden="true" />
          </button>
          <button
            v-if="canDelete"
            class="rp-btn-icon rp-btn-danger"
            aria-label="删除该组记录"
            @click="emit('row-delete', row)"
          >
            <FontAwesomeIcon icon="trash-alt" aria-hidden="true" />
          </button>
        </div>
      </template>
    </UiDataTable>
  </div>
</template>

<script setup lang="ts">
/**
 * ReportTable.vue — 报表流水表格
 *
 * 展示约定与 /stock 一致：空值留白（不再显示「-」），数量走千分位并加粗；
 * 容器自带的内盒圆角/边框在本页抵消，表格与卡片齐平。
 */
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { formatNumber } from '@/utils/format'
import type { TabConfig } from '../composables/useReportConfig'

defineProps<{
  logs: Record<string, unknown>[]
  columns: TableColumn[]
  isLoading: boolean
  isFetching: boolean
  searched: boolean
  perPage: number
  pagination: { pages?: number; total?: number } | undefined
  currentCfg: TabConfig
  /** 行内编辑按钮门控（order_edit）；false 时该按钮不渲染 */
  canEdit?: boolean
  /** 行内删除按钮门控（order_delete）；false 时该按钮不渲染 */
  canDelete?: boolean
}>()

const emit = defineEmits<{
  'page': [event: { page: number; rows: number }]
  'sort': [event: { field: string; order: number }]
  'row-edit': [row: Record<string, unknown>]
  'row-delete': [row: Record<string, unknown>]
}>()

/** 文本列：缺失即留白（后端可能给 null / 空串，不做占位符） */
function cellText(v: unknown): string {
  return v == null || v === '' ? '' : String(v)
}

/** 数量列：有值走千分位，0 与空值留白 */
function fmtQty(v: unknown): string {
  const n = Number(v)
  return Number.isFinite(n) && n !== 0 ? formatNumber(n) : ''
}
</script>

<style scoped>
.rp-table-wrap {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.rp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.rp-empty svg {
  width: 28px;
  height: 28px;
  opacity: 0.5;
}
.rp-empty span { font-size: 14px; }
.rp-qty { font-weight: 700; }
.rp-note { color: var(--color-text-secondary); }

/* 操作列（订单/备货流水的行内编辑/删除）：与原 OrderRecordTable 操作列同一套
   （36×36 / FontAwesome / 同配色）；hover 只换背景色、不带 translateY 位移 ——
   位移会造成扫读抖动与每帧重排（CustomerOrderView 既有注释口径）。 */
.rp-action-group {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.rp-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease;
}
.rp-btn-edit {
  background: var(--color-warning-50);
  color: var(--color-warning-600);
}
.rp-btn-edit:hover {
  background: var(--color-warning-100);
}
.rp-btn-danger {
  background: var(--color-danger-50);
  color: var(--color-danger-600);
}
.rp-btn-danger:hover {
  background: var(--color-danger-100);
}

/* 与 /stock 相同的表格处理：去掉 UiDataTable 容器的内层边框盒、固定表格布局
   （百分比列宽才是硬约束）、单元格单行省略、行分隔线随全局 PT 的 bodyRow 生效。 */
.rp-table-wrap :deep(.ui-data-table-wrapper) {
  border: 0;
}
.rp-table-wrap :deep(table) { table-layout: fixed; }
.rp-table-wrap :deep([data-pc-section='bodycell']) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rp-table-wrap :deep([data-pc-section='bodyrow']:last-child) {
  border-bottom: 0;
}

/* 排序图标：生产为 unstyled 模式，图标不带任何 class，只能靠 data-pc-section 命中 */
.rp-table-wrap :deep([data-pc-section='columnheadercontent']) {
  display: inline-flex;
  align-items: center;
}
.rp-table-wrap :deep([data-pc-section='sort']) {
  display: inline-flex;
  align-items: center;
  margin-left: 4px;
}
.rp-table-wrap :deep([data-pc-section='sorticon']) {
  width: 10px;
  height: 10px;
  color: #cbd5e1;
  transition: color 0.15s ease;
}
.rp-table-wrap :deep(th[data-p-sortable-column='true']) { cursor: pointer; }
.rp-table-wrap :deep(th[data-p-sortable-column='true']:hover [data-pc-section='sorticon']) {
  color: var(--color-primary-500);
}
.rp-table-wrap :deep(th[aria-sort='ascending'] [data-pc-section='sorticon']),
.rp-table-wrap :deep(th[aria-sort='descending'] [data-pc-section='sorticon']) {
  color: var(--color-primary-600);
}
.rp-table-wrap :deep(th[aria-sort='ascending'] [data-pc-section='columntitle']),
.rp-table-wrap :deep(th[aria-sort='descending'] [data-pc-section='columntitle']) {
  color: var(--color-primary-700);
}

.rp-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.rp-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: rp-progress-slide 1s ease-in-out infinite;
}
@keyframes rp-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
