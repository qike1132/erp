import { ref, computed } from 'vue'
import { orderApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import { getErrorMessage } from '@/types/errors'
import type { OrderRecord } from './types'

/** 工厂筛选选项（与后端 VALID_FACTORIES 保持一致） */
const FACTORY_OPTIONS = [
  { value: '东莞', label: '东莞' },
  { value: '湖北', label: '湖北' },
]

export function useOrderList() {
  const authStore = useAuthStore()
  // 当前用户工厂绑定：非空时后端强制按本厂过滤（权限隔离），前端不再展示工厂筛选
  const userFactory = computed(() => authStore.user?.factory || '')

  /** 记录类型筛选：all=全部 / order=订单 / stockin=备货（B1 单端点契约）；F2 起恒为 all */
  const filterType = ref<'all' | 'order' | 'stockin'>('all')
  /** 搜索框 OR 关键字：单号 / 客户 / 产品名 / 条码（后端 keyword 参数） */
  const keyword = ref('')
  const currentPage = ref(1)
  const perPage = ref(20)
  const totalPages = ref(1)
  const isLoadingRecords = ref(false)
  const isFetchingRecords = ref(false)
  /** 列表加载失败时的可读原因；非空即表示当前应展示错误态而非空态 */
  const errorMessage = ref('')
  const totalRecords = ref(0)
  const orderRecords = ref<OrderRecord[]>([])

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
      const params: Record<string, unknown> = {
        page: currentPage.value,
        per_page: perPage.value,
        record_type: filterType.value,
      }
      if (keyword.value.trim()) params.keyword = keyword.value.trim()
      const res = await orderApi.records(params)
      // 丢弃过期响应：快速切换 tab/翻页时旧请求可能晚到
      if (seq !== requestSeq) return
      // 后端已归一化（record_type/order_no/order_date/status/deduct_quantity 均由后端下发），
      // 前端不再按 recordType 二态分支、不再对备货行 map i.deducted。
      orderRecords.value = (res.data ?? []) as unknown as OrderRecord[]
      const total = res.total ?? orderRecords.value.length
      totalRecords.value = total
      totalPages.value = Math.ceil(total / perPage.value) || 1
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

  /** 搜索框「查询」：回第 1 页再查询（否则可能停在超出结果范围的页码上） */
  function search() {
    currentPage.value = 1
    fetchOrders()
  }

  /** 搜索框 ✕：清空关键字并立即重新查询 */
  function clearKeyword() {
    keyword.value = ''
    search()
  }

  return {
    filterType,
    keyword,
    currentPage,
    perPage,
    totalPages,
    isLoadingRecords,
    isFetchingRecords,
    errorMessage,
    totalRecords,
    orderRecords,
    factoryOptions: FACTORY_OPTIONS,
    userFactory,
    statusOptions,
    getStatusClass,
    fetchOrders,
    search,
    clearKeyword,
  }
}
