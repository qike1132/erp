import { ref, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'

/** 皮套入库/出库记录项 */
export interface CaseStockRecord {
  id: number
  stockin_date?: string
  stockout_date?: string
  customer?: string
  case_name?: string
  case_barcode?: string
  quantity: number
  note?: string
}

/** 皮套入库/出库列表响应 */
export interface CaseStockListResponse {
  stockins?: CaseStockRecord[]
  stockouts?: CaseStockRecord[]
  items?: CaseStockRecord[]
  pages?: number
  total_pages?: number
}

/**
 * 皮套入库/出库「记录列表」查询状态（筛选 + 分页 + useQuery）。
 * 入库与出库结构一致，通过 kind 复用同一套逻辑。
 * @param kind 'stockin' 入库 | 'stockout' 出库
 */
export function useCaseStockRecords(kind: 'stockin' | 'stockout') {
  const isStockin = kind === 'stockin'

  // === 筛选与分页状态 ===
  const showFilter = ref(false)
  const fCustomer = ref('')
  const fStart = ref('')
  const fEnd = ref('')
  const page = ref(1)
  const perPage = ref(10)
  const totalPages = ref(1)

  const {
    data,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: [isStockin ? 'case-stockins' : 'case-stockouts', page, fCustomer, fStart, fEnd, perPage],
    queryFn: async () => {
      const params: Record<string, string | number> = { page: page.value, per_page: perPage.value }
      if (fCustomer.value) params.customer = fCustomer.value
      if (fStart.value) params.start_date = fStart.value
      if (fEnd.value) params.end_date = fEnd.value
      const res = (await (isStockin ? caseApi.stockins(params) : caseApi.stockouts(params))) as CaseStockListResponse
      totalPages.value = res.pages ?? res.total_pages ?? 1
      return res
    },
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
  const list = computed(() =>
    isStockin
      ? data.value?.stockins ?? data.value?.items ?? []
      : data.value?.stockouts ?? data.value?.items ?? [],
  )

  /** UiDataTable 列定义 */
  const columns: TableColumn[] = [
    { field: isStockin ? 'stockin_date' : 'stockout_date', header: isStockin ? '入库日期' : '出库日期', align: 'center' },
    { field: 'customer', header: '客户', align: 'center' },
    { field: 'case_name', header: '产品名称', align: 'left' },
    { field: 'case_barcode', header: '69码', align: 'center' },
    { field: 'quantity', header: '数量', align: 'right' },
    { field: 'note', header: '备注', align: 'center' },
    { field: 'actions', header: '操作', align: 'center' },
  ]

  /** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
  function onPageChange(event: { page: number; rows: number }) {
    page.value = event.page + 1
    perPage.value = event.rows
  }

  /** 筛选查询：重置回第 1 页后重新拉取 */
  function search() {
    page.value = 1
    refetch()
  }

  return {
    showFilter,
    fCustomer,
    fStart,
    fEnd,
    page,
    perPage,
    totalPages,
    data,
    isLoading,
    isFetching,
    refetch,
    list,
    columns,
    onPageChange,
    search,
  }
}
