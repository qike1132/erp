/**
 * useBeileOrders.ts — 湖北订单列表数据逻辑
 *
 * 从 BeileOrderTab.vue 下沉的逻辑：查询（vue-query）、筛选、分页、
 * 确认状态切换、订单确认（乐观更新）、详情弹窗状态、
 * 选中/导出/打印（原 BeileOrderTab 头部桥接逻辑上提至此）。
 *
 * HubeiView 调用 provideBeileOrders() 创建唯一实例并 provide，
 * BeileOrderTab 通过 injectBeileOrders() 注入同一实例，
 * 消除 ref 反向桥接导致的父子联动重渲染。
 */
import { reactive, computed, ref, watch, provide, inject, type InjectionKey } from 'vue'
import { useRoute } from 'vue-router'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { orderApi } from '@/api'
import type { OrderItem } from '@/types'
import type { OrderListApiResponse } from '@/api/order'
import { toast } from '@/composables/useToast'
import { useAuthStore } from '@/stores/auth'
import { useExport } from '@/composables/useExport'
import { downloadXls } from '@/utils/xls'
import { printHtml } from '@/utils/print'

/** 每页条数选项（分页组件下拉可选） */
export const PAGE_SIZE_OPTIONS = [18, 30, 50, 100]

/** 湖北订单行：OrderItem 在后端实际响应中还包含 order_no / customer / product（未在 OrderItem 类型中声明） */
export type BeileOrderRow = OrderItem & {
  order_no?: string
  customer?: string
  record_type?: 'order' | 'stockin'
  factories?: string[]
  /** 湖北订单确认状态：confirmed=false 即「未确认订单」 */
  confirmed?: boolean
  confirmed_at?: string
  confirmed_by?: string
  product?: { id: number; name: string; barcode: string; image: string }
}

/** SKU 是否匹配关键字（产品名称或条码） */
export function skuMatchesKeyword(sku: { product_name?: string | null; product_barcode?: string | null }, kw: string): boolean {
  return (sku.product_name || '').toLowerCase().includes(kw)
    || (sku.product_barcode || '').toLowerCase().includes(kw)
}

/**
 * 列表行唯一键：订单与备货来自不同表，id 可能撞号，
 * 选中集 / 确认中集合 / 虚拟列表 key 必须用 record_type:id 组合键。
 */
export function rowKey(item: Pick<BeileOrderRow, 'id' | 'record_type'>): string {
  return `${item.record_type ?? 'order'}:${item.id}`
}

