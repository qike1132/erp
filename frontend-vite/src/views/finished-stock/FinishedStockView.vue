<template>
  <div class="sp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <div class="fs-search">
          <FontAwesomeIcon icon="search" class="fs-search-icon" aria-hidden="true" />
          <input v-model="filters.product" class="fs-search-input" placeholder="输入产品名称或 69 码" aria-label="搜索成品库存" />
        </div>
        <button
          class="fs-export-btn"
          :disabled="exporting"
          aria-label="导出"
          @click="handleExport"
        >
          <FontAwesomeIcon icon="file-excel" aria-hidden="true" />{{ exporting ? '导出中' : '导出 Excel' }}
        </button>
      </div>

      <!-- 客户快捷切换行（复用 /stock 同款共享组件） -->
      <CustomerChipBar
        :customers="customerList"
        :selected="filters.customer"
        :loading="isLoading"
        @select="filters.customer = $event"
      />

      <!-- 表格：SKU 大格（图片/产品名/69码跨行合并）+ 批次子行 -->
      <!-- page-card-body 自带 20px/24px 内边距（给有边距的内容页用）；本页表格需贴卡片边，
           故在此归零，观感与 /stock 的表格一致。 -->
      <div class="page-card-body fs-table-body">
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
          <!-- 产品图片（独立列，随 SKU 大格跨行合并；点击看原图） -->
          <template #column-body-_g_image="{ row }">
            <span v-if="(row as FinishedStockItem).image && !failedKeys.has(groupKeyOf(row as FinishedStockItem))" class="fs-thumb-box">
              <img
                loading="lazy"
                :src="thumbSrc(row as FinishedStockItem)"
                :alt="(row as FinishedStockItem).product_name"
                @error="onImgError(row as FinishedStockItem)"
                @click="previewImage(row as FinishedStockItem)"
              />
            </span>
            <span v-else class="fs-no-image"><FontAwesomeIcon icon="file-image" aria-hidden="true" /></span>
          </template>
          <!-- 产品名称（「全部客户」时补一行淡色客户名，否则不同客户同产品无法区分） -->
          <template #column-body-_g_product="{ row }">
            <span class="fs-name-cell">
              <strong class="fs-name">{{ (row as FinishedStockItem).product_name }}</strong>
              <small v-if="!filters.customer" class="fs-cust">{{ (row as FinishedStockItem).customer_name || '未指定客户' }}</small>
            </span>
          </template>
          <!-- 69码（field 被换成分组键，必须显式渲染原字段，否则会显示分组键本身） -->
          <template #column-body-_g_barcode="{ row }">
            <span>{{ (row as FinishedStockItem).barcode }}</span>
          </template>
          <!-- 批次号：空则留空（不再显示「(未分批次)」灰标） -->
          <template #column-body-batch_no="{ row }">
            <span v-if="(row as FinishedStockItem).batch_no" class="fs-badge-batch">{{ (row as FinishedStockItem).batch_no }}</span>
          </template>
          <!-- 库存 -->
          <template #column-body-batch_available="{ row }">
            <span v-if="(row as FinishedStockItem).batch_available <= LOW_STOCK_THRESHOLD" class="fs-qty-low">
              <FontAwesomeIcon icon="triangle-exclamation" aria-hidden="true" />{{ fmtNum((row as FinishedStockItem).batch_available) }}
            </span>
            <span v-else class="fs-qty-ok">{{ fmtNum((row as FinishedStockItem).batch_available) }}</span>
          </template>
          <!-- 定制 -->
          <template #column-body-is_custom="{ row }">
            <span v-if="(row as FinishedStockItem).is_custom" class="fs-badge-custom">{{ (row as FinishedStockItem).custom_country }}</span>
            <span v-else class="fs-dash">—</span>
          </template>
          <!-- 备注：行内可编辑（子组件管理编辑态/草稿；父级只处理 save） -->
          <template #column-body-remark="{ row }">
            <FinishedStockRemarkCell
              :remark="(row as FinishedStockRow).remark"
              :editing="editingKey === (row as FinishedStockRow).__rk"
              :saving="savingKey === (row as FinishedStockRow).__rk"
              @start="startEditRemark(row as FinishedStockRow)"
              @cancel="cancelEditRemark"
              @save="(text: string) => saveRemark(row as FinishedStockRow, text)"
            />
          </template>
          <template #empty>
            <div class="fs-empty"><FontAwesomeIcon icon="boxes-stacked" aria-hidden="true" /><span>暂无成品库存</span></div>
          </template>
        </UiDataTable>
      </div>

      <!-- 原图预览（复用共享组件；传原图 URL，不是列表缩略图） -->
      <ImagePreviewModal v-model:image="previewImg" />
    </div>
  </div></template>

