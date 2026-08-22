import { ref, reactive, computed, watch } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { PurchaseOrder } from '@/types'

/** 快速筛选配置（/purchase/quick-filters 返回） */
export interface QuickFilter {
  id: string
  name?: string
  filters?: { start_date?: string; end_date?: string }
}

/** Vue Query 缓存 key */
export const COMPLETED_ORDERS_QUERY_KEY = 'completed-orders-list'
export const QUICK_FILTERS_QUERY_KEY = 'purchase-quick-filters'

export function useCompletedOrders() {
  const queryClient = useQueryClient()
  const page = ref(1)

  const filters = reactive({
    order_no: '',
    customer_name: '',
    product_name: '',
    supplier_name: '',
    barcode: '',
    material_name: '',
    start_date: '',
    end_date: '',
  })

  const currentQuickFilterId = ref<string | null>(null)
  const filterExpanded = ref(false)

  const { data, isLoading, isFetching } = useQuery({
    queryKey: [
      COMPLETED_ORDERS_QUERY_KEY,
      () => page.value,
      () => filters.order_no,
      () => filters.customer_name,
      () => filters.product_name,
      () => filters.supplier_name,
      () => filters.barcode,
      () => filters.material_name,
      () => filters.start_date,
      () => filters.end_date,
    ],
    queryFn: async () => {
      const params: Record<string, string | number> = { page: page.value, per_page: 20 }
      if (filters.order_no) params.order_no = filters.order_no
      if (filters.customer_name) params.customer_name = filters.customer_name
      if (filters.product_name) params.product_name = filters.product_name
      if (filters.supplier_name) params.supplier_name = filters.supplier_name
      if (filters.barcode) params.barcode = filters.barcode
      if (filters.material_name) params.material_name = filters.material_name
      if (filters.start_date) params.start_date = filters.start_date
      if (filters.end_date) params.end_date = filters.end_date
      try {
        return await purchaseApi.completed(params)
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

  const orders = computed<PurchaseOrder[]>(() => data.value?.orders ?? [])
  const total = computed(() => data.value?.total ?? 0)
  const totalPages = computed(() => data.value?.total_pages ?? data.value?.pages ?? 1)

  // P3-17: 当前页加载完成后，若存在下一页则静默预取（staleTime 30s 避免重复请求）。
  // 预取失败不弹 toast（后台行为）；用户翻页时若缓存有 error 则 Vue Query 自动 refetch。
  watch(data, (resp) => {
    if (resp && page.value < (resp.total_pages ?? resp.pages ?? 1)) {
      const nextPage = page.value + 1
      queryClient.prefetchQuery({
        queryKey: [
          COMPLETED_ORDERS_QUERY_KEY,
          nextPage,
          filters.order_no,
          filters.customer_name,
          filters.product_name,
          filters.supplier_name,
          filters.barcode,
          filters.material_name,
          filters.start_date,
          filters.end_date,
        ],
        queryFn: () => {
          const params: Record<string, string | number> = { page: nextPage, per_page: 20 }
          if (filters.order_no) params.order_no = filters.order_no
          if (filters.customer_name) params.customer_name = filters.customer_name
          if (filters.product_name) params.product_name = filters.product_name
          if (filters.supplier_name) params.supplier_name = filters.supplier_name
          if (filters.barcode) params.barcode = filters.barcode
          if (filters.material_name) params.material_name = filters.material_name
          if (filters.start_date) params.start_date = filters.start_date
          if (filters.end_date) params.end_date = filters.end_date
          return purchaseApi.completed(params)
        },
        staleTime: 30_000,
      })
    }
  })

  // 快速筛选配置：5 分钟 stale，避免 applyQuickFilter 时重复请求
  const { data: qfData } = useQuery({
    queryKey: [QUICK_FILTERS_QUERY_KEY],
    queryFn: () => purchaseApi.quickFilters(),
    staleTime: 5 * 60_000,
    gcTime: 10 * 60_000,
  })
  const quickFilters = computed<QuickFilter[]>(() => qfData.value?.quick_filters ?? [])

  function load() {
    return queryClient.invalidateQueries({ queryKey: [COMPLETED_ORDERS_QUERY_KEY] })
  }

  async function loadQuickFilters() {
    await queryClient.refetchQueries({ queryKey: [QUICK_FILTERS_QUERY_KEY] })
  }

  async function applyQuickFilter(filterId: string) {
    currentQuickFilterId.value = filterId
    const qf = quickFilters.value.find((f) => f.id === filterId)
    if (qf) {
      filters.start_date = qf.filters?.start_date || ''
      filters.end_date = qf.filters?.end_date || ''
      filters.order_no = ''
      filters.customer_name = ''
      filters.product_name = ''
      filters.supplier_name = ''
      filters.barcode = ''
      filters.material_name = ''
      page.value = 1
      // filters/page 变化触发 queryKey 变化，Vue Query 自动 refetch
    }
  }

  function resetFilters() {
    Object.assign(filters, {
      order_no: '',
      customer_name: '',
      product_name: '',
      supplier_name: '',
      barcode: '',
      material_name: '',
      start_date: '',
      end_date: '',
    })
    currentQuickFilterId.value = null
    page.value = 1
    // queryKey 变化自动 refetch
  }

  async function exportOrders() {
    const params: Record<string, string> = {}
    if (filters.order_no) params.order_no = filters.order_no
    if (filters.customer_name) params.customer_name = filters.customer_name
    if (filters.supplier_name) params.supplier_name = filters.supplier_name
    if (filters.start_date) params.start_date = filters.start_date
    if (filters.end_date) params.end_date = filters.end_date
    const res = await purchaseApi.exportCompleted(params)
    if (res.success && res.html) {
      const bom = '\uFEFF'
      const blob = new Blob([bom + res.html], { type: 'application/vnd.ms-excel;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = '下单查询汇总.xls'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      return true
    }
    throw new Error(res.message || '导出失败')
  }

  return reactive({
    orders,
    loading: isLoading,
    fetching: isFetching,
    page,
    total,
    totalPages,
    filters,
    quickFilters,
    currentQuickFilterId,
    filterExpanded,
    load,
    loadQuickFilters,
    applyQuickFilter,
    resetFilters,
    exportOrders,
  })
}
