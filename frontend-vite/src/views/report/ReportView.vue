<template>
  <div class="rp-container">
    <div class="page-card page-card-main">
      <!-- 单行工具条：标题 · 维度 tab · 筛选与动作（原先是 tab 独占一个卡片头、筛选独占一行） -->
      <div class="rp-toolbar">
        <div class="rp-title">
          <FontAwesomeIcon icon="chart-line" aria-hidden="true" />
          <h1>报表流水</h1>
        </div>

        <ReportTabGroup :model-value="activeTab" @change="onTabChange" />

        <ReportFilterBar
          v-model:filters="filters"
          :customer-options="customerOptions"
          :searched="searched"
          @search="doSearch"
          @reset="doReset"
          @export="exportReport"
        />
      </div>

      <ReportTable
        :logs="sortedLogs"
        :columns="reportColumns"
        :is-loading="isLoading"
        :is-fetching="isFetching"
        :searched="searched"
        :per-page="perPage"
        :pagination="pagination"
        :current-cfg="currentCfg"
        @sort="onSort"
        @page="onPageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { reportApi } from '@/api'
import { useCatalogStore } from '@/stores/catalog'
import ReportTabGroup from './components/ReportTabGroup.vue'
import ReportFilterBar from './components/ReportFilterBar.vue'
import ReportTable from './components/ReportTable.vue'
import { useReportConfig, type TabType } from './composables/useReportConfig'

const activeTab = ref<TabType>('order')
const page = ref(1)
const perPage = ref(15)
const searched = ref(true)
/** 当前排序（服务端分页不变，这是当前页内的客户端排序） */
const sort = ref<{ field: string; order: number } | null>(null)

const filters = reactive({ customer: '', product: '' })

const { currentCfg, currentTabEndpoint, reportColumns } = useReportConfig(activeTab)

const catalogStore = useCatalogStore()
catalogStore.ensureActiveCustomerNames().catch(() => {})

const customerOptions = computed(() =>
  catalogStore.activeCustomerNames.map((c) => ({ value: c.name, label: c.name })),
)

const { data: reportData, isLoading, isFetching } = useQuery({
  queryKey: ['report-data', activeTab, page, perPage, filters],
  queryFn: async () => {
    const params: Record<string, string | number> = { page: page.value, per_page: perPage.value }
    if (filters.customer) params.customer = filters.customer
    if (filters.product) params.product = filters.product
    return await reportApi[currentTabEndpoint()](params)
  },
  enabled: searched,
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

const logs = computed(() => reportData.value?.logs ?? [])
const pagination = computed(() => reportData.value?.pagination)

/** 排序取值：非数值列按 0，避免 NaN 让整列排序失效 */
function sortValue(row: Record<string, unknown>, field: string): number {
  const n = Number(row[field])
  return Number.isFinite(n) ? n : 0
}

const sortedLogs = computed(() => {
  const s = sort.value
  if (!s) return logs.value
  return [...logs.value].sort((a, b) => (sortValue(a, s.field) - sortValue(b, s.field)) * s.order)
})

/** PrimeVue 排序事件：order 为 1 升序 / -1 降序 / 0 取消 */
function onSort(event: { field: string; order: number }) {
  sort.value = event.order ? { field: event.field, order: event.order } : null
}

function doSearch() {
  searched.value = true
  page.value = 1
}

function doReset() {
  Object.assign(filters, { customer: '', product: '' })
  page.value = 1
}

function onTabChange(value: TabType) {
  activeTab.value = value
  page.value = 1
}

function onPageChange(event: { page: number; rows: number }) {
  page.value = event.page + 1
  perPage.value = event.rows
}

function exportReport() {
  const params = new URLSearchParams()
  params.set('report_type', activeTab.value)
  if (filters.customer) params.set('customer', filters.customer)
  if (filters.product) params.set('product', filters.product)
  window.open(`/api/v1/reports/export?${params.toString()}`, '_blank')
}
</script>

<style scoped>
.rp-container {
  padding: 0;
  margin: 0 auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}
.rp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 10px 20px;
  min-height: 62px;
  border-bottom: 1px solid var(--color-border-light, #f0f2f5);
  flex-shrink: 0;
}
.rp-title {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-shrink: 0;
}
.rp-title svg {
  width: 18px;
  height: 18px;
  color: var(--color-primary-600);
}
.rp-title h1 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
}
</style>
