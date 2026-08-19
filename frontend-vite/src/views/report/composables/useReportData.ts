import { computed, ref, reactive } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { reportApi } from '@/api'
import { useCatalogStore } from '@/stores/catalog'

/** 报表标签页类型 */
export type TabType = 'order' | 'stockin' | 'stockout' | 'deduction'

/** 单个标签页的列配置 */
interface TabConfig {
  label: string
  endpoint: string
  dateKey: string
  countKey: string
  dateLabel: string
  countLabel: string
  noteKey: string
}

/** 各标签页的列映射配置 */
const TAB_CONFIG: Record<TabType, TabConfig> = {
  order: {
    label: '订单流水',
    endpoint: '/reports/order-logs',
    dateKey: 'order_date',
    countKey: 'order_count',
    dateLabel: '下单时间',
    countLabel: '数量',
    noteKey: 'note',
  },
  stockin: {
    label: '备货流水',
    endpoint: '/reports/stockin-logs',
    dateKey: 'stockin_date',
    countKey: 'stockin_count',
    dateLabel: '备货时间',
    countLabel: '备货数量',
    noteKey: 'note',
  },
  stockout: {
    label: '出货流水',
    endpoint: '/reports/stockout-logs',
    dateKey: 'stockout_date',
    countKey: 'stockout_count',
    dateLabel: '出货时间',
    countLabel: '出货数量',
    noteKey: 'note',
  },
  deduction: {
    label: '备货抵扣流水',
    endpoint: '/reports/deduction-logs',
    dateKey: 'deduction_time',
    countKey: 'deduction_count',
    dateLabel: '抵扣时间',
    countLabel: '抵扣数量',
    noteKey: 'order_note',
  },
}

export const REPORT_TABS: { value: TabType; label: string }[] = [
  { value: 'order', label: '订单流水' },
  { value: 'stockin', label: '备货流水' },
  { value: 'stockout', label: '出货流水' },
  { value: 'deduction', label: '备货抵扣流水' },
]

export function useReportData() {
  const activeTab = ref<TabType>('order')
  const page = ref(1)
  const perPage = ref(15)
  const searched = ref(true)
  const filters = reactive({ customer: '', product: '', startDate: '', endDate: '' })

  const currentCfg = computed(() => TAB_CONFIG[activeTab.value])

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

  function currentTabEndpoint(): 'orderLogs' | 'stockinLogs' | 'stockoutLogs' | 'deductionLogs' {
    const map: Record<TabType, 'orderLogs' | 'stockinLogs' | 'stockoutLogs' | 'deductionLogs'> = {
      order: 'orderLogs',
      stockin: 'stockinLogs',
      stockout: 'stockoutLogs',
      deduction: 'deductionLogs',
    }
    return map[activeTab.value]
  }

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

  function handleTabChange() {
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

  return {
    activeTab,
    page,
    perPage,
    searched,
    filters,
    currentCfg,
    customerOptions,
    reportData,
    isLoading,
    isFetching,
    logs,
    pagination,
    doSearch,
    doReset,
    handleTabChange,
    onPageChange,
    exportReport,
  }
}