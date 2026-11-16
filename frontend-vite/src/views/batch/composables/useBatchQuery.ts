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
import { useDebouncedRef } from '@/composables/useDebouncedRef'

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

/** 列表端点单页上限（后端 per_page le=500）——与 OutsourcePresetTab 同口径 */
const BATCH_PAGE_SIZE = 500
/** 分页护栏：最多 20 页，防异常响应（恒满页）死循环（照 P1-23 模式） */
const BATCH_MAX_PAGES = 20

/** 翻页触顶的行数上限（20 页 × 500 行）：超过它的结果只能拿到前 N 行 */
const BATCH_MAX_ROWS = BATCH_MAX_PAGES * BATCH_PAGE_SIZE

/**
 * 触顶提示文案：写明真实上限，避免与 BATCH_MAX_PAGES 改动后脱节。
 * 静默截断会让「完成批次」基于残缺列表做决策，必须让用户看见。
 */
export const BATCH_TRUNCATED_HINT =
  `结果超过 ${BATCH_MAX_ROWS} 行，已截断，请收窄筛选`

/** 批次查询的完整结果：truncated=true 表示只拿到了前 BATCH_MAX_ROWS 行 */
export interface BatchQueryResult {
  data: BatchQueryItem[]
  /** 后端返回的真实总数（触顶时**不得**退化成已拉取行数） */
  total: number
  truncated: boolean
}

/** 批次查询：主查询 + 白名单 + 分组 + 完成批次 */
export function useBatchQuery() {
  const perPage = ref(500)

  const filters = reactive({ batch_no: '', customer: '', status: '', keyword: '' })
  /**
   * 实际参与查询的关键字（2026-10-30 审计 A-M37）。
   *
   * 现场：queryKey 直接塞了 reactive 的 filters，于是每敲一个字都触发一次主查询——
   * 而主查询一次要翻最多 20 页 × 500 行。改成「输入文本 / 已应用关键字」分离后，
   * 键里只剩原始值，且关键字走 400ms 防抖：连续输入只发最后一次。
   */
  const appliedKeyword = ref('')
  const debouncedKeyword = useDebouncedRef(computed(() => filters.keyword), 400)
  watch(debouncedKeyword, (v) => {
    appliedKeyword.value = v
  })

  /** 立即应用当前输入（「查询」按钮 / 回车），不等防抖窗口 */
  function applyFilters() {
    appliedKeyword.value = filters.keyword
  }

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
    /** 查询失败（A-M32）：原先只取 isLoading，失败会落到「暂无批次数据」 */
    isError,
    refetch,
  } = useQuery({
    // 键里只放原始值（A-M37）：reactive 对象进 key 会让输入框每次击键都换 key
    queryKey: [
      'batch-query',
      () => perPage.value,
      () => filters.batch_no,
      () => filters.customer,
      () => filters.status,
      () => appliedKeyword.value,
    ],
    queryFn: async (): Promise<BatchQueryResult> => {
      const base: Record<string, unknown> = {}
      if (filters.batch_no) base.batch_no = filters.batch_no
      if (filters.customer) base.customer = filters.customer
      if (filters.status) base.status = filters.status
      if (appliedKeyword.value) base.keyword = appliedKeyword.value
      // F1a-04（2026-10-24 审计）：分页拉全部——原先单页 500 不翻页不校验
      // total，记录超 500 静默截断，「完成批次」决策基于残缺列表（同类问题
      // 已在 OutsourcePresetTab P1-23 修复，本页漏修）。
      const all: BatchQueryItem[] = []
      let total = 0
      for (let page = 1; page <= BATCH_MAX_PAGES; page += 1) {
        const res = await batchApi.list({ ...base, page, per_page: BATCH_PAGE_SIZE })
        const pageItems = (res.data ?? []) as BatchQueryItem[]
        total = (res as { total?: number }).total ?? total
        all.push(...pageItems)
        if (pageItems.length < BATCH_PAGE_SIZE || (total > 0 && all.length >= total)) {
          return { ...res, data: all, total, truncated: false }
        }
      }
      // 翻满 BATCH_MAX_PAGES 页仍未取完：记 truncated 由页面显式提示，
      // 且 total 保持后端真实总数——伪装成 all.length 会把「还有 N 行没拿到」藏起来。
      return { data: all, total, truncated: true }
    },
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })

  const items = computed<BatchQueryItem[]>(() => result.value?.data ?? [])

  /**
   * 结果是否被翻页上限截断（后端真实总数 > 已拉取行数）。
   *
   * 页面必须据此给出可见提示：静默截断时用户以为「就这么多行」，
   * 会拿残缺列表去做「完成批次」的决策。
   */
  const truncated = computed<boolean>(() => result.value?.truncated === true)

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
      const res = await orderBatchApi.completeBatch({ batch_no: completingBatchNo.value })
      const failed = res?.failed_orders?.length ?? 0
      const done = res?.completed_count ?? 0
      const stockins = res?.completed_stockins ?? 0
      // 后端对「状态不是已出货」的单只塞进 failed_orders，不能一律报「已完成」。
      // 只有备货可归档时 success=true、done=0 但 stockins>0 —— 不能按「状态不符」提示。
      const archived = `已归档 ${done} 单${stockins > 0 ? `、${stockins} 条备货` : ''}`
      if (failed > 0 && (res?.success === false || (done === 0 && stockins === 0))) {
        showToast(`未归档任何订单：${failed} 单状态不符（需先出货）`, 'warning')
      } else if (failed > 0) {
        showToast(`${archived}，另有 ${failed} 单状态不符未归档`, 'warning')
      } else if (res?.success === false) {
        showToast(res.message || '批次完成失败', 'warning')
      } else {
        showToast(stockins > 0 ? `批次已完成，${archived}` : '批次已完成', 'success')
      }
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
    applyFilters,
    result,
    whitelistCustomers,
    allCustomers,
    isLoading,
    isFetching,
    isError,
    refetch,
    truncated,
    truncatedHint: BATCH_TRUNCATED_HINT,
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
