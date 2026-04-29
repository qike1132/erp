import { ref, computed, reactive } from 'vue'
import { purchaseApi } from '@/api'

export function usePurchaseOrders() {
  const orders = ref<any[]>([])
  const loading = ref(false)
  const page = ref(1)
  const pages = ref(1)
  const total = ref(0)
  const selectedIds = ref<number[]>([])

  const allSelected = computed(() => orders.value.length > 0 && selectedIds.value.length >= orders.value.length)

  async function load() {
    loading.value = true
    try {
      const res = (await purchaseApi.orders({ page: page.value, per_page: 15 })) as any
      orders.value = res.orders || []
      total.value = res.total || 0
      pages.value = res.pages || 1
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

  async function completeOrder(orderId: number) {
    const res = (await purchaseApi.completeOrder(orderId)) as any
    if (res.success) {
      await load()
      return true
    }
    throw new Error(res.message || '操作失败')
  }

  async function batchComplete() {
    const count = selectedIds.value.length
    const res = (await purchaseApi.batchComplete([...selectedIds.value])) as any
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
