import { ref, computed, reactive, watch } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { UnprocessedOrder } from '@/types'

interface UnprocessedOrdersResponse {
  success?: boolean
  orders: UnprocessedOrder[]
  total: number
  pages: number
  current_page: number
  /** 最近一次同步时间 */
  latest_sync_time?: string | null
}

interface OneClickGenerateResponse {
  success: boolean
  message?: string
  created_count: number
  orders: { id: number; order_no: string }[]
}

/** Vue Query 缓存 key（与 persistQueryClient sessionStorage 持久化配合） */
export const UNPROCESSED_QUERY_KEY = 'unprocessed-orders'

export function useUnprocessedOrders(options?: { refetchInterval?: () => number | false }) {
  const queryClient = useQueryClient()
  const currentPage = ref(1)
  const perPage = ref(15)
  const selectedCompositeIds = ref<string[]>([])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: [UNPROCESSED_QUERY_KEY, () => currentPage.value, () => perPage.value],
    queryFn: async () => {
      try {
        return (await purchaseApi.unprocessedOrders({
          page: currentPage.value,
          per_page: perPage.value,
        })) as unknown as UnprocessedOrdersResponse
      } catch (err) {
        showToast(getErrorMessage(err, '加载待审核订单失败'), 'error')
        throw err
      }
    },
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
    retry: false,
    refetchInterval: options?.refetchInterval,
  })

  const orders = computed<UnprocessedOrder[]>(() => data.value?.orders ?? [])
  const total = computed(() => data.value?.total ?? 0)
  const totalPages = computed(() => data.value?.pages ?? Math.max(1, Math.ceil(total.value / perPage.value)))

  // P3-17: 当前页加载完成后，若存在下一页则静默预取（staleTime 30s 避免重复请求）。
  // 预取失败不弹 toast（后台行为）；用户翻页时若缓存有 error 则 Vue Query 自动 refetch。
  watch(data, (resp) => {
    if (resp && resp.current_page < (resp.pages ?? 1)) {
      const nextPage = resp.current_page + 1
      queryClient.prefetchQuery({
        queryKey: [UNPROCESSED_QUERY_KEY, nextPage, perPage.value],
        queryFn: () =>
          purchaseApi.unprocessedOrders({
            page: nextPage,
            per_page: perPage.value,
          }) as unknown as Promise<UnprocessedOrdersResponse>,
        staleTime: 30_000,
      })
    }
  })

  const orderMap = computed(() => {
    const m = new Map<string, UnprocessedOrder>()
    for (const o of orders.value) m.set(o.composite_id, o)
    return m
  })

  const validSelectedCompositeIds = computed(() =>
    selectedCompositeIds.value.filter((cid) => {
      const o = orderMap.value.get(cid)
      return o && o.has_bom
    }),
  )

  const allSelected = computed(() => orders.value.length > 0 && selectedCompositeIds.value.length >= orders.value.length)

  function load(page?: number) {
    if (page !== undefined) {
      currentPage.value = page
      // P3-17: 页码变更由 Vue Query queryKey 自动触发 fetch；
      // 不 invalidate 以保留 prefetch 缓存（fresh 时秒切，stale 时后台 refetch）。
      return Promise.resolve()
    }
    return queryClient.invalidateQueries({ queryKey: [UNPROCESSED_QUERY_KEY] })
  }

  function toggleSelection(compositeId: string) {
    const idx = selectedCompositeIds.value.indexOf(compositeId)
    if (idx >= 0) selectedCompositeIds.value.splice(idx, 1)
    else selectedCompositeIds.value.push(compositeId)
  }

  function toggleAll(checked: boolean) {
    if (checked) selectedCompositeIds.value = orders.value.map((o) => o.composite_id)
    else selectedCompositeIds.value = []
  }

  function clearSelection() {
    selectedCompositeIds.value = []
  }

  async function oneClickGenerate() {
    if (validSelectedCompositeIds.value.length === 0) throw new Error('请选择至少一个有BOM配置的订单')
    const res = (await purchaseApi.oneClickGenerate({
      composite_ids: validSelectedCompositeIds.value,
    })) as unknown as OneClickGenerateResponse
    if (res.success) {
      clearSelection()
      return res
    }
    throw new Error(res.message || '审核失败')
  }

  async function quickGenerateSingle(compositeId: string) {
    const order = orders.value.find((o) => o.composite_id === compositeId)
    if (!order?.has_bom) throw new Error(`订单 ${order?.order_no || ''}无法审核：该产品未配置BOM表`)
    const res = (await purchaseApi.oneClickGenerate({ composite_ids: [compositeId] })) as unknown as OneClickGenerateResponse
    if (res.success) return res
    throw new Error(res.message || '审核失败')
  }

  return reactive({
    orders,
    loading: isLoading,
    fetching: isFetching,
    total,
    currentPage,
    totalPages,
    perPage,
    selectedCompositeIds,
    validSelectedCompositeIds,
    allSelected,
    load,
    toggleSelection,
    toggleAll,
    clearSelection,
    oneClickGenerate,
    quickGenerateSingle,
  })
}
