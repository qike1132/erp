import { ref, computed, reactive } from 'vue'
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

export function useUnprocessedOrders() {
  const orders = ref<UnprocessedOrder[]>([])
  const loading = ref(false)
  const fetching = ref(false)
  const total = ref(0)
  const currentPage = ref(1)
  const totalPages = ref(1)
  const perPage = ref(15)
  const selectedCompositeIds = ref<string[]>([])
  let loadController: AbortController | null = null

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

  async function load(page?: number) {
    const isInitial = orders.value.length === 0
    if (isInitial) loading.value = true
    else fetching.value = true
    loadController?.abort()
    loadController = new AbortController()
    const signal = loadController.signal
    try {
      const p = page ?? currentPage.value
      const res = await purchaseApi.unprocessedOrders({ page: p, per_page: perPage.value }) as unknown as UnprocessedOrdersResponse
      if (signal.aborted) return
      orders.value = res.orders || []
      total.value = res.total || orders.value.length
      totalPages.value = res.pages || Math.max(1, Math.ceil(total.value / perPage.value))
      currentPage.value = res.current_page || p
      selectedCompositeIds.value = []
    } catch (err: unknown) {
      if (signal.aborted) return
      orders.value = []
      showToast(getErrorMessage(err, '加载待审核订单失败'), 'error')
    } finally {
      if (!signal.aborted) {
        loading.value = false
        fetching.value = false
      }
    }
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
    const res = await purchaseApi.oneClickGenerate({ composite_ids: validSelectedCompositeIds.value }) as unknown as OneClickGenerateResponse
    if (res.success) {
      clearSelection()
      return res
    }
    throw new Error(res.message || '审核失败')
  }

  async function quickGenerateSingle(compositeId: string) {
    const order = orders.value.find((o) => o.composite_id === compositeId)
    if (!order?.has_bom) throw new Error(`订单 ${order?.order_no || ''}无法审核：该产品未配置BOM表`)
    const res = await purchaseApi.oneClickGenerate({ composite_ids: [compositeId] }) as unknown as OneClickGenerateResponse
    if (res.success) return res
    throw new Error(res.message || '审核失败')
  }

  return reactive({
    orders,
    loading,
    fetching,
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