<script setup lang="ts">
/**
 * FinishedStockView.vue — 成品库存（批次级）
 *
 * 布局（Excel 风格 SKU 行合并）：一行 = 一个批次；同一 SKU 的
 * 「图片 / 产品名称 / 69码」并成一个跨行大格，批次号 / 库存 / 定制 逐行渲染。
 * 机制照 views/report/components/ReportTable.vue（PrimeVue rowGroupMode='rowspan'）：
 * 要合并的列 field 换成分组键（_g_*），显示值仍从 body 槽取原字段。
 *
 * 分组键 = 客户 + 产品ID（后端按 (customer, product, batch) 聚合；同一批次号可能
 * 出现在不同客户下，故客户必须进键，否则不同客户的行会被错误并成一个大格）。
 * 用 product_id 而非 barcode：barcode 可空，无 69 码的产品会被并成一组。
 *
 * 数据源 GET /finished-stock/summary（与 /stock 同源：包装部入库 + 批次出货扣减）。
 */
import { ref, computed, watch } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import CustomerChipBar from '@/components/ui/CustomerChipBar.vue'
import ImagePreviewModal from '@/components/ui/ImagePreviewModal.vue'
import FinishedStockRemarkCell from './FinishedStockRemarkCell.vue'
import { formatNumber } from '@/utils/format'
import { resolveStaticUrl } from '@/api/request'
import { finishedStockApi } from '@/api'
import { useDebouncedRef } from '@/composables/useDebouncedRef'
import { useExport } from '@/composables/useExport'
import { showToast } from '@/composables/useToast'
import { batchSortKey, compareBatchNo } from './batchSort'
import type { FinishedStockItem } from '@/types'

/** 表格行：聚合行 + 分组键注入的 `__rk`（row-key 与编辑态标识都用它）。
 *  带上索引签名，与 `skuGroups` 产出的 `FinishedStockItem & Record<string, unknown>` 兼容。 */
type FinishedStockRow = FinishedStockItem & { __rk: string } & Record<string, unknown>

const filters = ref({ customer: '', product: '' })
/** 低库存高亮阈值（≤ 该值标红预警） */
const LOW_STOCK_THRESHOLD = 100
const debouncedProduct = useDebouncedRef(computed(() => filters.value.product), 300)
const page = ref(1)
const perPage = ref(20)
/** 排序态：批次号/库存 列可点（order: 1 升序 / -1 降序） */
const sort = ref<{ field: string; order: number } | null>(null)

