/**
 * useOutsourceOrders.ts — 湖北外发订单列表数据逻辑
 *
 * 从 OutsourceOrderTab.vue 下沉的列表逻辑：
 * 查询（vue-query）、产品/客户筛选（客户端二次过滤）、分页。
 */
import { computed, ref, watch } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { outsourceApi } from '@/api/outsource'
import type { OrderItem, OrderSKU } from '@/types'

/** 每页条数选项（分页组件下拉可选） */
export const PAGE_SIZE_OPTIONS = [18, 30, 50, 100]

/** 湖北外发订单行：与 beile-list 返回结构一致 + 后端附加的进度统计 */
export type OutsourceOrderRow = OrderItem & {
  order_no?: string
  customer?: string
  record_type?: 'order' | 'stockin'
  factories?: string[]
  items?: OrderSKU[]
  total_processes?: number
  completed_processes?: number
  progress?: number
  current_process?: string | null
  status_label?: string
}

/**
 * 湖北外发订单列表：查询 + 筛选 + 分页。
 * @param props 父组件的响应式 props（productFilter / customerFilter 由头部搜索栏确认后传入）
 */
export function useOutsourceOrders(props: { productFilter: string; customerFilter: string }) {
  /** 当前每页条数，可由分页组件修改 */
  const perPage = ref(18)
  const page = ref(1)
  const currentPage = computed(() => page.value)

  /** 已应用的产品/客户筛选值（由父组件 props 同步而来） */
  const appliedProduct = ref(props.productFilter)
  const appliedCustomer = ref(props.customerFilter)

  watch(() => props.productFilter, (v) => { appliedProduct.value = v })
  watch(() => props.customerFilter, (v) => { appliedCustomer.value = v; page.value = 1 })

  const {
    data: ordersData,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    queryKey: ['outsource-orders', appliedCustomer, () => page.value, () => perPage.value],
    queryFn: () =>
      outsourceApi.orders({
        customer: appliedCustomer.value || undefined,
        page: page.value,
        per_page: perPage.value,
      }),
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
  })

  /** 服务端返回的订单列表 */
  const orders = computed<OutsourceOrderRow[]>(() => (ordersData.value?.data ?? []) as OutsourceOrderRow[])
  const totalItems = computed(() => ordersData.value?.total ?? 0)
  const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage.value)))

  /** SKU 是否匹配关键字（产品名称或条码） */
  function skuMatchesKeyword(sku: { product_name?: string | null; product_barcode?: string | null }, kw: string): boolean {
    return (sku.product_name || '').toLowerCase().includes(kw)
      || (sku.product_barcode || '').toLowerCase().includes(kw)
  }

  /** 行内展示的 SKU：有工序时仅展示有工序的 SKU，再叠加产品关键字二次过滤 */
  function visibleSkus(item: OutsourceOrderRow): OrderSKU[] {
    const items = item.items || []
    const kw = appliedProduct.value.trim().toLowerCase()

    // 订单有外发工序时，只展示有工序的 SKU
    let result = items
    if ((item.total_processes || 0) > 0) {
      result = items.filter((s) => s.has_processes === true)
    }

    // 产品关键字二次过滤
    if (kw) {
      const matched = result.filter((s) => skuMatchesKeyword(s, kw))
      if (matched.length > 0) return matched
    }
    return result
  }

  /** 客户端二次过滤：产品名或任一 SKU 名称/条码匹配关键字 */
  const displayOrders = computed<OutsourceOrderRow[]>(() => {
    const kw = appliedProduct.value.trim().toLowerCase()
    if (!kw) return orders.value
    return orders.value.filter((o) => {
      if ((o.product_name || '').toLowerCase().includes(kw)) return true
      return (o.items || []).some((s) => skuMatchesKeyword(s, kw))
    })
  })

  /** 行内数量合计：优先按可见 SKU 汇总，无 SKU 时用订单总量 */
  function totalQuantity(item: OutsourceOrderRow): number {
    const skus = visibleSkus(item)
    if (skus.length > 0) return skus.reduce((sum, s) => sum + (s.quantity || 0), 0)
    return item.quantity || 0
  }

  /** 跳转页码 */
  function goPage(p: number) {
    page.value = p
  }

  // 每页条数变化时回到第一页
  watch(perPage, () => { page.value = 1 })

  return {
    PAGE_SIZE_OPTIONS,
    perPage,
    page,
    currentPage,
    appliedProduct,
    appliedCustomer,
    isLoading,
    isFetching,
    refetch,
    orders,
    totalItems,
    totalPages,
    visibleSkus,
    displayOrders,
    totalQuantity,
    goPage,
  }
}
