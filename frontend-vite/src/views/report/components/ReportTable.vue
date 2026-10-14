<template>
  <div class="rp-table-wrap">
    <div v-if="isFetching" class="rp-fetching-bar"><div class="rp-fetching-progress" /></div>
    <UiDataTable
      :data="rows"
      :columns="uiColumns"
      :loading="isLoading && searched && !rows.length"
      :paginator="(pagination?.pages ?? 0) > 1"
      :rows="perPage"
      :total-records="pagination?.total ?? 0"
      row-key="__rk"
      :row-group-mode="isOrder ? 'rowspan' : undefined"
      :group-rows-by="isOrder ? GROUP_ROWS_BY : undefined"
      :striped="false"
      @sort="emit('sort', $event)"
      @page="emit('page', $event)"
    >
      <template #empty>
        <div class="rp-empty">
          <FontAwesomeIcon icon="chart-line" aria-hidden="true" />
          <span>{{ isFetching ? '加载中…' : '暂无数据' }}</span>
        </div>
      </template>

      <!-- 订单级三列（时间/单号/客户）在订单 tab 下合并成跨行大格，故三列的槽名是分组键
           （见 GROUP_FIELD_OF）：PrimeVue 按「列 field 的值相等」合并，槽名必须与 field 对齐。 -->
      <template #column-body-_g_date="{ row }">
        {{ cellText((row as Record<string, unknown>)[currentCfg.dateKey]) }}
      </template>
      <template #column-body-_g_no="{ row }">
        <span class="rp-no">{{ cellText((row as Record<string, unknown>)[currentCfg.noKey]) }}</span>
      </template>
      <template #column-body-_g_customer="{ row }">
        {{ cellText((row as Record<string, unknown>).customer) }}
      </template>
      <template #column-body-product_name="{ row }">
        {{ cellText((row as Record<string, unknown>).product_name) }}
      </template>
      <template #column-body-product_barcode="{ row }">
        <span class="rp-barcode">{{ cellText((row as Record<string, unknown>).product_barcode) }}</span>
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
        <!-- 每一行都是一个具体 SKU（订单级字段已合并在上方的跨行格里），故每行都挂操作 -->
        <div class="rp-action-group">
          <button
            v-if="canEdit"
            class="rp-btn-icon rp-btn-edit"
            :aria-label="`编辑 ${cellText((row as Record<string, unknown>).product_name)}`"
            @click="emit('row-edit', row)"
          >
            <FontAwesomeIcon icon="pen-to-square" aria-hidden="true" />
          </button>
          <button
            v-if="canDelete"
            class="rp-btn-icon rp-btn-danger"
            aria-label="删除该记录"
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
 * 2026-10-13（方案 C，Excel 风格跨行合并）：订单 tab 一行 = 一个 SKU，同一订单的
 * 「时间 / 单号 / 客户」三列并成一个跨行大格（PrimeVue 行合并 rowGroupMode='rowspan'）；
 * 产品名称/条码/数量/备注/操作逐行渲染 —— 它们各自属于具体 SKU。
 *
 * 合并判据是**列 field 的值相等**（PrimeVue 逐行比 field 值算跨度），所以这三列的 field
 * 不能直接用时间/客户原值：相邻两张不同订单只要客户同名，就会被并成一个跨行大格。
 * 做法是把三列的 field 换成分组键（见 GROUP_FIELD_OF）——订单 tab 下每行的键 = order_id
 * （组内唯一、跨组不同），显示值仍由 body 槽从原字段取 → 合并键与显示解耦。
 * 后端按订单分页且同一订单的 SKU 行相邻（report_service.get_order_logs），才有组可并；
 * 「数量」列客户端重排会把同一订单的 SKU 打散，那几列就退化成各自渲染（数据仍正确，只是不合并）。
 * 其余四个 tab 直接平铺（每行分组键各自唯一 → 永不合并）。
 */
