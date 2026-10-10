import { ref, reactive, computed, watch, onScopeDispose } from 'vue'
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

/** Vue Query 缓存 key（与 persistQueryClient sessionStorage 持久化配合） */
export const UNPROCESSED_QUERY_KEY = 'unprocessed-orders'

/**
 * 未处理（待生成）订单列表。
 *
 * 采购订单已改为后端自动生成，本 composable 现为**只读**数据源，仅供采购页
 * 「待生成」区块展示「尚未生成采购单」的客户订单 / 备货记录（未配置BOM的会在
 * 该区块标红提示）。不再包含勾选与生成动作。
 */
export function useUnprocessedOrders(options?: { refetchInterval?: () => number | false }) {
  const queryClient = useQueryClient()
  const currentPage = ref(1)
  // 待生成行已并入「待生产订单」同一张表、不再单独分页，故一次多取以避免漏行。
  // 正常情况下待生成行≈0（订单秒级自动生成），只有缺 BOM 的会滞留，量很小。
  const perPage = ref(100)

  const { data, isLoading, isFetching, isError } = useQuery({
    queryKey: [UNPROCESSED_QUERY_KEY, () => currentPage.value, () => perPage.value],
    queryFn: async () => {
      try {
        return (await purchaseApi.unprocessedOrders({
          page: currentPage.value,
          per_page: perPage.value,
        })) as unknown as UnprocessedOrdersResponse
      } catch (err) {
        showToast(getErrorMessage(err, '加载待生成订单失败'), 'error')
        throw err
      }
    },
    // 每次显示都取数：持久化快照 + staleTime 会让刷新/切回本页时沿用旧列表。
    staleTime: 0,
    gcTime: 60_000,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
    placeholderData: keepPreviousData,
    retry: false,
    refetchInterval: options?.refetchInterval,
  })

  // 前端加载超时兜底：后端异常导致 query 长时间停在"加载中"时（axios 层最差约 15s），
  // 20s 后强制转错误态，保证加载状态必定会结束，由面板展示错误提示 + 重试。
  // 注意 immediate: true —— 首次加载时 isLoading 在 setup 即 true，若不加 immediate 且请求一直挂着，
  // watch 不会触发、定时器永远不会启动（安全网失效）。
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
    await queryClient.invalidateQueries({ queryKey: [UNPROCESSED_QUERY_KEY] })
  }

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

  function load(page?: number) {
    if (page !== undefined) {
      currentPage.value = page
      // P3-17: 页码变更由 Vue Query queryKey 自动触发 fetch；
      // 不 invalidate 以保留 prefetch 缓存（fresh 时秒切，stale 时后台 refetch）。
      return Promise.resolve()
    }
    return queryClient.invalidateQueries({ queryKey: [UNPROCESSED_QUERY_KEY] })
  }

  return reactive({
    orders,
    loading: isLoading,
    fetching: isFetching,
    error: loadError,
    retry,
    total,
    currentPage,
    totalPages,
    perPage,
    load,
  })
}
