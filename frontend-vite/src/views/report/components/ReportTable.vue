<template>
  <div class="rp-table-wrap">
    <div v-if="isFetching" class="rp-fetching-bar"><div class="rp-fetching-progress" /></div>
    <UiDataTable
      :data="rows"
      :columns="columns"
      :loading="isLoading && searched && !rows.length"
      :paginator="(pagination?.pages ?? 0) > 1"
      :rows="perPage"
      :total-records="pagination?.total ?? 0"
      row-key="__rk"
      :row-class="rowClassOf"
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

      <!-- 展开列：母行箭头 / 子行树线（仅订单 tab 有该列） -->
      <template #column-body-expand="{ row }">
        <button
          v-if="row._kind === 'parent'"
          class="rp-caret"
          :class="{ open: isExpanded(Number(row.order_id)) }"
          :aria-label="isExpanded(Number(row.order_id)) ? '收起 SKU' : '展开 SKU'"
          @click="toggle(Number(row.order_id))"
        >▶</button>
        <span v-else-if="row._kind === 'child'" class="rp-tree">└</span>
      </template>

      <template #column-body-date="{ row }">
        {{ cellText((row as Record<string, unknown>)[currentCfg.dateKey]) }}
      </template>
      <template #column-body-no="{ row }">
        <span class="rp-no">{{ cellText((row as Record<string, unknown>)[currentCfg.noKey]) }}</span>
      </template>
      <template #column-body-customer="{ row }">
        {{ cellText((row as Record<string, unknown>).customer) }}
      </template>
      <template #column-body-product_name="{ row }">
        <span v-if="row._kind === 'parent'" class="rp-muted">共 {{ row.item_count }} 个 SKU</span>
        <span v-else>{{ cellText((row as Record<string, unknown>).product_name) }}</span>
      </template>
      <template #column-body-product_barcode="{ row }">
        <span class="rp-barcode">{{ cellText((row as Record<string, unknown>).product_barcode) }}</span>
      </template>
      <template #column-body-quantity="{ row }">
        <span class="rp-qty">{{
          fmtQty(row._kind === 'parent' ? row.order_total_qty : (row as Record<string, unknown>).quantity)
        }}</span>
      </template>
      <template #column-body-note="{ row }">
        <span
          class="rp-note"
          :title="cellText((row as Record<string, unknown>)[currentCfg.noteKey])"
        >{{ cellText((row as Record<string, unknown>)[currentCfg.noteKey]) }}</span>
      </template>
      <template v-if="canEdit || canDelete" #column-body-actions="{ row }">
        <!-- 母行（多 SKU 订单头）不挂操作：按钮只作用于具体 SKU 行 -->
        <div v-if="row._kind !== 'parent'" class="rp-action-group">
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
 * 2026-10-13：订单 tab 改母行-明细——按 order_id 把「一行一 SKU」的扁平结果聚成
 * 母行（订单）+ 子行（SKU）；单 SKU 订单压成一行。母行与子行是**同一张表的真实行**、
 * 共用同一 `<colgroup>`，靠 `rowClass` 区分样式、不做左缩进 → 产品名称/条码/数量/
 * 备注/操作永远与表头对齐。展开/折叠 = 前端增删子行。
 * 其余四个 tab 直接平铺（一行 = 一条记录）。
 */
import { computed, ref, watch } from 'vue'
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

/** 展开的订单 id 集合（仅订单 tab 用） */
const expanded = ref<Set<number>>(new Set())
function isExpanded(orderId: number): boolean {
  return expanded.value.has(orderId)
}
function toggle(orderId: number) {
  const next = new Set(expanded.value)
  if (next.has(orderId)) next.delete(orderId)
  else next.add(orderId)
  expanded.value = next
}
// 切 tab 时收起（避免上一屏的展开态串场）
watch(() => props.activeTab, () => { expanded.value = new Set() })

interface OrderGroup {
  order_id: number
  fields: Record<string, unknown>
  items: Record<string, unknown>[]
}

/** 把「一行一 SKU」的订单流水按 order_id 聚成订单组（保持首次出现顺序） */
function groupByOrder(logs: Record<string, unknown>[]): OrderGroup[] {
  const map = new Map<number, OrderGroup>()
  for (const r of logs) {
    const oid = Number(r.order_id ?? 0)
    let g = map.get(oid)
    if (!g) {
      g = {
        order_id: oid,
        fields: {
          order_id: oid,
          order_no: r.order_no ?? '',
          order_date: r.order_date ?? '',
          customer: r.customer ?? '',
          order_note: r.order_note ?? '',
          note: r.order_note ?? '',   // 母行备注列显示订单备注（noteKey='note'）
          item_count: r.item_count ?? 1,
          order_total_qty: r.order_total_qty ?? 0,
        },
        items: [],
      }
      map.set(oid, g)
    }
    g.items.push(r)
  }
  return [...map.values()]
}

/** 渲染行：订单 tab = 母行/子行/单 SKU 压一行；其余 tab = 平铺 */
const rows = computed<Record<string, unknown>[]>(() => {
  if (props.activeTab !== 'order') {
    return props.logs.map((r, i) => ({ ...r, _kind: 'flat', __rk: `f-${String(r.record_id ?? i)}-${i}` }))
  }
  const out: Record<string, unknown>[] = []
  for (const g of groupByOrder(props.logs)) {
    if (g.items.length === 1) {
      out.push({ ...g.items[0], ...g.fields, _kind: 'single', __rk: `o-${g.order_id}` })
    } else {
      out.push({ ...g.fields, _kind: 'parent', __rk: `o-${g.order_id}` })
      if (expanded.value.has(g.order_id)) {
        for (const it of g.items) {
          out.push({ ...it, ...g.fields, _kind: 'child', __rk: `i-${String(it.item_id)}` })
        }
      }
    }
  }
  return out
})

function rowClassOf(row: Record<string, unknown>): string {
  const k = row._kind
  if (k === 'parent') return 'order-row'
  if (k === 'child') return 'child-row'
  if (k === 'single') return 'order-row single-row'
  return ''
}

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
.rp-muted { color: var(--color-text-muted); }
.rp-no { color: var(--color-primary-700, #2d5ab8); font-weight: 600; }
.rp-barcode { color: var(--color-text-muted); }

/* 展开箭头 / 子行树线（层级不靠缩进，只靠首列字符 → 不破坏列对齐） */
.rp-caret {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 6px; border: 1px solid var(--color-border, #e4e7ed);
  background: #fff; color: var(--color-text-secondary); cursor: pointer; font-size: 10px;
  transition: transform 0.18s ease, background 0.18s, color 0.18s;
}
.rp-caret:hover { background: var(--color-primary-50, #eff5ff); color: var(--color-primary-600); }
.rp-caret.open { transform: rotate(90deg); color: var(--color-primary-600); }
.rp-tree { color: #9db8e0; font-size: 13px; }

/* 子行：靠底色 + 左侧竖线表示层级，不做任何左缩进（否则破坏列对齐） */
.rp-table-wrap :deep(tr.child-row) { background: #f8fbff; }
.rp-table-wrap :deep(tr.child-row:hover) { background: #eef5ff; }
.rp-table-wrap :deep(tr.child-row td:first-child) { border-left: 3px solid var(--color-primary-100, #d6e4ff); }

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
