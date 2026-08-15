<template>
  <div class="so-records-header">
    <span class="so-records-title"><FontAwesomeIcon icon="list-alt" aria-hidden="true" /> 出货记录列表</span>
    <UiButton variant="outline" size="sm" @click="showFilter = !showFilter">
      <FontAwesomeIcon icon="filter" style="margin-right: 4px"  aria-hidden="true" />筛选
    </UiButton>
  </div>

  <div v-if="showFilter" class="so-filter-panel">
    <div class="so-filter-row">
      <div class="so-filter-field">
        <label class="so-label"><FontAwesomeIcon icon="user" aria-hidden="true" /> 客户</label>
        <UiSelect v-model="filterCustomer" placeholder="全部" :options="customerOptions" style="width: 100%" />
      </div>
      <div class="so-filter-field">
        <label class="so-label"><FontAwesomeIcon icon="tag" aria-hidden="true" /> 订单类型</label>
        <UiSelect v-model="filterOrderType" placeholder="全部" :options="filterOrderTypeOptions" style="width: 100%" />
      </div>
      <div class="so-filter-field" style="grid-column: span 2">
        <label class="so-label"><FontAwesomeIcon icon="calendar-alt" aria-hidden="true" /> 日期范围</label>
        <UiDateRangePicker v-model="filterDateRange" style="width: 100%" />
      </div>
      <div class="so-filter-field so-filter-action">
        <UiButton variant="primary" size="sm" @click="fetchStockouts">
          <FontAwesomeIcon icon="search" style="margin-right: 4px"  aria-hidden="true" />查询
        </UiButton>
        <UiButton variant="outline" size="sm" @click="resetFilter">
          <FontAwesomeIcon icon="undo" style="margin-right: 4px"  aria-hidden="true" />重置
        </UiButton>
      </div>
    </div>
  </div>

  <div class="so-records-body">
    <template v-if="isFetching && stockoutRecords.length > 0">
      <div class="so-fetching-bar"><div class="so-fetching-progress" /></div>
    </template>
    <UiDataTable
      :data="stockoutRecords"
      :columns="stockoutColumns"
      :loading="isLoading && stockoutRecords.length === 0"
      :paginator="totalPages > 1"
      :rows="perPage"
      :total-records="totalPages * perPage"
      row-key="id"
      @page="onPageChange"
    >
      <template #empty>
        <div class="so-state-placeholder so-state-empty">
          <div class="so-empty-illustration"><FontAwesomeIcon icon="shipping-fast" aria-hidden="true" /></div>
          <p class="so-state-text">暂无出货记录</p>
        </div>
      </template>
      <template #column-body-stockout_date="{ row }">
        <span class="so-cell-muted">{{ row.stockout_date }}</span>
      </template>
      <template #column-body-customer="{ row }">
        <span class="so-cell-main">{{ row.customer || '-' }}</span>
      </template>
      <template #column-body-product="{ row }">
        <span class="so-cell-main">{{ row.product_name || row.product?.name || '-' }}</span>
        <span v-if="row.barcode || row.product?.barcode" class="so-cell-muted" style="display: block; font-size: 11px;">{{ row.barcode || row.product?.barcode }}</span>
      </template>
      <template #column-body-quantity="{ row }">
        <strong>{{ row.quantity }}</strong>
      </template>
      <template #column-body-actions="{ row }">
        <div class="so-action-group">
          <button class="so-btn-icon so-btn-info" @click="openDetail(row)" aria-label="详情">
            <FontAwesomeIcon icon="eye" aria-hidden="true" />
          </button>
        </div>
      </template>
    </UiDataTable>
  </div>

  <!-- 出货详情弹窗 -->
  <UiDialog v-model:open="detailOpen" title="出货详情" max-width-class="max-w-[500px]">
    <div v-if="detailData" class="so-detail-dialog">
      <div class="so-detail-grid">
        <div class="so-detail-cell">
          <span class="so-detail-label">出货时间</span>
          <span class="so-detail-value">{{ detailData.stockout_date || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">客户</span>
          <span class="so-detail-value">{{ detailData.customer || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">产品</span>
          <span class="so-detail-value">{{ detailData.product_name || detailData.product?.name || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">69码</span>
          <span class="so-detail-value so-detail-mono">{{ detailData.barcode || detailData.product?.barcode || '-' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">数量</span>
          <span class="so-detail-value"><strong>{{ detailData.quantity }}</strong></span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">抵扣备货</span>
          <span class="so-detail-value">{{ (detailData.deduct_quantity ?? 0) > 0 ? `抵扣: ${detailData.deduct_quantity}` : '否' }}</span>
        </div>
        <div class="so-detail-cell">
          <span class="so-detail-label">订单类型</span>
          <span class="so-detail-value">{{ detailData.order_type === 'custom' ? '定制' : '常规' }}</span>
        </div>
        <div v-if="detailData.country" class="so-detail-cell">
          <span class="so-detail-label">国家</span>
          <span class="so-detail-value">{{ detailData.country }}</span>
        </div>
      </div>
      <div v-if="detailData.note" class="so-detail-note">
        <span class="so-detail-label">备注</span>
        <span class="so-detail-value">{{ detailData.note }}</span>
      </div>
    </div>
    <template #footer>
      <UiButton variant="outline" @click="detailOpen = false">关闭</UiButton>
    </template>
  </UiDialog>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { stockApi } from '@/api'
import UiSelect from '@/components/ui/UiSelect.vue'
import UiButton from '@/components/ui/UiButton.vue'
import UiDataTable from '@/components/ui/UiDataTable.vue'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import UiDialog from '@/components/ui/UiDialog.vue'

interface StockoutRecord {
  id?: number
  stockout_date?: string
  product_id?: number
  product?: { id?: number; name?: string; image?: string; barcode?: string }
  product_name?: string
  product_image?: string
  barcode?: string
  customer?: string
  quantity?: number
  deduct_quantity?: number
  note?: string
  order_type?: string
  country?: string
}

defineProps<{
  customerOptions: { value: string; label: string }[]
}>()

// === 出货记录列表 ===
const showFilter = ref(false)
const filterCustomer = ref('')
const filterOrderType = ref('')
const filterStart = ref('')
const filterEnd = ref('')
const filterDateRange = computed<[string, string] | null>({
  get: () => (filterStart.value && filterEnd.value ? [filterStart.value, filterEnd.value] as [string, string] : null),
  set: (val: [string, string] | null) => {
    if (val && val.length === 2) {
      filterStart.value = val[0]
      filterEnd.value = val[1]
    } else {
      filterStart.value = ''
      filterEnd.value = ''
    }
    fetchStockouts()
  },
})
const currentPage = ref(1)
/** 每页条数（可由分页器选择） */
const perPage = ref(20)
const totalPages = ref(1)
const isLoading = ref(false)
const isFetching = ref(false)
const stockoutRecords = ref<StockoutRecord[]>([])

const filterOrderTypeOptions = [
  { value: 'regular', label: '常规订单' },
  { value: 'custom', label: '定制订单' },
]

/** UiDataTable 列定义 */
const stockoutColumns: TableColumn[] = [
  { field: 'stockout_date', header: '出货时间', align: 'center' },
  { field: 'customer', header: '客户', align: 'center' },
  { field: 'product', header: '产品', align: 'center' },
  { field: 'quantity', header: '数量', align: 'center' },
  { field: 'actions', header: '操作', align: 'center' },
]

/** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
function onPageChange(event: { page: number; rows: number }) {
  currentPage.value = event.page + 1
  perPage.value = event.rows
  fetchStockouts()
}

async function fetchStockouts() {
  const isInitial = stockoutRecords.value.length === 0
  if (isInitial) isLoading.value = true
  else isFetching.value = true
  try {
    const params: Record<string, unknown> = { page: currentPage.value, per_page: perPage.value }
    if (filterCustomer.value) params.customer = filterCustomer.value
    if (filterOrderType.value) params.order_type = filterOrderType.value
    if (filterStart.value) params.start_date = filterStart.value
    if (filterEnd.value) params.end_date = filterEnd.value
    const res = await stockApi.stockouts(params)
    const items = res.stockouts ?? res.items ?? []
    stockoutRecords.value = items as StockoutRecord[]
    const total = res.total ?? items.length
    totalPages.value = Math.ceil(total / perPage.value) || 1
  } catch {
    stockoutRecords.value = []
  } finally {
    isLoading.value = false
    isFetching.value = false
  }
}

function resetFilter() {
  filterCustomer.value = ''
  filterOrderType.value = ''
  filterStart.value = ''
  filterEnd.value = ''
  currentPage.value = 1
  fetchStockouts()
}

// === 详情弹窗 ===
const detailOpen = ref(false)
const detailData = ref<StockoutRecord | null>(null)

function openDetail(item: StockoutRecord) {
  detailData.value = item
  detailOpen.value = true
}

// === 暴露给父组件的方法 ===
function loadIfEmpty() {
  if (stockoutRecords.value.length === 0) {
    fetchStockouts()
  }
}

defineExpose({ loadIfEmpty, refresh: fetchStockouts })
</script>

<style scoped>
/* ===== Records TAB ===== */
.so-records-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  flex-shrink: 0;
}
.so-records-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
}
.so-records-title i {
  color: var(--color-danger-500);
}
.so-records-body {
  flex: 1;
  overflow-y: auto;
  padding: 0;
  min-height: 0;
}

/* ===== Filter Panel ===== */
.so-filter-panel {
  padding: 12px 20px;
  border-bottom: 1px solid var(--color-border, #cbd5e1);
  background: var(--color-surface, #f8fafc);
}
.so-filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.so-filter-field {
  min-width: 140px;
  flex: 1;
}
.so-filter-field .so-label {
  font-size: 12px;
  margin-bottom: 4px;
}
.so-filter-action {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
  min-width: auto;
}
.so-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
  color: var(--color-text-secondary);
}

/* ===== Table ===== */
.so-cell-main {
  font-weight: 500;
  color: var(--color-text);
}
.so-cell-muted {
  color: var(--color-text-muted);
  font-size: 12px;
}

/* ===== Action Buttons (records) ===== */
.so-action-group {
  display: flex;
  gap: 4px;
  justify-content: center;
}
.so-btn-icon {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s ease, transform 0.2s ease;
}
.so-btn-info {
  background: var(--color-primary-50);
  color: var(--color-primary-600);
}
.so-btn-info:hover {
  background: var(--color-primary-100);
  transform: translateY(-1px);
}

/* ===== Loading & Empty States ===== */
.so-state-placeholder {
  text-align: center;
  padding: 60px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.so-state-empty {
  color: var(--color-text-muted);
}
.so-state-text {
  font-size: 14px;
  color: var(--color-text-secondary);
  margin: 0;
}
.so-empty-illustration {
  font-size: 36px;
  opacity: 0.4;
  color: var(--color-text-muted);
}

/* ===== Fetching Progress Bar ===== */
.so-fetching-bar {
  height: 3px;
  background: var(--color-border-light);
  overflow: hidden;
}
.so-fetching-progress {
  height: 100%;
  width: 30%;
  background: var(--color-primary-500);
  animation: so-progress-slide 1.2s ease-in-out infinite;
}
@keyframes so-progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* ===== Detail Dialog ===== */
.so-detail-dialog {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.so-detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
  overflow: hidden;
}
.so-detail-cell {
  padding: 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  border-bottom: 1px solid var(--color-border-light, #e2e8f0);
}
.so-detail-cell:nth-child(odd) {
  border-right: 1px solid var(--color-border-light, #e2e8f0);
}
.so-detail-cell:nth-last-child(-n+2) {
  border-bottom: none;
}
.so-detail-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.so-detail-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text);
}
.so-detail-mono {
  font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  letter-spacing: 0.02em;
}
.so-detail-note {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 16px;
  border: 1px solid var(--color-border-light, #e2e8f0);
  border-radius: 12px;
}

/* ===== Responsive ===== */
@media (max-width: 767.98px) {
  .so-filter-row {
    flex-direction: column;
  }
  .so-filter-field {
    min-width: 100%;
  }
  .so-detail-grid {
    grid-template-columns: 1fr;
  }
  .so-detail-cell:nth-child(odd) {
    border-right: none;
  }
}
</style>
