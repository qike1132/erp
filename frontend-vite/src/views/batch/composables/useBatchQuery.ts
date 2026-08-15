/**
 * useBatchQuery.ts — 批次查询数据逻辑
 *
 * 从 BatchView.vue 下沉的逻辑：主查询（按批次/客户/关键字）、客户白名单
 * 查询与保存、客户→产品→订单分组、完成批次确认流程。
 */
import { ref, reactive, computed, watch } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { batchApi, orderBatchApi, customerApi } from '@/api'
import type { BatchQueryItem } from '@/types'
import { showToast } from '@/composables/useToast'

/** 产品分组：同一产品下的订单/备货记录 */
export interface ProductGroup {
  key: string
  productName: string | null
  productBarcode: string | null
  orders: BatchQueryItem[]
}

/** 客户分组：客户 → 产品 → 订单 */
export interface CustomerGroup {
  customer: string
  products: ProductGroup[]
}

/** 批次查询：主查询 + 白名单 + 分组 + 完成批次 */
export function useBatchQuery() {
  const perPage = ref(500)

  const filters = reactive({ batch_no: '', customer: '', status: '', keyword: '' })

  // ---- Whitelist customers ----
  const { data: whitelistData, refetch: refetchWhitelist } = useQuery({
    queryKey: ['order-batch-whitelist'],
    queryFn: () => orderBatchApi.whitelist(),
    staleTime: 300_000,
  })
  const whitelistCustomers = computed<string[]>(() => whitelistData.value?.customers ?? [])

  // Auto-select first whitelist customer
  watch(whitelistCustomers, (list) => {
    if (list.length && (!filters.customer || !list.includes(filters.customer))) {
      filters.customer = list[0]!
    }
  }, { immediate: true })

  // ---- All active customers（白名单弹窗候选） ----
  const { data: activeNamesData } = useQuery({
    queryKey: ['customer-active-names'],
    queryFn: () => customerApi.activeNames(),
    staleTime: 300_000,
  })
  const allCustomers = computed<string[]>(() =>
    (activeNamesData.value ?? []).map((c: { name: string }) => c.name)
  )

  // ---- Main data query ----
  const {
    data: result,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['batch-query', perPage, filters],
    queryFn: async () => {
      const params: Record<string, unknown> = { per_page: perPage.value }
      if (filters.batch_no) params.batch_no = filters.batch_no
      if (filters.customer) params.customer = filters.customer
      if (filters.status) params.status = filters.status
      if (filters.keyword) params.keyword = filters.keyword
      return await batchApi.list(params)
    },
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const items = computed<BatchQueryItem[]>(() => result.value?.data ?? [])

  // ---- Grouped data: customer → product → orders ----
  const grouped = computed<CustomerGroup[]>(() => {
    const wl = whitelistCustomers.value
    const wlSet = new Set(wl)
    const whitelistLoaded = wl.length > 0 || whitelistData.value !== undefined
    const map = new Map<string, Map<string, BatchQueryItem[]>>()
    const order: string[] = []

    for (const item of items.value) {
      if (whitelistLoaded && !wlSet.has(item.customer)) continue
      const cKey = item.customer
      if (!map.has(cKey)) {
        map.set(cKey, new Map())
        order.push(cKey)
      }
      const pMap = map.get(cKey)!
      const pKey = `${item.product_id}`
      if (!pMap.has(pKey)) {
        pMap.set(pKey, [])
      }
      pMap.get(pKey)!.push(item)
    }

    return order.map(c => ({
      customer: c,
      products: Array.from(map.get(c)!.entries()).map(([pKey, orders]) => ({
        key: pKey,
        productName: orders[0]!.product_name,
        productBarcode: orders[0]!.product_barcode,
        orders: orders.sort((a, b) => (a.order_date ?? '').localeCompare(b.order_date ?? '')),
      })),
    }))
  })

  /** 切换客户筛选并重新查询 */
  function switchCustomer(customer: string) {
    filters.customer = customer
    refetch()
  }

  /** 白名单保存成功后：刷新白名单与主列表 */
  async function refreshAfterWhitelistSaved() {
    await refetchWhitelist()
    refetch()
  }

  // ---- Complete batch ----
  const showCompleteModal = ref(false)
  const completingBatchNo = ref('')
  const completing = ref(false)

  /** 打开完成批次确认弹窗 */
  function openCompleteConfirm(order: BatchQueryItem) {
    completingBatchNo.value = order.batch_no!
    showCompleteModal.value = true
  }

  /** 确认完成批次操作 */
  async function confirmComplete() {
    completing.value = true
    try {
      await orderBatchApi.completeBatch({ batch_no: completingBatchNo.value })
      showToast('批次已完成', 'success')
      showCompleteModal.value = false
      refetch()
    } catch {
      showToast('批次完成操作失败', 'error')
    } finally {
      completing.value = false
    }
  }

  return {
    filters,
    result,
    whitelistCustomers,
    allCustomers,
    isLoading,
    isFetching,
    refetch,
    grouped,
    switchCustomer,
    refreshAfterWhitelistSaved,
    showCompleteModal,
    completingBatchNo,
    completing,
    openCompleteConfirm,
    confirmComplete,
  }
}
