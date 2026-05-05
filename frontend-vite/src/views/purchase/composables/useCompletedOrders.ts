import { ref, reactive, computed } from 'vue'
import { purchaseApi } from '@/api'
import { showToast } from '@/composables/useToast'
import type { ApiResponse, PurchaseOrder } from '@/types'

interface QuickFilter {
  id: string
  name?: string
  filters?: { start_date?: string; end_date?: string }
}

export function useCompletedOrders() {
  const orders = ref<PurchaseOrder[]>([])
  const loading = ref(false)
  const page = ref(1)
  const total = ref(0)
  const totalPages = ref(1)

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

  const quickFilters = ref<QuickFilter[]>([])
  const currentQuickFilterId = ref<string | null>(null)
  const filterExpanded = ref(false)

  async function load() {
    loading.value = true
    try {
      const params: Record<string, string | number> = { page: page.value, per_page: 20 }
      if (filters.order_no) params.order_no = filters.order_no
      if (filters.customer_name) params.customer_name = filters.customer_name
      if (filters.product_name) params.product_name = filters.product_name
      if (filters.supplier_name) params.supplier_name = filters.supplier_name
      if (filters.barcode) params.barcode = filters.barcode
      if (filters.material_name) params.material_name = filters.material_name
      if (filters.start_date) params.start_date = filters.start_date
      if (filters.end_date) params.end_date = filters.end_date
      const res = await purchaseApi.completed(params) as ApiResponse<PurchaseOrder[]> & { orders?: PurchaseOrder[]; total?: number; total_pages?: number; pages?: number }
      orders.value = res.orders || []
      total.value = res.total || 0
      totalPages.value = res.total_pages || res.pages || 1
    } catch (err: any) {
      orders.value = []
      showToast(err.response?.data?.detail || '加载已完成订单失败', 'error')
    } finally {
      loading.value = false
    }
  }

  async function loadQuickFilters() {
    try {
      const res = await purchaseApi.quickFilters() as ApiResponse & { quick_filters?: QuickFilter[] }
      if (res.success && res.quick_filters) quickFilters.value = res.quick_filters
    } catch {
      /* ignore */
    }
  }

  async function applyQuickFilter(filterId: string) {
    currentQuickFilterId.value = filterId
    try {
      const res = await purchaseApi.quickFilters() as ApiResponse & { quick_filters?: QuickFilter[] }
      if (res.success && res.quick_filters) {
        const filter = res.quick_filters.find((f) => f.id === filterId)
        if (filter) {
          filters.start_date = filter.filters?.start_date || ''
          filters.end_date = filter.filters?.end_date || ''
          filters.order_no = ''
          filters.customer_name = ''
          filters.product_name = ''
          filters.supplier_name = ''
          filters.barcode = ''
          filters.material_name = ''
          page.value = 1
          await load()
        }
      }
    } catch {
      /* ignore */
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
    load()
  }

  async function exportOrders() {
    const params: Record<string, string> = {}
    if (filters.order_no) params.order_no = filters.order_no
    if (filters.customer_name) params.customer_name = filters.customer_name
    if (filters.supplier_name) params.supplier_name = filters.supplier_name
    if (filters.start_date) params.start_date = filters.start_date
    if (filters.end_date) params.end_date = filters.end_date
    const res = await purchaseApi.exportCompleted(params) as ApiResponse & { html?: string }
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
    loading,
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
