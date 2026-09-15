import { ref, reactive, computed, watch, onScopeDispose } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { PurchaseOrder } from '@/types'

/** Vue Query 缓存 key */
export const COMPLETED_ORDERS_QUERY_KEY = 'completed-orders-list'

/** 每页条数（后端 per_page 上限 500） */
const PER_PAGE = 20

export interface CompletedOrderFilters {
  order_no: string
  customer_name: string
  product_name: string
  start_date: string
  end_date: string
}

const FILTER_KEYS = ['order_no', 'customer_name', 'product_name', 'start_date', 'end_date'] as const

/** 把筛选条件拼成接口参数（查询与导出共用，避免两处重复） */
function buildParams(filters: CompletedOrderFilters, page?: number): Record<string, string | number> {
  const params: Record<string, string | number> = {}
  if (page != null) {
    params.page = page
    params.per_page = PER_PAGE
  }
  for (const key of FILTER_KEYS) {
    const value = filters[key]
    if (value) params[key] = value
  }
  return params
}

/**
 * useCompletedOrders — 下单查询数据层
 *
 * 只做三件事：搜索/查询（filters + page → 列表）、导出、重置。
 * 查询为显式提交（点"查询"或回车），不做输入即请求，避免每键一次请求。
 */
export function useCompletedOrders() {
  const queryClient = useQueryClient()
  const page = ref(1)

  /** 已提交的筛选条件（真正参与请求） */
  const filters = reactive<CompletedOrderFilters>({
    order_no: '',
    customer_name: '',
    product_name: '',
    start_date: '',
    end_date: '',
  })

  /** 表单草稿：用户编辑中，点"查询"才写入 filters */
  const draft = reactive<CompletedOrderFilters>({ ...filters })

  /** 草稿与已提交条件是否有差异（用于"查询"按钮的强调态） */
  const isDirty = computed(() => FILTER_KEYS.some((k) => draft[k] !== filters[k]))

  /** 是否处于筛选状态（用于空状态文案与重置按钮可用性） */
  const hasFilter = computed(() => FILTER_KEYS.some((k) => !!filters[k]))

  const { data, isLoading, isFetching, isError } = useQuery({
    queryKey: [COMPLETED_ORDERS_QUERY_KEY, page, { ...filters }],
    queryFn: async () => {
      try {
        return await purchaseApi.completed(buildParams(filters, page.value))
      } catch (err) {
        showToast(getErrorMessage(err, '加载已完成订单失败'), 'error')
        throw err
      }
    },
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
    retry: false,
  })

  // 加载超时兜底：后端挂住时 20s 强制转错误态，保证加载状态必定结束
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

  const orders = computed<PurchaseOrder[]>(() => data.value?.orders ?? [])
  const total = computed(() => data.value?.total ?? 0)
  const totalPages = computed(() => data.value?.total_pages ?? data.value?.pages ?? 1)
  const error = computed(() => isError.value || loadingTimedOut.value)

  /** 查询：把草稿提交为生效条件并回到第 1 页（queryKey 变化自动请求） */
  function search() {
    // 日期区间校验：起始晚于截止时阻断，避免返回空结果让用户困惑
    if (draft.start_date && draft.end_date && draft.start_date > draft.end_date) {
      showToast('开始日期不能晚于结束日期', 'warning')
      return
    }
    for (const key of FILTER_KEYS) filters[key] = draft[key]
    page.value = 1
  }

  /** 重置：清空草稿与生效条件，回到第 1 页 */
  function reset() {
    for (const key of FILTER_KEYS) {
      draft[key] = ''
      filters[key] = ''
    }
    page.value = 1
  }

  /** 刷新：保留当前条件重新请求 */
  function refresh() {
    return queryClient.invalidateQueries({ queryKey: [COMPLETED_ORDERS_QUERY_KEY] })
  }

  async function retry() {
    loadingTimedOut.value = false
    await refresh()
  }

  /** 导出：按当前生效条件导出，成功后触发浏览器下载 */
  async function exportOrders(): Promise<void> {
    const res = await purchaseApi.exportCompleted(buildParams(filters))
    if (!res.success || !res.html) throw new Error(res.message || '导出失败')
    const blob = new Blob(['\uFEFF' + res.html], { type: 'application/vnd.ms-excel;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '下单查询汇总.xls'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return reactive({
    orders,
    loading: isLoading,
    fetching: isFetching,
    error,
    total,
    totalPages,
    page,
    filters,
    draft,
    isDirty,
    hasFilter,
    search,
    reset,
    refresh,
    retry,
    exportOrders,
  })
}
