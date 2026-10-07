<template>
  <div class="sk-inventory">
    <InventoryToolbar
      :search="filters.product"
      :orders="totalOrderQty"
      :stockin="totalStockinQty"
      :has-data="inventory.length > 0"
      @update:search="filters.product = $event"
      @search="refetch()"
      @export="handleExport"
    />

    <InventoryCustomerBar
      :customers="allCustomers"
      :selected="filters.customer"
      :loading="isFetching"
      @select="selectCustomer"
    />

    <div class="sk-card-main">
      <div v-if="isFetching" class="sk-fetching-bar"><div class="sk-fetching-progress" /></div>
      <UiDataTable
        :data="inventory"
        :columns="inventoryColumns"
        :loading="isLoading && inventory.length === 0"
        :paginator="totalItems > perPage"
        :rows="perPage"
        :total-records="totalItems"
        row-key="_rowKey"
        @sort="onSort"
        @page="onPageChange"
      >
        <template #empty>
          <div class="sk-empty">
            <FontAwesomeIcon icon="warehouse" aria-hidden="true" />
            <span>暂无库存数据</span>
          </div>
        </template>
        <template #column-body-product_name="{ row }">
          <span class="sk-product-cell">
            <FontAwesomeIcon icon="cube" aria-hidden="true" />
            <strong>{{ (row as InventoryItem).product_name }}</strong>
          </span>
        </template>
        <template #column-body-order_quantity="{ row }">
          <span class="sk-num">{{ fmtQty((row as InventoryItem).order_quantity) }}</span>
        </template>
        <template #column-body-stockin_quantity="{ row }">
          <span class="sk-num">{{ fmtQty((row as InventoryItem).stockin_quantity) }}</span>
        </template>
        <template #column-body-total_stock="{ row }">
          <span class="sk-num sk-num-strong">{{ fmtQty((row as InventoryItem).total_stock) }}</span>
        </template>
      </UiDataTable>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * InventoryTab.vue — 库存明细（方案 B v5）
 *
 * 布局：一行工具条（标题·搜索·三格汇总·导出）→ 客户筛选行 → 5 列表格。
 * 列口径（与后端 CTE 一一对应）：
 *   订单数量 = 未发完的订单余量 · 备货数量 = 已入库未消耗 · 总订单 = 备货 + 订单余量
 * 三个数量列居中显示；有值走千分位，0 与空值留白（不做「—」之类的占位符）。
 * 排序为当前页客户端排序（服务端分页不变；要跨页排序需后端加 order_by 参数）。
 */
import { reactive, computed, watch, ref } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { stockApi } from '@/api'
import type { InventoryItem } from '@/types'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { useDebouncedRef } from '@/composables/useDebouncedRef'
import { useExport } from '@/composables/useExport'
import { formatNumber } from '@/utils/format'
import InventoryToolbar from './components/InventoryToolbar.vue'
import InventoryCustomerBar from './components/InventoryCustomerBar.vue'

const filters = reactive({ customer: '', product: '' })
const debouncedProduct = useDebouncedRef(computed(() => filters.product), 300)
const page = ref(1)
const perPage = ref(15)
const sort = ref<{ field: string; order: number } | null>(null)

const {
  data: invData,
  isLoading,
  isFetching,
  refetch,
} = useQuery({
  queryKey: ['inventory', () => filters.customer, debouncedProduct, () => page.value, () => perPage.value],
  queryFn: () =>
    stockApi.inventory({
      customer: filters.customer || undefined,
      product: debouncedProduct.value || undefined,
      page: page.value,
      per_page: perPage.value,
    }),
  staleTime: 30_000,
  gcTime: 60_000,
  placeholderData: keepPreviousData,
})

/** 数量展示：有值走千分位，0 与空值留白（后端把 0 序列化成空串，不做占位符） */
function fmtQty(v: unknown): string {
  const n = Number(v)
  return Number.isFinite(n) && n !== 0 ? formatNumber(n) : ''
}

/** 排序取值：非数值列当作 0，避免 NaN 让排序整体失效 */
function sortValue(row: InventoryItem, field: string): number {
  const n = Number((row as unknown as Record<string, unknown>)[field])
  return Number.isFinite(n) ? n : 0
}

const inventory = computed(() => {
  const rows = (invData.value?.data ?? []).map((item) => ({
    ...item,
    _rowKey: `${item.customer}-${item.product_name}`,
  }))
  const s = sort.value
  if (!s) return rows
  return [...rows].sort((a, b) => (sortValue(a, s.field) - sortValue(b, s.field)) * s.order)
})

const inventoryColumns: TableColumn[] = [
  // 按比例分配而非定宽：定宽数值列（如各 140px）会把全部余量留给产品名列，
  // 宽屏上产品名列能独吞上千像素，三个数值列被推到最右、中间留一大片空档。
  // 百分比配合 table-layout: fixed（见样式）才是硬约束，五列按 15/35/16.67×3 铺满。
  { field: 'customer', header: '客户', align: 'left', width: '15%' },
  { field: 'product_name', header: '产品名称', align: 'left', width: '35%' },
  { field: 'order_quantity', header: '订单数量', align: 'center', sortable: true, width: '16.67%' },
  { field: 'stockin_quantity', header: '备货数量', align: 'center', sortable: true, width: '16.67%' },
  { field: 'total_stock', header: '总订单', align: 'center', sortable: true, width: '16.67%' },
]