/** 湖北订单列表：查询 + 筛选 + 分页 + 确认流程 + 选中/导出/打印 */
export function useBeileOrders() {
  /** 当前每页条数，可由分页组件修改 */
  const perPage = ref(18)

  /**
   * 输入文本与已应用筛选分离：
   * - filters.productKw / filters.customer = 输入框显示文本（用户自由键入，不触发筛选）
   * - appliedProduct / appliedCustomer = 已确认的筛选值（选择建议 / 重置后生效）
   */
  const filters = reactive({ productKw: '', customer: '' })
  const appliedProduct = ref('')
  const appliedCustomer = ref('')

  /** 确认状态筛选：unconfirmed=未确认 / confirmed=已确认（默认未确认） */
  const confirmStatus = ref('unconfirmed')

  const page = ref(1)

  const currentPage = computed(() => page.value)

  /** 当前查询 key：useQuery 与乐观更新 setQueryData 共用，避免双写导致缓存 miss */
  const queryKey = computed(() =>
    ['beile-orders', appliedCustomer.value, appliedProduct.value, confirmStatus.value, page.value, perPage.value] as const,
  )

  const {
    data: ordersData,
    isLoading,
    isFetching,
    refetch,
  } = useQuery({
    /** 湖北订单列表查询 key：随筛选/分页变化（乐观更新时复用同一 key） */
    queryKey,
    queryFn: () =>
      orderApi.beileList({
        customer: appliedCustomer.value || undefined,
        product: appliedProduct.value || undefined,
        confirm_status: confirmStatus.value || undefined,
        page: page.value,
        per_page: perPage.value,
      }),
    staleTime: 30_000,
    gcTime: 60_000,
    // 不再使用 refetchInterval 定时刷新（会在用户交互时打断渲染）；
    // 依赖 vue-query 默认的 refetchOnWindowFocus + staleTime，仅在页面重新可见且数据过期时刷新。
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

  /**
   * 产品关键字筛选已下沉到服务端（beile-list 的 product 参数），
   * 此处不再做客户端二次过滤，避免「先分页后过滤」漏掉后续页命中数据。
   */
  const displayOrders = computed<BeileOrderRow[]>(() => orders.value)

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

  function handleReset() {
    filters.productKw = ''
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

  /** 确认中记录键集合（rowKey，防止重复点击，按钮禁用态依赖） */
  const confirmingIds = ref<Set<string>>(new Set())

  const queryClient = useQueryClient()

  /**
   * 确认湖北订单/备货：未确认的订单与备货记录均显示确认按钮，
   * 确认后由后端落库 confirmed_at。在「未确认」筛选下成功后立即
   * 从列表移除该行并递减未确认计数，无需等待定时刷新；
   * 其他筛选下照常 refetch。
   */
  async function handleConfirm(item: BeileOrderRow) {
    if (item.confirmed) return
    const key = rowKey(item)
    if (confirmingIds.value.has(key)) return
    confirmingIds.value.add(key)
    try {
      const isStockin = item.record_type === 'stockin'
      const res = isStockin
        ? await orderApi.confirmBeileStockin(item.id)
        : await orderApi.confirmBeileOrder(item.id)
      toast.success(res.message || (isStockin ? '备货已确认' : '订单已确认'))
      if (confirmStatus.value === 'unconfirmed') {
        queryClient.setQueryData<OrderListApiResponse>(queryKey.value, (old) => {
          if (!old) return old
          // 订单与备货来自不同表，id 可能撞号，需同时匹配 record_type
          const data = ((old.data || []) as BeileOrderRow[]).filter((o) => !(o.id === item.id && o.record_type === item.record_type))
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
      toast.error(msg || '确认失败')
    } finally {
      confirmingIds.value.delete(key)
    }
  }

  // ==================== 选中（批量打印） ====================
  /** 选中的记录键集合（rowKey：record_type:id，订单与备货 id 可能撞号） */
  const selectedIds = ref<Set<string>>(new Set())
  const selectedCount = computed(() => selectedIds.value.size)

  /** 当前展示列表是否有数据（导出按钮启用条件） */
  const hasDisplayOrders = computed(() => displayOrders.value.length > 0)

  /** 当前页是否全选 */
  const isAllSelected = computed(() =>
    displayOrders.value.length > 0 && displayOrders.value.every((o) => selectedIds.value.has(rowKey(o))),
  )

  /** 切换单行选中（直接 mutate reactive Set，避免 O(n) 拷贝） */
  function toggleSelect(key: string) {
    if (selectedIds.value.has(key)) selectedIds.value.delete(key)
    else selectedIds.value.add(key)
  }

  /** 全选 / 取消全选当前页 */
  function toggleSelectAll(checked: boolean) {
    if (checked) {
      displayOrders.value.forEach((o) => selectedIds.value.add(rowKey(o)))
    } else {
      displayOrders.value.forEach((o) => selectedIds.value.delete(rowKey(o)))
    }
  }

  // ==================== 导出 / 打印 ====================
  const authStore = useAuthStore()
  const { exporting, runExport } = useExport()

  /** 权限：导出 / 打印（超级管理员自动放行） */
  const canExport = computed(() => authStore.hasPermission('beile_order_export'))
  const canPrint = computed(() => authStore.hasPermission('beile_order_print'))

  /** 汇总表列头（含产品明细） */
  const SUMMARY_HEADERS = [
    '订单类型', '下单时间', '客户名称', '工厂', '产品名称', '数量', '备注',
  ]

  /** 汇总表各列宽度（px），用于导出 XLS 列宽分配 */
  const SUMMARY_COL_WIDTHS = [90, 120, 130, 80, 220, 80, 180]

  /** HTML 特殊字符转义 */
  function escapeHtml(str: string): string {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  }

  /**
   * 构建汇总表 tbody HTML。
   * 同一订单的订单类型/下单时间/客户名称/工厂列用 rowspan 合并单元格，
   * 产品名称/数量/备注每行独立输出。
   */
  function buildSummaryTbody(items: BeileOrderRow[]): string {
    let html = ''
    for (const item of items) {
      const type = item.record_type === 'stockin' ? '备货' : '订单'
      const factory = (item.factories || ['湖北']).join(', ')
      const orderCells = [type, item.order_date || '', item.customer || '', factory]
      const note = item.note || ''

      const skus = (item.items && item.items.length > 0)
        ? item.items
        : [{ product_name: item.product_name, quantity: item.quantity }]

      const rowspan = skus.length
      skus.forEach((sku, idx) => {
        const cells: string[] = []
        if (idx === 0) {
          for (const c of orderCells) {
            cells.push(`<td${rowspan > 1 ? ` rowspan="${rowspan}"` : ''}>${escapeHtml(c)}</td>`)
          }
        }
        cells.push(`<td>${escapeHtml(sku.product_name || '-')}</td>`)
        cells.push(`<td>${escapeHtml(String(sku.quantity || 0))}</td>`)
        cells.push(`<td>${idx === 0 ? escapeHtml(note) : ''}</td>`)
        html += `<tr>${cells.join('')}</tr>`
      })
    }
    return html
  }

  /**
   * 按产品关键字裁剪 SKU 明细：产品搜索生效时，导出/打印仅保留
   * 匹配关键字的 SKU 行（同一订单内未命中的产品不输出）。
   * 仅订单级 product_name 命中或无明细的订单保持原样
   * （buildSummaryTbody 对空明细回退为单行 product_name）。
   */
  function filterSkusByKeyword(list: BeileOrderRow[]): BeileOrderRow[] {
    const kw = appliedProduct.value.trim().toLowerCase()
    if (!kw) return list
    return list.map((o) => {
      const original = o.items || []
      if (original.length === 0) return o
      const items = original.filter((s) => skuMatchesKeyword(s, kw))
      // 全部命中复用原对象；过滤后可能为空 → 置空明细，
      // 由 buildSummaryTbody 回退为订单级 product_name 单行
      if (items.length === original.length) return o
      return { ...o, items }
    })
  }

  /** 导出当前页数据为 XLS */
  function handleExport() {
    runExport(() => {
      const thead = `<tr>${SUMMARY_HEADERS.map((h, i) => `<th style="width:${SUMMARY_COL_WIDTHS[i]}px">${h}</th>`).join('')}</tr>`
      const tbody = buildSummaryTbody(filterSkusByKeyword(displayOrders.value))
      const statusLabel = confirmStatus.value === 'unconfirmed' ? '未确认' : '已确认'
      const title = `湖北订单汇总（${statusLabel}）`
      const html = `<div style="text-align:center;margin-bottom:20px;"><h2>${title}</h2></div><table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`
      const date = new Date().toISOString().slice(0, 10)
      downloadXls(html, `湖北订单_${statusLabel}_${date}.xls`)
    })
  }

  /** 批量打印选中订单汇总表 */
  function handlePrint() {
    const targets = displayOrders.value.filter((o) => selectedIds.value.has(rowKey(o)))
    if (targets.length === 0) {
      toast.warning('请先勾选要打印的订单')
      return
    }
    const thead = `<tr>${SUMMARY_HEADERS.map((h) => `<th>${escapeHtml(h)}</th>`).join('')}</tr>`
    const tbody = buildSummaryTbody(filterSkusByKeyword(targets))
    const printStyle = `
      body { font-family: SimSun, 宋体; padding: 20px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { border: 1px solid #333; padding: 8px; font-size: 13px; text-align: center; }
      th { background: #e6e6e6; }
    `
    printHtml(`湖北订单汇总（${targets.length} 条）`, `<table><thead>${thead}</thead><tbody>${tbody}</tbody></table>`, printStyle)
    toast.success(`已发送 ${targets.length} 条订单至打印预览`)
  }

  // ==================== watchers ====================
  // 已确认的客户筛选变化时回到首页
  watch(() => appliedCustomer.value, () => {
    page.value = 1
  })

  // 产品关键字筛选变化时回到首页（服务端过滤，需复位分页避免越界空页）
  watch(() => appliedProduct.value, () => {
    page.value = 1
  })

  // 每页条数变化时回到第一页
  watch(perPage, () => {
    page.value = 1
  })

  // 翻页 / 筛选变化时清空选中（滚动归位由 BeileOrderTab 处理）
  watch([page, appliedProduct, appliedCustomer, confirmStatus], () => {
    selectedIds.value = new Set()
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
    displayOrders,
    highlightId,
    applyProductFilter,
    handleReset,
    goPage,
    setConfirmStatus,
    detailOpen,
    detailData,
    openDetail,
    confirmingIds,
    handleConfirm,
    // 选中
    selectedIds,
    selectedCount,
    hasDisplayOrders,
    isAllSelected,
    toggleSelect,
    toggleSelectAll,
    // 导出 / 打印
    canExport,
    canPrint,
    exporting,
    handleExport,
    handlePrint,
  }
}

// ==================== provide/inject：HubeiView 与 BeileOrderTab 共享同一状态实例 ====================
export type BeileOrdersHandle = ReturnType<typeof useBeileOrders>
export const BEILE_ORDERS_KEY: InjectionKey<BeileOrdersHandle> = Symbol('beile-orders')

/** 在父组件（HubeiView）调用：创建状态实例并 provide 给子组件 */
export function provideBeileOrders(): BeileOrdersHandle {
  const bo = useBeileOrders()
  provide(BEILE_ORDERS_KEY, bo)
  return bo
}

/** 在子组件（BeileOrderTab）调用：注入父组件 provide 的状态实例 */
export function injectBeileOrders(): BeileOrdersHandle {
  const bo = inject(BEILE_ORDERS_KEY)
  if (!bo) throw new Error('injectBeileOrders 必须在调用了 provideBeileOrders 的组件树内使用')
  return bo
}
