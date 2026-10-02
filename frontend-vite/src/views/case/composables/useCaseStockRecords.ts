import { ref, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseMovement, CaseMovementListParams } from '@/api/case'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { directionOf, type StockMode } from './useCaseStockWorkbench'

export type { CaseMovement }

export interface StockRecordFilters {
  customer: string
  start: string
  end: string
}

/**
 * 皮套出入库流水列表（方向固定 = 所属工作台模式；vue-query：筛选 + 服务端分页）。
 */
export function useCaseStockRecords(mode: StockMode) {
  const direction = directionOf(mode)
  const queryKey = direction === 'in' ? 'case-movements-in' : 'case-movements-out'
  const isStockin = direction === 'in'

  const showFilter = ref(false)
  const filters = ref<StockRecordFilters>({ customer: '', start: '', end: '' })
  const page = ref(1)
  const perPage = ref(20)

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: [queryKey, page, filters, perPage],
    queryFn: async () => {
      const params: CaseMovementListParams = { page: page.value, per_page: perPage.value, direction }
      if (filters.value.customer) params.customer = filters.value.customer
      if (filters.value.start) params.start_date = filters.value.start
      if (filters.value.end) params.end_date = filters.value.end
      return caseApi.movements(params)
    },
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const list = computed<CaseMovement[]>(() => data.value?.movements ?? [])
  const total = computed(() => data.value?.total ?? 0)
  const totalPages = computed(() => data.value?.pages ?? 0)

  const columns: TableColumn[] = [
    { field: 'movement_no', header: isStockin ? '入库单号' : '出库单号', align: 'center' },
    { field: 'movement_date', header: '日期', align: 'center' },
    { field: 'customer', header: '客户', align: 'center' },
    { field: 'case_name', header: '皮套', align: 'left' },
    { field: 'case_barcode', header: '69码', align: 'center' },
    { field: 'quantity', header: '数量', align: 'right' },
    { field: 'note', header: '备注', align: 'center' },
    { field: 'actions', header: '操作', align: 'center' },
  ]

  function onPageChange(event: { page: number; rows: number }) {
    page.value = event.page + 1
    perPage.value = event.rows
  }

  function search() {
    page.value = 1
    refetch()
  }

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
