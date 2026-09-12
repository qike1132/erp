import { ref, computed } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseInventoryItem, CaseInventoryLogItem } from '@/api/case'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'

export type { CaseInventoryItem, CaseInventoryLogItem }

/** 流水操作类型下拉选项（与后端 CaseInventoryLog.change_type 枚举一致） */
export const LOG_TYPE_OPTIONS = [
  { value: '入库', label: '入库' },
  { value: '出库', label: '出库' },
  { value: '入库调整', label: '入库调整' },
  { value: '出库调整', label: '出库调整' },
  { value: '删除入库', label: '删除入库' },
  { value: '删除出库', label: '删除出库' },
]

/** 库存汇总表列 */
export const INVENTORY_COLUMNS: TableColumn[] = [
  { field: 'name', header: '产品名称', align: 'left' },
  { field: 'barcode', header: '69码', align: 'center' },
  { field: 'initial_stock', header: '初始库存', align: 'right' },
  { field: 'total_in', header: '累计入库', align: 'right' },
  { field: 'total_out', header: '累计出库', align: 'right' },
  { field: 'current_stock', header: '当前库存', align: 'right' },
]

/** 流水表列 */
export const LOG_COLUMNS: TableColumn[] = [
  { field: 'change_type', header: '操作类型', align: 'center' },
  { field: 'change_quantity', header: '变化数量', align: 'right' },
  { field: 'customer', header: '客户', align: 'center' },
  { field: 'related_id', header: '关联单号', align: 'center' },
  { field: 'change_date', header: '时间', align: 'center' },
  { field: 'note', header: '备注', align: 'center' },
]

/** 流水类型徽标配色 */
export function logBadgeClass(changeType: string): string {
  const map: Record<string, string> = {
    '入库': 'cl-badge-success',
    '出库': 'cl-badge-danger',
    '入库调整': 'cl-badge-warning',
    '出库调整': 'cl-badge-warning',
    '删除入库': 'cl-badge-info',
    '删除出库': 'cl-badge-info',
  }
  return map[changeType] ?? 'cl-badge-info'
}

/**
 * 皮套库存查询：汇总统计 + 分产品库存表 + 单产品流水抽屉。
 * 流水查询仅在选中产品后启用。
 */
export function useCaseInventory() {
  // ===== 库存汇总 =====
  const invSearch = ref('')
  const debouncedInvSearch = ref('')
  const invPage = ref(1)
  const invPerPage = ref(50)

  const { data: invData, isLoading: invIsLoading, isFetching: invIsFetching, refetch: invRefetch } = useQuery({
    queryKey: ['case-inventory', invPage, debouncedInvSearch, invPerPage],
    queryFn: () =>
      caseApi.inventorySummary({
        page: invPage.value,
        per_page: invPerPage.value,
        search: debouncedInvSearch.value || undefined,
      }),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const inventoryList = computed<CaseInventoryItem[]>(() => invData.value?.inventory ?? [])
  const invTotal = computed(() => invData.value?.total ?? 0)
  const invTotalPages = computed(() => invData.value?.pages ?? 0)
  const invStats = computed(() => invData.value?.stats ?? null)

  function onInvSearchInput() {
    // 由组件层防抖后调用：回第 1 页并应用关键词
    debouncedInvSearch.value = invSearch.value
    invPage.value = 1
  }

  function onInvPageChange(event: { page: number; rows: number }) {
    invPage.value = event.page + 1
    invPerPage.value = event.rows
  }

  // ===== 流水抽屉 =====
  const selectedCase = ref<CaseInventoryItem | null>(null)
  const drawerOpen = ref(false)

  const showLogFilter = ref(false)
  const logFilterType = ref('')
  const logFilterStart = ref('')
  const logFilterEnd = ref('')
  const logPage = ref(1)
  const logPerPage = ref(10)

  const { data: logData, isLoading: logIsLoading, isFetching: logIsFetching, refetch: logRefetch } = useQuery({
    queryKey: ['case-inventory-logs', selectedCase, logPage, logFilterType, logFilterStart, logFilterEnd, logPerPage],
    queryFn: async () => {
      if (!selectedCase.value) return null
      const params: { page: number; per_page: number; type?: string; start_date?: string; end_date?: string } = {
        page: logPage.value,
        per_page: logPerPage.value,
      }
      if (logFilterType.value) params.type = logFilterType.value
      if (logFilterStart.value) params.start_date = logFilterStart.value
      if (logFilterEnd.value) params.end_date = logFilterEnd.value
      return caseApi.inventoryLogs(selectedCase.value.id, params)
    },
    enabled: computed(() => !!selectedCase.value),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const logList = computed<CaseInventoryLogItem[]>(() => logData.value?.logs ?? [])
  const logTotalPages = computed(() => logData.value?.pagination?.pages ?? 0)

  function openLogDrawer(row: CaseInventoryItem) {
    selectedCase.value = row
    logPage.value = 1
    drawerOpen.value = true
  }

  function closeLogDrawer() {
    drawerOpen.value = false
    selectedCase.value = null
  }

  function onLogPageChange(event: { page: number; rows: number }) {
    logPage.value = event.page + 1
    logPerPage.value = event.rows
  }

  function searchLogs() {
    logPage.value = 1
    logRefetch()
  }

  function clearLogFilter() {
    logFilterType.value = ''
    logFilterStart.value = ''
    logFilterEnd.value = ''
    logPage.value = 1
    logRefetch()
  }

  return {
    invSearch,
    invPage,
    invPerPage,
    invIsLoading,
    invIsFetching,
    invRefetch,
    inventoryList,
    invTotal,
    invTotalPages,
    invStats,
    onInvSearchInput,
    onInvPageChange,
    openLogDrawer,
    // 抽屉
    selectedCase,
    drawerOpen,
    closeLogDrawer,
    showLogFilter,
    logFilterType,
    logFilterStart,
    logFilterEnd,
    logPage,
    logPerPage,
    logTotalPages,
    logIsLoading,
    logIsFetching,
    logList,
    onLogPageChange,
    searchLogs,
    clearLogFilter,
  }
}