import { computed } from 'vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { formatNumber } from '@/utils/format'
import type { TabConfig, TabType } from '../composables/useReportConfig'

const props = defineProps<{
  logs: Record<string, unknown>[]
  columns: TableColumn[]
  isLoading: boolean
  isFetching: boolean
  searched: boolean
  perPage: number
  pagination: { pages?: number; total?: number } | undefined
  currentCfg: TabConfig
  /** 当前 tab（用稳定 key 判断，不用中文 label） */
  activeTab: TabType
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

/**
 * 订单级三列 → 分组键字段名。键名刻意与显示字段（date/no/customer）分开：
 * 合并按键值判定，显示仍取原字段，二者解耦（理由见文件头注释）。
 */
const GROUP_FIELD_OF: Record<string, string> = {
  date: '_g_date',
  no: '_g_no',
  customer: '_g_customer',
}
const GROUP_ROWS_BY = ['_g_date', '_g_no', '_g_customer']

const isOrder = computed(() => props.activeTab === 'order')

/** 送进表格的列：订单级三列换成组内唯一的分组键，其余列（数量/备注/操作）原样逐行渲染 */
const uiColumns = computed<TableColumn[]>(() =>
  props.columns.map((c) => {
    const groupField = GROUP_FIELD_OF[c.field]
    return groupField ? { ...c, field: groupField } : c
  }),
)

/**
 * 渲染行：一行 = 一个 (订单 × SKU)，保持后端给的顺序（同订单相邻）。
 * 分组键在订单 tab 取 order_id（同订单同键 → 并成一个跨行格），其余 tab 取行号
 * （每行各自唯一 → 不合并，等价于平铺）。
 */
const rows = computed<Record<string, unknown>[]>(() =>
  props.logs.map((r, i) => {
    const groupKey = isOrder.value && r.order_id != null ? `o${String(r.order_id)}` : `r${i}`
    return {
      ...r,
      // 行唯一键：item_id 可能为 0（无明细的历史订单，后端 LEFT JOIN 出 NULL 后置 0），
      // 故再带上行号兜底，避免同一页出现重复 key
      __rk: `r-${String(r.item_id ?? 'x')}-${i}`,
      _g_date: groupKey,
      _g_no: groupKey,
      _g_customer: groupKey,
    }
  }),
)

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
.rp-no { color: var(--color-primary-700, #2d5ab8); font-weight: 600; }
.rp-barcode { color: var(--color-text-muted); }

/* 跨行合并格（时间/单号/客户）不再需要额外样式：PrimeVue 的 bodyCell 自带 align-middle，
   合并格天然是「一格跨多行、内部无分隔线」的 Excel 观感。刻意不给单 SKU 订单加左侧竖线 ——
   单 SKU 组的跨度为 1、PrimeVue 不输出 rowspan 属性，加了会变成「多 SKU 有、单 SKU 没有」的不一致。 */

/* 操作列（行内编辑/删除）：与原 OrderRecordTable 操作列同一套 */
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
.rp-btn-edit { background: var(--color-warning-50); color: var(--color-warning-600); }
.rp-btn-edit:hover { background: var(--color-warning-100); }
.rp-btn-danger { background: var(--color-danger-50); color: var(--color-danger-600); }
.rp-btn-danger:hover { background: var(--color-danger-100); }

/* 与 /stock 相同的表格处理：去掉 UiDataTable 容器的内层边框盒、固定表格布局
   （百分比列宽才是硬约束）、单元格单行省略、行分隔线随全局 PT 的 bodyRow 生效。 */
.rp-table-wrap :deep(.ui-data-table-wrapper) { border: 0; }
.rp-table-wrap :deep(table) { table-layout: fixed; }
.rp-table-wrap :deep([data-pc-section='bodycell']) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rp-table-wrap :deep([data-pc-section='bodyrow']:last-child) { border-bottom: 0; }

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
