import { ref, computed } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { caseApi } from '@/api'
import type { CaseInventoryNode, CaseInventoryStats, CaseMovement } from '@/api/case'
import type { TableColumn } from '@/components/ui/UiDataTable.vue'

export type { CaseInventoryNode, CaseInventoryStats, CaseMovement }

/** 抽屉内的流水列 */
export const MOVEMENT_COLUMNS: TableColumn[] = [
  { field: 'direction', header: '方向', align: 'center' },
  { field: 'movement_no', header: '单号', align: 'center' },
  { field: 'movement_date', header: '日期', align: 'center' },
  { field: 'quantity', header: '数量', align: 'right' },
  { field: 'note', header: '备注', align: 'center' },
]

/** 方向 → 中文标签 */
export function directionLabel(direction: string): string {
  return direction === 'in' ? '入库' : '出库'
}

/**
 * 皮套库存查询：整体统计 + 主件分组的库存表 + 单 SKU 流水抽屉。
 * 主件行可展开其配件；流水仅在某 SKU 被选中后启用。
 */
export function useCaseInventory() {
  // ===== 库存汇总（主件分组） =====
  const invSearch = ref('')
  // 已**提交**的关键词（由组件层在「回车 / 点放大镜 / 点×清空」时经 onInvSearchInput 赋值
  // —— UiSearchInput 没有内置防抖，是"显式提交"语义）。queryKey 与请求**必须**用它，
  // 不能直接用 invSearch —— 那是 v-model 绑定，每敲一键都会变，会导致逐键打接口。
  const debouncedInvSearch = ref('')
  const invPage = ref(1)
  const invPerPage = ref(50)

  const { data: invData, isLoading: invIsLoading, isFetching: invIsFetching, refetch: invRefetch } = useQuery({
    queryKey: ['case-inventory', invPage, debouncedInvSearch, invPerPage],
    queryFn: () =>
      caseApi.inventory({
        page: invPage.value,
        per_page: invPerPage.value,
        search: debouncedInvSearch.value || undefined,
      }),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const inventoryList = computed<CaseInventoryNode[]>(() => invData.value?.inventory ?? [])
  const invTotal = computed(() => invData.value?.total ?? 0)
  const invTotalPages = computed(() => invData.value?.pages ?? 0)
  const invStats = computed<CaseInventoryStats | null>(() => invData.value?.stats ?? null)

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
  const selectedCase = ref<CaseInventoryNode | null>(null)
  const drawerOpen = ref(false)
  const logPage = ref(1)
  const logPerPage = ref(10)

  const { data: logData, isLoading: logIsLoading, isFetching: logIsFetching } = useQuery({
    queryKey: ['case-movements-drawer', selectedCase, logPage, logPerPage],
    queryFn: async () => {
      if (!selectedCase.value) return null
      return caseApi.movements({
        case_id: selectedCase.value.id,
        page: logPage.value,
        per_page: logPerPage.value,
      })
    },
    enabled: computed(() => !!selectedCase.value),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const logList = computed<CaseMovement[]>(() => logData.value?.movements ?? [])
  const logTotal = computed(() => logData.value?.total ?? 0)
  const logTotalPages = computed(() => logData.value?.pages ?? 0)

  function openLogDrawer(row: CaseInventoryNode) {
    selectedCase.value = row
    logPage.value = 1
    drawerOpen.value = true
  }

  function onLogPageChange(event: { page: number; rows: number }) {
    logPage.value = event.page + 1
    logPerPage.value = event.rows
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
    selectedCase,
    drawerOpen,
    logPage,
    logPerPage,
    logTotal,
    logTotalPages,
    logIsLoading,
    logIsFetching,
    logList,
    onLogPageChange,
  }
}
