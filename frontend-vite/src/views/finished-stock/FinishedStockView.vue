<template>
  <div class="fs-page">
    <!-- 工具条：汇总 + 搜索 + 导出 -->
    <div class="fs-toolbar">
      <div class="fs-stat-row">
        <div class="fs-stat">
          <div class="fs-stat-top"><span class="fs-stat-dot" style="background: var(--color-info-500)" /><span class="fs-stat-label">可用库存</span></div>
          <div class="fs-stat-value">{{ fmtNum(totalAvailable) }}</div>
        </div>
      </div>
      <div class="fs-search">
        <FontAwesomeIcon icon="search" class="fs-search-icon" aria-hidden="true" />
        <input v-model="filters.product" class="fs-search-input" placeholder="输入产品名称或 69 码" aria-label="搜索成品库存" />
      </div>
      <button class="fs-export-btn" aria-label="导出"><FontAwesomeIcon icon="file-excel" aria-hidden="true" />导出 Excel</button>
    </div>

    <!-- 客户快捷切换行 -->
    <div class="fs-customer-row">
      <span class="fs-customer-label"><FontAwesomeIcon icon="users" aria-hidden="true" />客户</span>
      <div class="fs-chip-scroll">
        <button type="button" :class="['fs-chip', { active: !filters.customer }]" @click="filters.customer = ''">
          <FontAwesomeIcon icon="th-large" aria-hidden="true" />全部
        </button>
        <button
          v-for="c in customerList"
          :key="c"
          type="button"
          :class="['fs-chip', { active: filters.customer === c }]"
          @click="filters.customer = c"
        >{{ c }}</button>
      </div>
    </div>

    <!-- 表格：SKU 大格（图片/产品名/69码跨行合并）+ 批次子行 -->
    <div class="fs-card-main">
      <UiDataTable
        :data="tableRows"
        :columns="uiColumns"
        :loading="isLoading"
        :paginator="(data?.total ?? 0) > perPage"
        :rows="perPage"
        :total-records="data?.total ?? 0"
        row-key="__rk"
        row-group-mode="rowspan"
        :group-rows-by="GROUP_ROWS_BY"
        @page="onPage"
        @sort="onSort"
      >
        <!-- 产品图片（SKU 大格内，与产品名同行显示） -->
        <template #column-body-_g_product="{ row }">
          <span class="fs-sku-cell">
            <span v-if="(row as FinishedStockItem).image && !failedKeys.has((row as FinishedStockItem).barcode)" class="fs-thumb-box">
              <img loading="lazy" :src="thumbSrc(row as FinishedStockItem)" :alt="(row as FinishedStockItem).product_name" @error="onImgError(row as FinishedStockItem)" />
            </span>
            <span v-else class="fs-no-image"><FontAwesomeIcon icon="file-image" aria-hidden="true" /></span>
            <strong>{{ (row as FinishedStockItem).product_name }}</strong>
          </span>
        </template>
        <!-- 批次号 -->
        <template #column-body-batch_no="{ row }">
          <span v-if="(row as FinishedStockItem).batch_no" class="fs-badge-batch">{{ (row as FinishedStockItem).batch_no }}</span>
          <span v-else class="fs-badge-none">(未分批次)</span>
        </template>
        <!-- 库存 -->
        <template #column-body-batch_available="{ row }">
          <span v-if="(row as FinishedStockItem).batch_available <= 100" class="fs-qty-low">
            <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />{{ fmtNum((row as FinishedStockItem).batch_available) }}
          </span>
          <span v-else class="fs-qty-ok">{{ fmtNum((row as FinishedStockItem).batch_available) }}</span>
        </template>
        <!-- 定制 -->
        <template #column-body-is_custom="{ row }">
          <span v-if="(row as FinishedStockItem).is_custom" class="fs-badge-custom">{{ (row as FinishedStockItem).custom_country }}</span>
          <span v-else class="fs-dash">—</span>
        </template>
        <template #empty>
          <div class="fs-empty"><FontAwesomeIcon icon="boxes-stacked" aria-hidden="true" /><span>暂无成品库存</span></div>
        </template>
      </UiDataTable>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * FinishedStockView.vue — 成品库存（批次级）
 *
 * 布局（Excel 风格 SKU 行合并）：一行 = 一个批次；同一产品的
 * 「图片 / 产品名称 / 69码」并成一个跨行大格（SKU 大格），
 * 批次号 / 库存 / 定制 逐行渲染 —— 它们各自属于具体批次。
 * 机制照 views/report/components/ReportTable.vue（PrimeVue rowGroupMode='rowspan'）：
 * 要合并的列 field 换成分组键（_g_*），显示值仍从 body 槽取原字段，
 * 分组键 = barcode（同 SKU 同键 → 并成一个大格）。
 *
 * 数据源 GET /finished-stock/summary（与 /stock 同源：包装部入库 + 批次出货扣减）。
 */
