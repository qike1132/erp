import { ref, computed } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { get } from '@/api/request'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'
import { useDebouncedSearch } from '@/composables/useDebouncedSearch'

/** 库存汇总中单个产品的库存信息 */
export interface InventorySummaryItem {
  id: number
  name: string
  barcode?: string
  initial_stock: number
  total_in: number
  total_out: number
  current_stock: number
}

/** 库存汇总响应 */
export interface InventorySummaryResponse {
  inventory: InventorySummaryItem[]
  pages: number
  stats: {
    total_stock: number
    total_in: number
    total_out: number
  }
}

/** 库存流水中单条记录 */
export interface InventoryLogItem {
  id: number
  change_type: string
  change_quantity: number
  customer?: string
  related_id?: string
  change_date: string
  note?: string
}

/** 库存流水响应 */
export interface InventoryLogResponse {
  logs: InventoryLogItem[]
  pagination: {
    pages: number
  }
}

/** 操作类型选项 */
export const LOG_TYPE_OPTIONS = [
  { value: '入库', label: '入库' },
  { value: '出库', label: '出库' },
  { value: '入库调整', label: '入库调整' },
  { value: '出库调整', label: '出库调整' },
  { value: '删除入库', label: '删除入库' },
  { value: '删除出库', label: '删除出库' },
]

/** UiDataTable 列定义 */
export const INVENTORY_COLUMNS: TableColumn[] = [
  { field: 'name', header: '产品名称', align: 'left' },
  { field: 'barcode', header: '69码', align: 'center' },
  { field: 'initial_stock', header: '初始库存', align: 'right' },
  { field: 'total_in', header: '累计入库', align: 'right' },
  { field: 'total_out', header: '累计出库', align: 'right' },
  { field: 'current_stock', header: '当前库存', align: 'right' },
  { field: 'actions', header: '操作', align: 'center' },
]

export const LOG_COLUMNS: TableColumn[] = [
  { field: 'change_type', header: '操作类型', align: 'center' },
  { field: 'change_quantity', header: '变化数量', align: 'right' },
  { field: 'customer', header: '客户', align: 'center' },
  { field: 'related_id', header: '关联单号', align: 'center' },
  { field: 'change_date', header: '时间', align: 'center' },
  { field: 'note', header: '备注', align: 'center' },
]

/** 皮套库存查询标签页业务逻辑 */
export function useCaseInventory() {
  // ===== 库存汇总 =====
  const invSearch = ref('')
  const debouncedInvSearch = ref('')
  const invPage = ref(1)
  const invPerPage = ref(50)
  const selectedCaseId = ref<number | null>(null)
  const selectedCaseName = ref('')

  const { debounceSearch: debounceInvSearch } = useDebouncedSearch()

  function onInvSearchInput() {
    debounceInvSearch(() => {
      debouncedInvSearch.value = invSearch.value
      invPage.value = 1
    })
  }

  const {
    data: invData,
    isLoading: invIsLoading,
    isFetching: invIsFetching,
    refetch: invRefetch,
  } = useQuery({
    queryKey: ['case-inventory', invPage, debouncedInvSearch, invPerPage],
    queryFn: () => get<InventorySummaryResponse>('/cases/inventory-summary', { page: invPage.value, per_page: invPerPage.value, search: debouncedInvSearch.value }),
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
  })

  const inventoryList = computed<InventorySummaryItem[]>(() => invData.value?.inventory ?? [])
  const invTotalPages = computed(() => invData.value?.pages ?? 0)
  const invStats = computed(() => invData.value?.stats ?? null)
  const invTotalStock = computed(() => invStats.value?.total_stock ?? 0)
  const invTotalIn = computed(() => invStats.value?.total_in ?? 0)
  const invTotalOut = computed(() => invStats.value?.total_out ?? 0)

  function selectCaseRow(row: InventorySummaryItem) {
    selectedCaseId.value = row.id
    selectedCaseName.value = row.name
    logPage.value = 1
  }

  // ===== 库存流水 =====
  const showLogFilter = ref(false)
  const logFilterType = ref('')
  const logFilterStart = ref('')
  const logFilterEnd = ref('')
  const logPage = ref(1)
  const logPerPage = ref(10)
  const logTotalPages = ref(1)

  const {
    data: logData,
    isLoading: logIsLoading,
    isFetching: logIsFetching,
    refetch: logRefetch,
  } = useQuery({
    queryKey: ['case-inventory-logs', selectedCaseId, logPage, logFilterType, logFilterStart, logFilterEnd, logPerPage],
    queryFn: async () => {
      const params: Record<string, string | number> = { page: logPage.value, per_page: logPerPage.value }
      if (logFilterType.value) params.type = logFilterType.value
      if (logFilterStart.value) params.start_date = logFilterStart.value
      if (logFilterEnd.value) params.end_date = logFilterEnd.value
      const res = await get<InventoryLogResponse>(`/cases/inventory-logs/${selectedCaseId.value}`, params)
      logTotalPages.value = res.pagination?.pages ?? 1
      return res
    },
    enabled: computed(() => !!selectedCaseId.value),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const logList = computed<InventoryLogItem[]>(() => logData.value?.logs ?? [])

  function onInvPageChange(event: { page: number; rows: number }) {
    invPage.value = event.page + 1
    invPerPage.value = event.rows
  }
  function onLogPageChange(event: { page: number; rows: number }) {
    logPage.value = event.page + 1
    logPerPage.value = event.rows
  }

  function clearLogFilter() {
    logFilterType.value = ''
    logFilterStart.value = ''
    logFilterEnd.value = ''
    logPage.value = 1
  }

  function logBadgeClass(t: string): string {
    const map: Record<string, string> = {
      '入库': 'ci-badge-success',
      '出库': 'ci-badge-danger',
      '入库调整': 'ci-badge-warning',
      '出库调整': 'ci-badge-warning',
      '删除入库': 'ci-badge-info',
      '删除出库': 'ci-badge-info',
      '批量导入入库': 'ci-badge-success',
      '批量导入出库': 'ci-badge-danger',
    }
    return map[t] ?? 'ci-badge-info'
  }

  return {
    invSearch,
    invPage,
    invPerPage,
    invIsLoading,
    invIsFetching,
    invRefetch,
    inventoryList,
    invTotalPages,
    invTotalStock,
    invTotalIn,
    invTotalOut,
    onInvSearchInput,
    onInvPageChange,
    selectCaseRow,
    selectedCaseId,
    selectedCaseName,
    showLogFilter,
    logFilterType,
    logFilterStart,
    logFilterEnd,
    logPage,
    logPerPage,
    logTotalPages,
    logIsLoading,
    logIsFetching,
    logRefetch,
    logList,
    onLogPageChange,
    clearLogFilter,
    logBadgeClass,
  }
}