import { ref, computed, reactive, watch, onScopeDispose } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { ApiResponse, PurchaseOrder } from '@/types'

/** Vue Query 缓存 key */
export const PURCHASE_ORDERS_QUERY_KEY = 'purchase-orders-list'

export function usePurchaseOrders(options?: { refetchInterval?: () => number | false }) {
  const queryClient = useQueryClient()
  const page = ref(1)
  const selectedIds = ref<number[]>([])

  const { data, isLoading, isFetching, isError } = useQuery({
    queryKey: [PURCHASE_ORDERS_QUERY_KEY, () => page.value],
    queryFn: async () => {
      try {
        return await purchaseApi.orders({ page: page.value, per_page: 15, status: 'pending,confirmed' })
      } catch (err) {
        showToast(getErrorMessage(err, '加载采购订单失败'), 'error')
        throw err
      }
    },
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
    retry: false,
    refetchInterval: options?.refetchInterval,
  })

  // 前端加载超时兜底：后端异常导致 query 长时间停在"加载中"时，20s 后强制转错误态。
  // 注意 immediate: true —— 首次加载时 isLoading 在 setup 即 true，否则定时器不会启动（安全网失效）。
  const loadingTimedOut = ref(false)
  let loadingTimer: ReturnType<typeof setTimeout> | null = null
  watch([isLoading, isError], () => {
    if (loadingTimer) {
      clearTimeout(loadingTimer)
      loadingTimer = null
    }
    loadingTimedOut.value = false
    if (isLoading.value && !isError.value) {
      loadingTimer = setTimeout(() => {
        loadingTimedOut.value = true
      }, 20_000)
    }
  }, { immediate: true })
  onScopeDispose(() => {
    if (loadingTimer) clearTimeout(loadingTimer)
  })
  const loadError = computed(() => isError.value || loadingTimedOut.value)

  async function retry() {
    loadingTimedOut.value = false
    await queryClient.invalidateQueries({ queryKey: [PURCHASE_ORDERS_QUERY_KEY] })
  }

  const orders = computed<PurchaseOrder[]>(() => data.value?.orders ?? [])
  const total = computed(() => data.value?.total ?? 0)
  const pages = computed(() => data.value?.pages ?? 1)

  // P3-17: 当前页加载完成后，若存在下一页则静默预取（staleTime 30s 避免重复请求）。
  // 预取失败不弹 toast（后台行为）；用户翻页时若缓存有 error 则 Vue Query 自动 refetch。
  watch(data, (resp) => {
    if (resp && page.value < (resp.pages ?? 1)) {
      const nextPage = page.value + 1
      queryClient.prefetchQuery({
        queryKey: [PURCHASE_ORDERS_QUERY_KEY, nextPage],
        queryFn: () => purchaseApi.orders({ page: nextPage, per_page: 15, status: 'pending,confirmed' }),
        staleTime: 30_000,
      })
    }
  })

  const allSelected = computed(() => orders.value.length > 0 && selectedIds.value.length >= orders.value.length)

  function load() {
    return queryClient.invalidateQueries({ queryKey: [PURCHASE_ORDERS_QUERY_KEY] })
  }

  function toggleSelection(id: number) {
    const idx = selectedIds.value.indexOf(id)
    if (idx >= 0) selectedIds.value.splice(idx, 1)
    else selectedIds.value.push(id)
  }

  function toggleAll(checked: boolean) {
    if (checked) selectedIds.value = orders.value.map((o) => o.id)
    else selectedIds.value = []
  }

  function clearSelection() {
    selectedIds.value = []
  }

  async function completeOrder(orderId: number, spareRate?: number) {
    const res = (await purchaseApi.completeOrder(orderId, spareRate)) as ApiResponse
    if (res.success) {
      await load()
      return true
    }
    throw new Error(res.message || '操作失败')
  }

  async function batchComplete(spareRate?: number) {
    const count = selectedIds.value.length
    const res = (await purchaseApi.batchComplete([...selectedIds.value], spareRate)) as ApiResponse & { completed_count?: number }
    if (res.success) {
      clearSelection()
      await load()
      return res.completed_count || count
    }
    throw new Error(res.message || '操作失败')
  }

  return reactive({
    orders,
    loading: isLoading,
    fetching: isFetching,
    error: loadError,
    retry,
    page,
    pages,
    total,
    selectedIds,
    allSelected,
    load,
    toggleSelection,
    toggleAll,
    clearSelection,
    completeOrder,
    batchComplete,
  })
}
