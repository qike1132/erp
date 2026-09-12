import { ref, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseStockRecord, CaseStockListParams } from '@/api/case'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'

export type { CaseStockRecord }

export interface StockRecordFilters {
  customer: string
  start: string
  end: string
}

/**
 * 皮套入库/出库记录列表（vue-query：筛选 + 服务端分页）。
 * 入库与出库结构一致，通过 kind 复用。
 */
export function useCaseStockRecords(kind: 'stockin' | 'stockout') {
  const isStockin = kind === 'stockin'
  const queryKey = isStockin ? 'case-stockins' : 'case-stockouts'

  // === 筛选与分页状态 ===
  const showFilter = ref(false)
  const filters = ref<StockRecordFilters>({ customer: '', start: '', end: '' })
  const page = ref(1)
  const perPage = ref(20)

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: [queryKey, page, filters, perPage],
    queryFn: async () => {
      const params: CaseStockListParams = { page: page.value, per_page: perPage.value }
      if (filters.value.customer) params.customer = filters.value.customer
      if (filters.value.start) params.start_date = filters.value.start
      if (filters.value.end) params.end_date = filters.value.end
      return isStockin ? caseApi.stockins(params) : caseApi.stockouts(params)
    },
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const list = computed<CaseStockRecord[]>(() =>
    isStockin ? data.value?.stockins ?? [] : data.value?.stockouts ?? [],
  )
  const total = computed(() => data.value?.total ?? 0)
  const totalPages = computed(() => data.value?.pages ?? 0)

  const columns: TableColumn[] = [
    { field: isStockin ? 'stockin_no' : 'stockout_no', header: isStockin ? '入库单号' : '出库单号', align: 'center' },
    { field: isStockin ? 'stockin_date' : 'stockout_date', header: isStockin ? '入库日期' : '出库日期', align: 'center' },
    { field: 'customer', header: '客户', align: 'center' },
    { field: 'case_name', header: '产品名称', align: 'left' },
    { field: 'case_barcode', header: '69码', align: 'center' },
    { field: 'quantity', header: '数量', align: 'right' },
    { field: 'note', header: '备注', align: 'center' },
    { field: 'actions', header: '操作', align: 'center' },
  ]

  function onPageChange(event: { page: number; rows: number }) {
    page.value = event.page + 1
    perPage.value = event.rows
  }

  /** 筛选查询：重置回第 1 页 */
  function search() {
    page.value = 1
    refetch()
  }

  /** 重置筛选条件 */
  function resetFilters() {
    filters.value = { customer: '', start: '', end: '' }
    page.value = 1
    refetch()
  }

  return {
    showFilter,
    filters,
    page,
    perPage,
    total,
    totalPages,
    isLoading,
    isFetching,
    refetch,
    list,
    columns,
    onPageChange,
    search,
    resetFilters,
  }
}
