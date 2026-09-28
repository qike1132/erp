import { ref, computed } from 'vue'
import { orderApi, stockApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/types/errors'
import type { StockInRecord } from '@/types'
import type { OrderRecord } from './types'

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
  const filterStatus = ref('')
  const filterFactory = ref(userFactory.value)
  const filterStart = ref('')
  const filterEnd = ref('')
  const currentPage = ref(1)
  const perPage = ref(20)
  const totalPages = ref(1)
  const isLoadingRecords = ref(false)
  const isFetchingRecords = ref(false)
  /** 列表加载失败时的可读原因；非空即表示当前应展示错误态而非空态 */
  const errorMessage = ref('')
  const totalRecords = ref(0)
  const orderRecords = ref<OrderRecord[]>([])
  const recordType = ref<'order' | 'stockin'>('order')

  const recordTypeOptions = [
    { value: 'order' as const, label: '订单' },
    { value: 'stockin' as const, label: '备货' },
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
    errorMessage.value = ''
    try {
      if (recordType.value === 'stockin') {
        await fetchStockins(seq)
      } else {
        await fetchOrderRecords(seq)
      }
    } catch (e: unknown) {
      // 不再让异常逃逸：请求失败必须变成「可识别 + 可重试」的错误态，
      // 否则空数组会被空态槽渲染成「暂无记录」，把故障说成"没有数据"。
      if (seq === requestSeq) {
        errorMessage.value = getErrorMessage(e, '列表加载失败')
        if (isInitial) orderRecords.value = []
        totalRecords.value = 0
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
    const params: Record<string, unknown> = { page: currentPage.value, per_page: perPage.value }
    if (filterCustomer.value) params.customer = filterCustomer.value
    if (filterStatus.value) params.status = filterStatus.value
    if (filterFactory.value) params.factory = filterFactory.value
    if (filterStart.value) params.start_date = filterStart.value
    if (filterEnd.value) params.end_date = filterEnd.value
    const res = await orderApi.list(params)
    // 丢弃过期响应：快速切换 tab/翻页时旧请求可能晚到
    if (seq !== requestSeq) return
    const items: OrderRecord[] = (res.data ?? []).map((i) => ({ ...i, record_type: 'order' }) as OrderRecord)
    orderRecords.value = items
    const total = res.total ?? items.length
    totalRecords.value = total
    totalPages.value = Math.ceil(total / perPage.value) || 1
  }

  async function fetchStockins(seq: number) {
    const params: Record<string, unknown> = { page: currentPage.value, per_page: perPage.value }
    if (filterCustomer.value) params.customer = filterCustomer.value
    if (filterStart.value) params.start_date = filterStart.value
    if (filterEnd.value) params.end_date = filterEnd.value
    const res = await stockApi.stockins(params) as unknown as { data?: StockInRecord[]; items?: StockInRecord[]; total?: number }
    if (seq !== requestSeq) return
    const rawItems: StockInRecord[] = res.data ?? res.items ?? []
    orderRecords.value = rawItems.map((i) => ({
      ...i,
      record_type: 'stockin',
      order_date: i.stockin_date,
      order_no: i.stockin_no,
      deduct_quantity: i.deducted ?? 0,
    }) as OrderRecord)
    const total = res.total ?? rawItems.length
    totalRecords.value = total
    totalPages.value = Math.ceil(total / perPage.value) || 1
  }

  function resetFilter() {
    filterCustomer.value = ''
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
    filterStatus,
    filterFactory,
    filterStart,
    filterEnd,
    currentPage,
    perPage,
    totalPages,
    isLoadingRecords,
    isFetchingRecords,
    errorMessage,
    totalRecords,
    orderRecords,
    recordType,
    recordTypeOptions,
    factoryOptions: FACTORY_OPTIONS,
    factoryDisabled,
    statusOptions,
    getStatusClass,
    fetchOrders,
    resetFilter,
  }
}