const { data, isLoading } = useQuery({
  queryKey: ['finished-stock', () => filters.value.customer, debouncedProduct, () => page.value, () => perPage.value],
  queryFn: () => finishedStockApi.summary({
    customer: filters.value.customer || undefined,
    product: debouncedProduct.value || undefined,
    page: page.value,
    per_page: perPage.value,
  }),
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

// 过滤条件变化回到第 1 页：否则停在 page>1 会请求到不存在的页（空表），
// 且 UiDataTable 分页器与父级 page 会脱节（照 InventoryTab 的既有做法）。
watch(() => [filters.value.customer, debouncedProduct.value], () => {
  page.value = 1
})

const customerList = computed(() => (data.value?.all_customers ?? []) as string[])

/** 分组键：客户 + 产品ID（见文件头注释） */
function groupKeyOf(row: FinishedStockItem): string {
  return `${row.customer_name || ''}\u0000${row.product_id}`
}

/** 图片加载失败的分组（失败后退化成「无图」占位） */
const failedKeys = ref<Set<string>>(new Set())
function onImgError(row: FinishedStockItem): void { failedKeys.value.add(groupKeyOf(row)) }
/** 列表用缩略图（后端确定性派生 + 已签名），拿不到回退原图 */
function thumbSrc(row: FinishedStockItem): string {
  return resolveStaticUrl(row.image_thumb || row.image || '')
}
/** 原图预览：传**原图** URL（不是列表缩略图） */
const previewImg = ref<string | null>(null)
function previewImage(row: FinishedStockItem): void {
  if (row.image) previewImg.value = row.image
}

const { exporting, runExport } = useExport()
/** 导出当前筛选结果（客户 + 搜索词），照 InventoryTab 的 runExport 写法 */
function handleExport() {
  runExport(() => finishedStockApi.export({
    customer: filters.value.customer || undefined,
    product: filters.value.product || undefined,
  }))
}

// ===== 备注行内编辑 =====
/** 正在编辑的行键（`__rk`）；null 表示没有行处于编辑态 */
const editingKey = ref<string | null>(null)
/** 保存中的行键，用于按钮 loading */
const savingKey = ref<string | null>(null)

function startEditRemark(row: FinishedStockRow) {
  editingKey.value = row.__rk
}

function cancelEditRemark() {
  editingKey.value = null
}

async function saveRemark(row: FinishedStockRow, text: string) {
  if (savingKey.value) return
  savingKey.value = row.__rk
  try {
    await finishedStockApi.saveRemark({
      customer_name: row.customer_name || '',
      product_id: row.product_id,
      batch_no: row.batch_no || '',
      remark: text,
    })
    row.remark = text.trim()
    showToast('备注已保存', 'success')
    editingKey.value = null
  } catch (err: unknown) {
    const e = err as { response?: { data?: { detail?: string } } }
    showToast(e.response?.data?.detail || '备注保存失败', 'error')
  } finally {
    savingKey.value = null
  }
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
  { field: 'product_name', header: '产品名称', align: 'left', width: '27%' },
  { field: 'barcode', header: '69码', align: 'left', width: '11%' },
  { field: 'batch_no', header: '批次号', align: 'left', sortable: true, width: '18%' },
  { field: 'batch_available', header: '库存', align: 'center', sortable: true, width: '9%' },
  { field: 'is_custom', header: '定制', align: 'center', width: '7%' },
  { field: 'remark', header: '备注', align: 'left', width: 'auto' },
]
const uiColumns = computed(() => baseColumns.map((c) => ({ ...c, field: GROUP_FIELD_OF[c.field] ?? c.field })))

function fmtNum(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return ''
  return formatNumber(n)
}

/** 排序取值：批次号走专用键（见 batchSort），其余按数值。 */
function sortVal(row: Record<string, unknown>, field: string): number | string {
  if (field === 'batch_no') return batchSortKey(row.batch_no)
  const n = Number(row[field])
  return Number.isFinite(n) ? n : 0
}

/** 按分组键聚合，同 SKU 的批次行相邻 */
const skuGroups = computed(() => {
  const items = (data.value?.data ?? []) as FinishedStockItem[]
  const map = new Map<string, FinishedStockItem[]>()
  for (const r of items) {
    const k = groupKeyOf(r)
    const arr = map.get(k)
    if (arr) arr.push(r)
    else map.set(k, [r])
  }
  // SKU 组按产品名稳定排列、不参与列排序（否则点库存列会把组序打乱、破坏合并观感）
  const groups = [...map.entries()].sort((a, b) =>
    (a[1][0]?.product_name ?? '').localeCompare(b[1][0]?.product_name ?? '', 'zh'),
  )
  const out: (FinishedStockItem & Record<string, unknown>)[] = []
  for (const [key, rows] of groups) {
    // 组内按当前排序列排；默认按批次号升序（= 生产时间正序）
    const s = sort.value
    const ordered = s
      ? [...rows].sort((x, y) => {
          const a = sortVal(x as unknown as Record<string, unknown>, s.field)
          const b = sortVal(y as unknown as Record<string, unknown>, s.field)
          if (a < b) return -s.order
          if (a > b) return s.order
          return 0
        })
      : [...rows].sort((x, y) => compareBatchNo(x.batch_no, y.batch_no))
    for (const r of ordered) {
      out.push({
        ...r,
        __rk: `${key}-${r.batch_no || 'none'}`,        _g_image: key,
        _g_product: key,
        _g_barcode: key,
      })
    }
  }
  return out
})

const tableRows = computed(() => skuGroups.value)

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
.fs-search { position: relative; flex-shrink: 0; }
.fs-search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); width: 13px; height: 13px; color: var(--color-text-muted); pointer-events: none; }
.fs-search-input { width: 230px; padding: 7px 12px 7px 30px; border: 1.5px solid var(--color-border); border-radius: 9px; background: var(--color-surface-card); font-size: 12.5px; font-family: inherit; color: var(--color-text); outline: none; }
.fs-search-input::placeholder { color: var(--color-text-muted); }
.fs-search-input:focus { border-color: var(--color-primary-500); box-shadow: 0 0 0 3px rgba(91,141,239,0.15); }
.fs-export-btn {
  display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0;
  padding: 7px 14px; border: 1.5px solid var(--color-success-200); border-radius: 9px;
  background: var(--color-surface-card); font-family: inherit; font-size: 12.5px;
  font-weight: 600; color: var(--color-success-600); white-space: nowrap; cursor: pointer;
}
.fs-export-btn:hover { background: var(--color-success-50); border-color: var(--color-success-500); }
.fs-export-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.fs-card-main { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; }
/* 归零 page-card-body 的内边距，让表格贴卡片边（不产生左侧空隙）；观感对齐 /stock */
.fs-table-body { padding: 0; }
.fs-card-main :deep(.ui-data-table-wrapper) { flex: 1; min-height: 0; display: flex; flex-direction: column; border: 0; }
.fs-card-main :deep([data-pc-name='datatable']) { flex: 1; min-height: 0; overflow-y: auto; scrollbar-gutter: stable; }
.fs-card-main :deep(.ui-pagination) { flex-shrink: 0; }
.fs-card-main :deep(table) { table-layout: fixed; }
.fs-card-main :deep([data-pc-section='bodycell']) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-card-main :deep([data-pc-section='bodyrow']:last-child) { border-bottom: 0; }
.fs-card-main :deep([data-pc-section='sorticon']) { width: 10px; height: 10px; color: var(--color-slate-300); }
.fs-card-main :deep(th[aria-sort='ascending'] [data-pc-section='sorticon']),
.fs-card-main :deep(th[aria-sort='descending'] [data-pc-section='sorticon']) { color: var(--color-primary-600); }