import { ref, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { formatNumber } from '@/utils/format'
import { resolveStaticUrl } from '@/api/request'
import { finishedStockApi } from '@/api'
import { batchSortKey } from './batchSort'
import type { FinishedStockItem } from '@/types'

const filters = ref({ customer: '', product: '' })
const page = ref(1)
const perPage = ref(20)
/** 排序态：批次号/库存 列可点（order: 1 升序 / -1 降序） */
const sort = ref<{ field: string; order: number } | null>(null)

const { data, isLoading } = useQuery({
  queryKey: ['finished-stock', () => filters.value.customer, () => filters.value.product, () => page.value, () => perPage.value],
  queryFn: () => finishedStockApi.summary({
    customer: filters.value.customer || undefined,
    product: filters.value.product || undefined,
    page: page.value,
    per_page: perPage.value,
  }),
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

const customerList = computed(() => (data.value?.all_customers ?? []) as string[])

/** 图片加载失败的行（按 barcode 记），失败后退化成「无图」占位 */
const failedKeys = ref<Set<string>>(new Set())
function onImgError(row: FinishedStockItem): void { failedKeys.value.add(row.barcode) }
function thumbSrc(row: FinishedStockItem): string {
  return resolveStaticUrl(row.image || '')
}

/** 要合并成 SKU 大格的列 → 分组键字段（与 ReportTable.GROUP_FIELD_OF 同思路） */
const GROUP_FIELD_OF: Record<string, string> = {
  image: '_g_image',
  product_name: '_g_product',
  barcode: '_g_barcode',
}
const GROUP_ROWS_BY = ['_g_image', '_g_product', '_g_barcode']

const baseColumns: TableColumn[] = [
  { field: 'image', header: '图片', align: 'center', width: '84px' },
  { field: 'product_name', header: '产品名称', align: 'left', width: '26%' },
  { field: 'barcode', header: '69码', align: 'left', width: '16%' },
  { field: 'batch_no', header: '批次号', align: 'left', sortable: true, width: '22%' },
  { field: 'batch_available', header: '库存', align: 'center', sortable: true, width: '12%' },
  { field: 'is_custom', header: '定制', align: 'center', width: '8%' },
]
const uiColumns = computed(() => baseColumns.map((c) => ({ ...c, field: GROUP_FIELD_OF[c.field] ?? c.field })))

function fmtNum(v: unknown): string {
  const n = Number(v)
  return Number.isFinite(n) && n !== 0 ? formatNumber(n) : String(n === 0 ? 0 : '')
}

/** 排序取值：批次号走专用键（见 batchSort），其余按数值。 */
function sortVal(row: Record<string, unknown>, field: string): number | string {
  if (field === 'batch_no') return batchSortKey(row.batch_no)
  const n = Number(row[field])
  return Number.isFinite(n) ? n : 0
}

/** 按产品（barcode）聚合，同 SKU 的批次行相邻 */
const skuGroups = computed(() => {
  const items = (data.value?.data ?? []) as FinishedStockItem[]
  const map = new Map<string, FinishedStockItem[]>()
  for (const r of items) {
    const arr = map.get(r.barcode)
    if (arr) arr.push(r)
    else map.set(r.barcode, [r])
  }
  // SKU 组按产品名稳定排列、不参与列排序（否则点库存列会把组序打乱、破坏合并观感）
  const groups = [...map.entries()].sort((a, b) =>
    (a[1][0]?.product_name ?? '').localeCompare(b[1][0]?.product_name ?? '', 'zh'),
  )
  const out: (FinishedStockItem & Record<string, unknown>)[] = []
  for (const [barcode, rows] of groups) {
    // 组内按当前排序列排；默认按批次号升序（= 生产时间正序）
    const s = sort.value
    const ordered = s
      ? [...rows].sort((x, y) => {
          const a = sortVal(x as unknown as Record<string, unknown>, s.field)
          const b = sortVal(y as unknown as Record<string, unknown>, s.field)
          return (a < b ? -1 : a > b ? 1 : 0) * s.order
        })
      : [...rows].sort((x, y) => batchSortKey(x.batch_no).localeCompare(batchSortKey(y.batch_no)))
    for (const r of ordered) {
      out.push({
        ...r,
        barcode,
        __rk: `${barcode}-${r.batch_no || 'none'}`,
        _g_image: barcode,
        _g_product: barcode,
        _g_barcode: barcode,
      })
    }
  }
  return out
})

const tableRows = computed(() => skuGroups.value)
const totalAvailable = computed(() => tableRows.value.reduce((s, r) => s + Number(r.batch_available || 0), 0))

/** PrimeVue 排序事件：order 为 1 升序 / -1 降序 / 0 取消 */
function onSort(event: { field: string; order: number }) {
  sort.value = event.order ? { field: event.field, order: event.order } : null
}

function onPage(event: { page: number; rows: number }) {
  page.value = event.page + 1
  perPage.value = event.rows
}
</script>

<style scoped>
.fs-page { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.fs-toolbar { display: flex; align-items: center; gap: 14px; padding: 10px 20px; min-height: 62px; border-bottom: 1px solid var(--color-border-light, #f0f2f5); flex-shrink: 0; }
.fs-toolbar > .fs-search { margin-left: auto; }
.fs-stat-row { display: flex; align-items: center; flex-shrink: 0; }
.fs-stat { display: flex; flex-direction: column; gap: 1px; padding: 0 16px; }
.fs-stat + .fs-stat { border-left: 1px solid var(--color-border-light, #f0f2f5); }
.fs-stat-top { display: flex; align-items: center; gap: 5px; }
.fs-stat-dot { width: 6px; height: 6px; border-radius: 2px; flex-shrink: 0; }
.fs-stat-label { font-size: 11px; font-weight: 500; color: var(--color-text-secondary); white-space: nowrap; }
.fs-stat-value { font-size: 17px; font-weight: 700; line-height: 1.2; color: var(--color-text); white-space: nowrap; font-variant-numeric: tabular-nums; }
.fs-search { position: relative; flex-shrink: 0; }
.fs-search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); width: 13px; height: 13px; color: var(--color-text-muted); pointer-events: none; }
.fs-search-input { width: 230px; padding: 7px 12px 7px 30px; border: 1.5px solid var(--color-border); border-radius: 9px; background: #fff; font-size: 12.5px; font-family: inherit; color: var(--color-text); outline: none; }
.fs-search-input::placeholder { color: var(--color-text-muted); }
.fs-search-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91,141,239,0.15); }
.fs-export-btn { display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0; padding: 7px 14px; border: 1.5px solid var(--color-success-200); border-radius: 9px; background: #fff; font-family: inherit; font-size: 12.5px; font-weight: 600; color: var(--color-success-600); white-space: nowrap; cursor: pointer; }
.fs-export-btn:hover { background: var(--color-success-50); border-color: var(--color-success-500); }

.fs-customer-row { display: flex; align-items: center; gap: 10px; padding: 9px 20px; border-bottom: 1px solid var(--color-border-light); background: linear-gradient(to bottom, var(--color-slate-50), #fff); flex-shrink: 0; }
.fs-customer-label { display: flex; align-items: center; gap: 5px; flex-shrink: 0; font-size: 11.5px; font-weight: 600; color: var(--color-text-secondary); white-space: nowrap; }
.fs-customer-label svg { width: 12px; height: 12px; color: var(--color-primary-500); }
.fs-chip-scroll { display: flex; gap: 6px; overflow-x: auto; flex: 1; min-width: 0; padding: 2px 0; scrollbar-width: none; }
.fs-chip-scroll::-webkit-scrollbar { display: none; }
.fs-chip { display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0; padding: 5px 14px; border: 1.5px solid var(--color-border); border-radius: 999px; background: #fff; font-family: inherit; font-size: 12px; font-weight: 600; color: var(--color-text-secondary); white-space: nowrap; cursor: pointer; user-select: none; transition: all .2s ease; }
.fs-chip svg { width: 11px; height: 11px; }
.fs-chip:hover { border-color: var(--color-primary-500); color: var(--color-primary-600); }
.fs-chip.active { background: var(--color-primary-600); border-color: var(--color-primary-600); color: #fff; }

.fs-card-main { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
.fs-card-main :deep(.ui-data-table-wrapper) { flex: 1; min-height: 0; display: flex; flex-direction: column; border: 0; }
.fs-card-main :deep([data-pc-name='datatable']) { flex: 1; min-height: 0; overflow-y: auto; scrollbar-gutter: stable; }
.fs-card-main :deep(.ui-pagination) { flex-shrink: 0; }
.fs-card-main :deep(table) { table-layout: fixed; }
.fs-card-main :deep([data-pc-section='bodycell']) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-card-main :deep([data-pc-section='bodyrow']:last-child) { border-bottom: 0; }
.fs-card-main :deep([data-pc-section='sorticon']) { width: 10px; height: 10px; color: #cbd5e1; }
.fs-card-main :deep(th[aria-sort='ascending'] [data-pc-section='sorticon']),
.fs-card-main :deep(th[aria-sort='descending'] [data-pc-section='sorticon']) { color: var(--color-primary-600); }

.fs-sku-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.fs-sku-cell strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-thumb-box {
  width: 44px; height: 44px; flex-shrink: 0; border-radius: 8px; overflow: hidden;
  background: var(--color-surface, #f8fafc); display: flex; align-items: center; justify-content: center;
}
.fs-thumb-box img { width: 100%; height: 100%; object-fit: contain; }
.fs-no-image {
  width: 44px; height: 44px; flex-shrink: 0; border-radius: 8px; display: flex; align-items: center;
  justify-content: center; background: var(--color-surface, #f8fafc); color: var(--color-text-secondary);
  font-size: 18px; opacity: 0.5;
}
.fs-badge-batch { display: inline-flex; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--color-primary-50); color: var(--color-primary-700); white-space: nowrap; }
.fs-badge-none { display: inline-flex; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 500; background: var(--color-slate-100); color: var(--color-slate-400); white-space: nowrap; }
.fs-badge-custom { display: inline-flex; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--color-purple-100); color: var(--color-purple-600); white-space: nowrap; }
.fs-dash { color: var(--color-slate-300); }
.fs-qty-ok { font-weight: 600; }
.fs-qty-low { color: var(--color-danger-600); font-weight: 700; display: inline-flex; align-items: center; gap: 4px; }
.fs-qty-low svg { width: 11px; height: 11px; }
.fs-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 20px; color: var(--color-text-muted); }
.fs-empty svg { width: 28px; height: 28px; opacity: .5; }
</style>
