<template>
  <div class="rp-container">
    <div class="page-card page-card-main">
      <div class="page-card-header">
        <ReportTabGroup :model-value="activeTab" @change="onTabChange" />
      </div>

      <ReportFilterBar
        v-model:filters="filters"
        :customer-options="customerOptions"
        :searched="searched"
        @search="doSearch"
        @reset="doReset"
        @export="exportReport"
      />

      <ReportTable
        :logs="logs"
        :columns="reportColumns"
        :is-loading="isLoading"
        :is-fetching="isFetching"
        :searched="searched"
        :per-page="perPage"
        :pagination="pagination"
        :current-cfg="currentCfg"
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

const filters = reactive({ customer: '', product: '', startDate: '', endDate: '' })

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
    if (filters.startDate) params.start_date = filters.startDate
    if (filters.endDate) params.end_date = filters.endDate
    return await reportApi[currentTabEndpoint()](params)
  },
  enabled: searched,
  staleTime: 30_000,
  placeholderData: keepPreviousData,
})

const logs = computed(() => reportData.value?.logs ?? [])
const pagination = computed(() => reportData.value?.pagination)

function doSearch() {
  searched.value = true
  page.value = 1
}

function doReset() {
  Object.assign(filters, { customer: '', product: '', startDate: '', endDate: '' })
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
  if (filters.startDate) params.set('start_date', filters.startDate)
  if (filters.endDate) params.set('end_date', filters.endDate)
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
</style>
