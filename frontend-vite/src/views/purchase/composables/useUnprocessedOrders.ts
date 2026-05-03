import { ref, computed, reactive } from 'vue'
import { purchaseApi } from '@/api'
import type { UnprocessedOrder } from '@/types'

interface UnprocessedOrdersResponse {
  orders: UnprocessedOrder[]
  total: number
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
  const selectedIds = ref<number[]>([])

  const validSelectedIds = computed(() =>
    selectedIds.value.filter((id) => {
      const o = orders.value.find((x) => x.id === id)
      return o && o.has_bom
    }),
  )

  const allSelected = computed(() => orders.value.length > 0 && selectedIds.value.length >= orders.value.length)

  async function load() {
    loading.value = true
    try {
      const res = await purchaseApi.unprocessedOrders() as unknown as UnprocessedOrdersResponse
      orders.value = res.orders || []
      total.value = res.total || orders.value.length
    } catch {
      orders.value = []
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
