import { ref, computed, reactive } from 'vue'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { ApiResponse, PurchaseOrder } from '@/types'

export function usePurchaseOrders() {
  const orders = ref<PurchaseOrder[]>([])
  const loading = ref(false)
  const fetching = ref(false)
  const page = ref(1)
  const pages = ref(1)
  const total = ref(0)
  const selectedIds = ref<number[]>([])
  let loadController: AbortController | null = null

  const allSelected = computed(() => orders.value.length > 0 && selectedIds.value.length >= orders.value.length)

  async function load() {
    const isInitial = orders.value.length === 0
    if (isInitial) loading.value = true
    else fetching.value = true
    loadController?.abort()
    loadController = new AbortController()
    const signal = loadController.signal
    try {
      const res = await purchaseApi.orders({ page: page.value, per_page: 15, status: 'pending,confirmed' })
      if (signal.aborted) return
      orders.value = res.orders || []
      total.value = res.total || 0
      pages.value = res.pages || 1
    } catch (err: unknown) {
      if (signal.aborted) return
      orders.value = []
      showToast(getErrorMessage(err, '加载采购订单失败'), 'error')
    } finally {
      if (!signal.aborted) {
        loading.value = false
        fetching.value = false
      }
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

  async function completeOrder(orderId: number) {
    const res = await purchaseApi.completeOrder(orderId) as ApiResponse
    if (res.success) {
      await load()
      return true
    }
    throw new Error(res.message || '操作失败')
  }

  async function batchComplete() {
    const count = selectedIds.value.length
    const res = await purchaseApi.batchComplete([...selectedIds.value]) as ApiResponse & { completed_count?: number }
    if (res.success) {
      clearSelection()
      await load()
      return res.completed_count || count
    }
    throw new Error(res.message || '操作失败')
  }

  return reactive({
    orders,
    loading,
    fetching,
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
