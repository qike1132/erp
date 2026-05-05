import { ref, computed, reactive } from 'vue'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { UnprocessedOrder } from '@/types'

interface UnprocessedOrdersResponse {
  orders: UnprocessedOrder[]
  total: number
  pages: number
  current_page: number
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
  const total = ref(0)
  const currentPage = ref(1)
  const totalPages = ref(1)
  const perPage = ref(15)
  const selectedIds = ref<number[]>([])

  const validSelectedIds = computed(() =>
    selectedIds.value.filter((id) => {
      const o = orders.value.find((x) => x.id === id)
      return o && o.has_bom
    }),
  )

  const allSelected = computed(() => orders.value.length > 0 && selectedIds.value.length >= orders.value.length)

  async function load(page?: number) {
    loading.value = true
    try {
      const p = page ?? currentPage.value
      const res = await purchaseApi.unprocessedOrders({ page: p, per_page: perPage.value }) as unknown as UnprocessedOrdersResponse
      orders.value = res.orders || []
      total.value = res.total || orders.value.length
      totalPages.value = res.pages || 1
      currentPage.value = res.current_page || p
      selectedIds.value = []
    } catch (err: any) {
      orders.value = []
      showToast(err.response?.data?.detail || '加载待审核订单失败', 'error')
    } finally {
      loading.value = false
    }
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

  async function oneClickGenerate() {
    if (validSelectedIds.value.length === 0) throw new Error('请选择至少一个有BOM配置的订单')
    const res = await purchaseApi.oneClickGenerate({ order_ids: validSelectedIds.value }) as unknown as OneClickGenerateResponse
    if (res.success) {
      clearSelection()
      return res
    }
    throw new Error(res.message || '审核失败')
  }

  async function quickGenerateSingle(orderId: number) {
    const order = orders.value.find((o) => o.id === orderId)
    if (!order?.has_bom) throw new Error(`订单 ${order?.order_no || ''}无法审核：该产品未配置BOM表`)
    const res = await purchaseApi.oneClickGenerate({ order_ids: [orderId] }) as unknown as OneClickGenerateResponse
    if (res.success) return res
    throw new Error(res.message || '审核失败')
  }

  return reactive({
    orders,
    loading,
    total,
    currentPage,
    totalPages,
    perPage,
    selectedIds,
    validSelectedIds,
    allSelected,
    load,
    toggleSelection,
    toggleAll,
    clearSelection,
    oneClickGenerate,
    quickGenerateSingle,
  })
}
