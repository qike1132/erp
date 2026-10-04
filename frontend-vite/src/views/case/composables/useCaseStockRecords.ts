import { ref, computed, watch } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseMovement, CaseMovementListParams } from '@/api/case'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'

export type { CaseMovement }

export interface StockRecordFilters {
  direction: '' | 'in' | 'out'
  start: string
  end: string
}

/**
 * 皮套出入库流水列表（入库出库混排，带方向列与方向筛选）。
 */
export function useCaseStockRecords() {
  const queryKey = 'case-movements'

  const showFilter = ref(false)
  const filters = ref<StockRecordFilters>({ direction: '', start: '', end: '' })
  const page = ref(1)
  const perPage = ref(20)

  // 筛选即改即查：queryKey 含 filters（改动会自动重新请求），这里只把页码归 1，
  // 避免在第 2 页改筛选后仍停在旧页而看起来「没生效」。
  watch(filters, () => {
    page.value = 1
  }, { deep: true })

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: [queryKey, page, filters, perPage],
    queryFn: async () => {
      const params: CaseMovementListParams = { page: page.value, per_page: perPage.value }
      if (filters.value.direction) params.direction = filters.value.direction
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
    { field: 'movement_no', header: '单号', align: 'center' },
    { field: 'direction', header: '方向', align: 'center' },
    { field: 'movement_date', header: '日期', align: 'center' },
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

  function resetFilters() {
    filters.value = { direction: '', start: '', end: '' }
    page.value = 1
    refetch()
  }

  return {
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
    resetFilters,
  }
}
