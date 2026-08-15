/**
 * useBeileOrders.ts — 湖北订单列表数据逻辑
 *
 * 从 BeileOrderTab.vue 下沉的逻辑：查询（vue-query）、筛选、分页、
 * 确认状态切换、订单确认（乐观更新）与详情弹窗状态。
 */
import { reactive, computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { orderApi } from '@/api'
import type { OrderItem, OrderSKU } from '@/types'
import type { OrderListApiResponse } from '@/api/order'
import { toast } from '@/composables/useToast'

/** 每页条数选项（分页组件下拉可选） */
export const PAGE_SIZE_OPTIONS = [18, 30, 50, 100]

/** 湖北订单行：OrderItem 在后端实际响应中还包含 order_no / customer / product（未在 OrderItem 类型中声明） */
export type BeileOrderRow = OrderItem & {
  order_no?: string
  customer?: string
  record_type?: 'order' | 'stockin'
  factories?: string[]
  /** 后端 beile-list 返回的首个 SKU 产品图路径 */
  product_image?: string | null
  /** 湖北订单确认状态：confirmed=false 即「未确认订单」 */
  confirmed?: boolean
  confirmed_at?: string
  confirmed_by?: string
  product?: { id: number; name: string; barcode: string; image: string }
}

/** 湖北订单列表：查询 + 筛选 + 分页 + 确认流程 */
export function useBeileOrders() {
  /** 当前每页条数，可由分页组件修改 */
  const perPage = ref(18)

  /**
   * 输入文本与已应用筛选分离：
   * - filters.orderNo / filters.customer = 输入框显示文本（用户自由键入，不触发筛选）
   * - appliedProduct / appliedCustomer = 已确认的筛选值（选择建议 / 点击查询后生效）
   */
  const filters = reactive({ orderNo: '', customer: '' })
  const appliedProduct = ref('')
  const appliedCustomer = ref('')

  /** 确认状态筛选：unconfirmed=未确认 / confirmed=已确认（默认未确认，湖北订单确认流程） */
  const confirmStatus = ref('unconfirmed')

  const page = ref(1)

  const currentPage = computed(() => page.value)

  const {
    data: ordersData,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    /** 湖北订单列表查询 key：随筛选/分页变化（乐观更新时复用同一 key） */
    queryKey: ['beile-orders', appliedCustomer, confirmStatus, () => page.value, () => perPage.value],
    queryFn: () =>
      orderApi.beileList({
        customer: appliedCustomer.value || undefined,
        confirm_status: confirmStatus.value || undefined,
        page: page.value,
        per_page: perPage.value,
      }),
    staleTime: 30_000,
    gcTime: 60_000,
    // 定时刷新：新到湖北订单（未确认提醒横幅）无需手动刷新即可出现
    refetchInterval: 30_000,
    placeholderData: keepPreviousData,
  })

  /** 服务端返回的订单列表（已应用 customer 筛选与分页） */
  const orders = computed<BeileOrderRow[]>(() => (ordersData.value?.data ?? []) as BeileOrderRow[])
  const totalItems = computed(() => ordersData.value?.total ?? 0)
  const totalPages = computed(() => Math.max(1, Math.ceil(totalItems.value / perPage.value)))

  /** 湖北订单确认流程：未确认订单总数（全局，列表顶部横幅用） */
  const unconfirmedCount = computed(() => ordersData.value?.unconfirmed_count ?? 0)

  /** 搜索产品时是否显示产品名称列：仅当已应用产品关键字筛选时显示 */
  const showProductColumn = computed(() => appliedProduct.value.trim() !== '')

  /** SKU 是否匹配关键字（产品名称或条码） */
  function skuMatchesKeyword(sku: { product_name?: string | null; product_barcode?: string | null }, kw: string): boolean {
    return (sku.product_name || '').toLowerCase().includes(kw)
      || (sku.product_barcode || '').toLowerCase().includes(kw)
  }

  /**
   * 行内展示的 SKU：应用产品筛选时仅返回名称/条码匹配关键字的 SKU，
   * 使产品名称、数量、备注只对应搜索到的那个产品；未筛选时返回全部。
   */
  function visibleSkus(item: BeileOrderRow): NonNullable<BeileOrderRow['items']> {
    const kw = appliedProduct.value.trim().toLowerCase()
    if (!kw) return item.items || []
    const matched = (item.items || []).filter((s) => skuMatchesKeyword(s, kw))
    return matched.length > 0 ? matched : (item.items || [])
  }

  /**
   * 客户端二次过滤：当前页订单中 product_name/barcode 模糊匹配。
   * 仅当 appliedProduct 有值时才过滤（选择建议或点击查询后生效），
   * 自由键入不触发过滤，避免输入中途表格发生抖动。
   * 匹配任一 SKU（名称或条码），而不只是订单首个产品。
   */
  const displayOrders = computed<BeileOrderRow[]>(() => {
    const kw = appliedProduct.value.trim().toLowerCase()
    if (!kw) return orders.value
    return orders.value.filter((o) => {
      if ((o.product_name || '').toLowerCase().includes(kw)) return true
      return (o.items || []).some((s) => skuMatchesKeyword(s, kw))
    })
  })

  /** URL order_id 参数：高亮对应订单行（通知点击跳转场景） */
  const route = useRoute()
  const highlightId = computed<string | null>(() => {
    const oid = route.query.order_id
    return oid ? String(oid) : null
  })

  /** 由父组件在用户点击自动补全候选项时调用 */
  function applyProductFilter(name: string) {
    appliedProduct.value = name
  }

  /** 由父组件在用户点击客户候选项时调用 */
  function applyCustomerFilter(name: string) {
    appliedCustomer.value = name
  }

  function handleSearch() {
    // 点击查询按钮：将输入框当前文本确认为筛选值
    appliedProduct.value = filters.orderNo
    appliedCustomer.value = filters.customer
    refetch()
  }

  function handleReset() {
    filters.orderNo = ''
    filters.customer = ''
    appliedProduct.value = ''
    appliedCustomer.value = ''
    page.value = 1
    refetch()
  }

  function goPage(p: number) {
    page.value = p
  }

  /** 切换确认状态筛选并回到第一页 */
  function setConfirmStatus(v: string) {
    confirmStatus.value = v
    page.value = 1
  }

  /** 订单详情弹窗状态 */
  const detailOpen = ref(false)
  const detailData = ref<BeileOrderRow | null>(null)

  function openDetail(item: BeileOrderRow) {
    detailData.value = item
    detailOpen.value = true
  }

  /** 确认中订单 id 集合（防止重复点击，按钮禁用态依赖） */
  const confirmingIds = ref<Set<number>>(new Set())

  const queryClient = useQueryClient()

  /** 当前查询 key（乐观更新 setQueryData 复用） */
  const queryKey = computed(() =>
    ['beile-orders', appliedCustomer.value, confirmStatus.value, page.value, perPage.value] as const,
  )

  /**
   * 确认湖北订单：仅未确认的订单记录可见按钮，确认后由后端落库
   * confirmed_at。在「未确认」筛选下成功后立即从列表移除该行并递减
   * 未确认计数，无需等待 30s 定时刷新；其他筛选下照常 refetch。
   */
  async function handleConfirm(item: BeileOrderRow) {
    if (item.record_type !== 'order' || item.confirmed) return
    if (confirmingIds.value.has(item.id)) return
    confirmingIds.value.add(item.id)
    try {
      const res = await orderApi.confirmBeileOrder(item.id)
      toast.success(res.message || '订单已确认')
      if (confirmStatus.value === 'unconfirmed') {
        queryClient.setQueryData<OrderListApiResponse>(queryKey.value, (old) => {
          if (!old) return old
          const data = (old.data || []).filter((o) => o.id !== item.id)
          return {
            ...old,
            data,
            total: Math.max(0, (old.total ?? 0) - 1),
            unconfirmed_count: Math.max(0, (old.unconfirmed_count ?? 0) - 1),
          }
        })
        // 当前页被清空且不是第一页时回退一页
        if (orders.value.length === 0 && page.value > 1) {
          page.value -= 1
        }
      } else {
        await refetch()
      }
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || '确认订单失败')
    } finally {
      confirmingIds.value.delete(item.id)
    }
  }

  // 已确认的客户筛选变化时回到首页
  watch(() => appliedCustomer.value, () => {
    page.value = 1
  })

  // 每页条数变化时回到第一页
  watch(perPage, () => {
    page.value = 1
  })

  return {
    PAGE_SIZE_OPTIONS,
    perPage,
    filters,
    appliedProduct,
    appliedCustomer,
    confirmStatus,
    page,
    currentPage,
    totalItems,
    totalPages,
    isLoading,
    isFetching,
    refetch,
    orders,
    unconfirmedCount,
    showProductColumn,
    visibleSkus,
    displayOrders,
    highlightId,
    applyProductFilter,
    applyCustomerFilter,
    handleSearch,
    handleReset,
    goPage,
    setConfirmStatus,
    detailOpen,
    detailData,
    openDetail,
    confirmingIds,
    handleConfirm,
  }
}
