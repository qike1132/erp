import { ref, computed } from 'vue'
import { orderApi, stockApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { OrderRecord } from './types'

/** 每页记录数 */
const PER_PAGE = 20

/** 工厂筛选选项（与后端 VALID_FACTORIES 保持一致） */
const FACTORY_OPTIONS = [
  { value: '东莞', label: '东莞' },
  { value: '湖北', label: '湖北' },
]

export function useOrderList() {
  const authStore = useAuthStore()
  // 当前用户工厂绑定：非空时筛选器锁定为本厂（权限隔离）
  const userFactory = computed(() => authStore.user?.factory || '')
  const factoryDisabled = computed(() => !!userFactory.value)

  const showFilter = ref(false)
  const filterCustomer = ref('')
  const filterOrderType = ref('')
  const filterStatus = ref('')
  const filterFactory = ref(userFactory.value)
  const filterStart = ref('')
  const filterEnd = ref('')
  const currentPage = ref(1)
  const totalPages = ref(1)
  const isLoadingRecords = ref(false)
  const isFetchingRecords = ref(false)
  const orderRecords = ref<OrderRecord[]>([])
  const recordType = ref<'order' | 'stockin'>('order')

  const recordTypeOptions = [
    { value: 'order' as const, label: '订单' },
    { value: 'stockin' as const, label: '备货' },
  ]

  const filterOrderTypeOptions = [
    { value: 'regular', label: '常规订单' },
    { value: 'custom', label: '定制订单' },
  ]

  const statusOptions = [
    { value: '待备货', label: '待备货' },
    { value: '已备货', label: '已备货' },
    { value: '部分备货', label: '部分备货' },
    { value: '待出货', label: '待出货' },
    { value: '已出货', label: '已出货' },
    { value: '已取消', label: '已取消' },
    { value: '批次已完成', label: '批次已完成' },
  ]

  function getStatusClass(status: string): string {
    const map: Record<string, string> = {
      '待备货': 'co-status-pending',
      '已备货': 'co-status-stocked',
      '部分备货': 'co-status-partial',
      '待出货': 'co-status-shipping',
      '已出货': 'co-status-shipped',
      '已取消': 'co-status-cancelled',
      '批次已完成': 'co-status-completed',
    }
    return map[status] || 'co-status-pending'
  }

  // 请求序列号：快速切换 tab/翻页时丢弃过期响应，避免脏数据覆盖
  let requestSeq = 0

  async function fetchOrders() {
    const seq = ++requestSeq
    const isInitial = orderRecords.value.length === 0
    if (isInitial) isLoadingRecords.value = true
    else isFetchingRecords.value = true
    try {
      if (recordType.value === 'stockin') {
        await fetchStockins(seq)
      } else {
        await fetchOrderRecords(seq)
      }
    } finally {
      // 仅当本次请求是最新请求时才清除 loading 状态
      if (seq === requestSeq) {
        isLoadingRecords.value = false
        isFetchingRecords.value = false
      }
    }
  }

  async function fetchOrderRecords(seq: number) {
    const params: Record<string, unknown> = { page: currentPage.value, per_page: PER_PAGE }
    if (filterCustomer.value) params.customer = filterCustomer.value
    if (filterOrderType.value) params.order_type = filterOrderType.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterFactory.value) params.factory = filterFactory.value
    if (filterStart.value) params.start_date = filterStart.value
    if (filterEnd.value) params.end_date = filterEnd.value
    const res = await orderApi.list(params) as any
    // 丢弃过期响应：快速切换 tab/翻页时旧请求可能晚到
    if (seq !== requestSeq) return
    const items: OrderRecord[] = (res.data ?? []).map((i: any) => ({ ...i, record_type: 'order' }) as OrderRecord)
    orderRecords.value = items
    const total = res.total ?? items.length
    totalPages.value = Math.ceil(total / PER_PAGE) || 1
  }

  async function fetchStockins(seq: number) {
    const params: Record<string, unknown> = { page: currentPage.value, per_page: PER_PAGE }
    if (filterCustomer.value) params.customer = filterCustomer.value
    if (filterOrderType.value) params.order_type = filterOrderType.value
    if (filterStart.value) params.start_date = filterStart.value
    if (filterEnd.value) params.end_date = filterEnd.value
    const res = await stockApi.stockins(params) as any
    if (seq !== requestSeq) return
    const rawItems: any[] = res.data ?? res.items ?? []
    orderRecords.value = rawItems.map((i) => ({
      ...i,
      record_type: 'stockin',
      order_date: i.stockin_date,
      order_no: i.stockin_no,
      deduct_quantity: i.deducted ?? 0,
    }) as OrderRecord)
    const total = res.total ?? rawItems.length
    totalPages.value = Math.ceil(total / PER_PAGE) || 1
  }

  function resetFilter() {
    filterCustomer.value = ''
    filterOrderType.value = ''
    filterStatus.value = ''
    // 锁定时保持本厂，否则重置为全部
    filterFactory.value = userFactory.value
    filterStart.value = ''
    filterEnd.value = ''
    currentPage.value = 1
    fetchOrders()
  }

  return {
    showFilter,
    filterCustomer,
    filterOrderType,
    filterStatus,
    filterFactory,
    filterStart,
    filterEnd,
    currentPage,
    totalPages,
    isLoadingRecords,
    isFetchingRecords,
    orderRecords,
    recordType,
    recordTypeOptions,
    filterOrderTypeOptions,
    factoryOptions: FACTORY_OPTIONS,
    factoryDisabled,
    statusOptions,
    getStatusClass,
    fetchOrders,
    resetFilter,
  }
}