const allCustomers = computed(() => (invData.value?.all_customers ?? []) as string[])
const totalItems = computed(() => invData.value?.total_items ?? 0)
const totalOrderQty = computed(() => invData.value?.total_order_quantity ?? 0)
const totalStockinQty = computed(() => invData.value?.total_stockin_quantity ?? 0)

function selectCustomer(c: string) {
  filters.customer = c
}

function onPageChange(event: { page: number; rows: number }) {
  page.value = event.page + 1
  perPage.value = event.rows
}

/** PrimeVue 排序事件：order 为 1 升序 / -1 降序 / 0 取消 */
function onSort(event: { field: string; order: number }) {
  sort.value = event.order ? { field: event.field, order: event.order } : null
}

const { runExport } = useExport({ start: false, success: false })

function handleExport() {
  runExport(() => stockApi.exportInventory({ customer: filters.customer, product: filters.product }))
}

watch(() => [filters.customer, debouncedProduct.value], () => {
  page.value = 1
})
</script>

<style scoped>
.sk-inventory {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
.sk-card-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow-y: auto;
}
/* 百分比列宽必须配 fixed 布局才是硬约束：auto 布局把百分比当建议值，
   余量仍会全塞给内容最长的那列（产品名列独吞、数值列被推最右）。 */
.sk-card-main :deep(table) { table-layout: fixed; }

/* fixed 布局下单元格内容不会自动收窄，统一单行 + 省略号，避免长产品名/长客户名撑破列宽 */
.sk-card-main :deep([data-pc-section='bodycell']) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sk-product-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.sk-product-cell svg {
  width: 13px;
  height: 13px;
  color: var(--color-text-muted);
  flex-shrink: 0;
}
.sk-product-cell strong {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sk-num { font-weight: 500; }
.sk-num-strong { font-weight: 700; }

/* UiDataTable 的容器自带边框（共享组件，多个视图共用）。
   本页的稿是表格与卡片齐平、没有内层盒子，故在此抵消边框，不动共享组件。 */
.sk-card-main :deep(.ui-data-table-wrapper) {
  border: 0;
}

/* 行分隔线与 hover 由全局 PT 的 bodyRow 段提供（2026-09-29 修正段名后全站生效）。
   这里只补 PT 表达不了的一条：末行去线 —— 紧邻的分页器自带 border-top，
   两条 1px 会叠成一道粗线。 */
.sk-card-main :deep([data-pc-section='bodyrow']:last-child) {
  border-bottom: 0;
}

/* PrimeVue 表头排序图标：生产是 unstyled + PT 模式，图标不带任何 class
   （`p-datatable-sort-icon` 只在未装插件时的默认模式下出现，生产里命不中），
   故用两模式都稳定输出的 data-pc-section 钩子。默认 14px 裸 svg 在表头里又大又飘。 */
.sk-card-main :deep([data-pc-section='columnheadercontent']) {
  display: inline-flex;
  align-items: center;
}
.sk-card-main :deep([data-pc-section='sort']) {
  display: inline-flex;
  align-items: center;
  margin-left: 4px;
}
.sk-card-main :deep([data-pc-section='sorticon']) {
  width: 10px;
  height: 10px;
  color: #cbd5e1;
  transition: color 0.15s ease;
}
.sk-card-main :deep(th[data-p-sortable-column='true']) { cursor: pointer; }
.sk-card-main :deep(th[data-p-sortable-column='true']:hover [data-pc-section='sorticon']) {
  color: var(--color-primary-500);
}
/* 已参与排序的列：图标点亮 + 列名加重，一眼看出当前按哪列排 */
.sk-card-main :deep(th[aria-sort='ascending'] [data-pc-section='sorticon']),
.sk-card-main :deep(th[aria-sort='descending'] [data-pc-section='sorticon']) {
  color: var(--color-primary-600);
}
.sk-card-main :deep(th[aria-sort='ascending'] [data-pc-section='columntitle']),
.sk-card-main :deep(th[aria-sort='descending'] [data-pc-section='columntitle']) {
  color: var(--color-primary-700);
}
.sk-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 40px 20px;
  color: var(--color-text-muted);
}
.sk-empty svg {
  width: 28px;
  height: 28px;
  opacity: 0.5;
}
.sk-empty span { font-size: 14px; }

.sk-fetching-bar {
  height: 2px;
  background: var(--color-primary-100, #e0f2fe);
  overflow: hidden;
  border-radius: 1px;
}
.sk-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500, #3b82f6);
  border-radius: 1px;
  animation: sk-progress-slide 1s ease-in-out infinite;
}
@keyframes sk-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}
</style>