.fs-name { font-weight: 500; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-name-cell { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.fs-cust { font-size: 11px; color: var(--color-text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fs-thumb-box {
  width: 44px; height: 44px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 8px; overflow: hidden; background: var(--color-surface);
}
.fs-thumb-box img { width: 100%; height: 100%; object-fit: contain; cursor: pointer; }
.fs-thumb-box img:hover { opacity: 0.85; }
.fs-no-image {
  width: 44px; height: 44px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 8px; background: var(--color-surface); color: var(--color-text-secondary);
  font-size: 18px; opacity: 0.5;
}
.fs-badge-batch { display: inline-flex; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--color-primary-50); color: var(--color-primary-700); white-space: nowrap; }
.fs-badge-custom { display: inline-flex; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; background: var(--color-purple-100); color: var(--color-purple-600); white-space: nowrap; }
.fs-dash { color: var(--color-slate-300); }
.fs-qty-ok { font-weight: 600; }
.fs-qty-low { color: var(--color-danger-600); font-weight: 700; display: inline-flex; align-items: center; gap: 4px; }
.fs-qty-low svg { width: 11px; height: 11px; }
.fs-empty { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 40px 20px; color: var(--color-text-muted); }
.fs-empty svg { width: 28px; height: 28px; opacity: .5; }
</style>
