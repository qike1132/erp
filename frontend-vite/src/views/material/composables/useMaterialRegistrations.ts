// 来料进度 / 历史查询的数据加载（Vue Query SWR + 服务端分页 + 数据预处理）
// 方案4：迁移到 @tanstack/vue-query，删除手写 SWR/sessionStorage 缓存（由 persistQueryClient 接管）
// 方案1：Vue Query shallowRef + structural sharing 避免全量重渲染
// 方案5：在预处理阶段格式化 parseFloat，消除模板内反复类型转换
// 方案A改版：分组键改为登记级 supplier_name（item 级字段后端不返回），
// 同单多条登记合并为一行、每条登记一个供应商块；30 天逾期标记与后端 stats/distribution 同口径
import { ref, computed, watch, onUnmounted, type Ref } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { queryClient } from '@/utils/queryClient'
import { materialApi } from '@/api'
import { formatQuantity } from '@/utils/quantity'
import type { Registration, RegItem } from '@/api/material'

/** 逾期判定：登记日期早于今天-30 天且未收齐（与后端 stats/distribution 的 SQL 一致） */
const OVERDUE_DAYS = 30

// 同一供应商 + 同一物料型号合并后的明细行
export interface MergedItem extends RegItem {
  ordered_quantity: number
  received_quantity: number
  progress: number
  /** 预格式化的采购数量字符串（方案5：消除模板内 parseFloat） */
  ordered_display: string
  /** 预格式化的已到货数量字符串 */
  received_display: string
  /** 该物料未收齐且登记超期（30 天口径） */
  overdue: boolean
}

// 按供应商分组的物料行（= 一条登记：登记级 supplier_name）
export interface SupplierGroupRow {
  supplierName: string
  items: MergedItem[]
  /** 组状态：pending 未动 / partial 部分到货（收齐的登记不会出现在进度页） */
  status: 'pending' | 'partial'
  /** 组进度 = 组内已收 / 组内采购 */
  progress: number
  /** 组内存在逾期物料 */
  overdue: boolean
  /** 登记日期（YYYY-MM-DD，逾期判定用） */
  registrationDate: string
}

// 来料进度表格渲染行：一行 = 一个采购订单（同单登记合并）
export interface ProgressOrderRow {
  orderNo: string
  poCreateTime: string
  customerName: string
  productName: string
  skuItems: Array<{ product_name: string; barcode: string; quantity: number | null }>
  /** 订单数量：多 SKU 求和，单 SKU 取 product_quantity */
  productQuantity: number | null
  groups: SupplierGroupRow[]
  /** 行进度 = 各组已收合计 / 各组采购合计（数量加权） */
  progress: number
  /** 行内存在逾期物料 */
  hasOverdue: boolean
  /** 搜索匹配用文本（订单号/客户/产品/供应商/物料名） */
  searchText: string
}

/** 数量格式化：统一走 @/utils/quantity（整数带千分位，小数 ≤2 位） */
function fmtQty(n: number): string {
  return formatQuantity(n)
}

/** 解析登记日期字符串为 UTC 零点 Date（后端序列化为 YYYY-MM-DD） */
function parseUtcDate(s: string | undefined): Date | null {
  if (!s) return null
  const [y, m, d] = s.split('-').map(Number)
  if (!y || !m || !d) return null
  return new Date(Date.UTC(y, m - 1, d))
}

/**
 * 预处理来料进度行：过滤 filling、同单合并、按登记级供应商分组、
 * 同名物料合并、逾期标记、预格式化数量。
 * 纯函数（now 仅用于测试固定时间）。
 */
export function buildProgressOrderRows(rows: Registration[], now: Date = new Date()): ProgressOrderRow[] {
  const cutoff = new Date(now)
  cutoff.setUTCDate(cutoff.getUTCDate() - OVERDUE_DAYS)

  const orderMap = new Map<string, {
    poCreateTime: string
    customerName: string
    productName: string
    skuItems: ProgressOrderRow['skuItems']
    productQuantity: number
    groups: SupplierGroupRow[]
  }>()

  for (const r of rows) {
    const items = (r.items || []).filter((i) => i.material_category !== 'filling')
    const regDate = parseUtcDate(r.registration_date)
    const regOverdue = !!regDate && regDate < cutoff

    // 组内按物料名合并
    const mergedMap = new Map<string, MergedItem>()
    for (const i of items) {
      const ordered = parseFloat(String(i.ordered_quantity || 0))
      const received = parseFloat(String(i.received_quantity || 0))
      const existing = mergedMap.get(i.material_name)
      if (existing) {
        existing.ordered_quantity += ordered
        existing.received_quantity += received
        existing.progress = existing.ordered_quantity > 0
          ? Math.round((existing.received_quantity / existing.ordered_quantity) * 100)
          : 0
        existing.ordered_display = fmtQty(existing.ordered_quantity)
        existing.received_display = fmtQty(existing.received_quantity)
        existing.remaining_quantity = existing.ordered_quantity - existing.received_quantity
        existing.overdue = regOverdue && existing.received_quantity < existing.ordered_quantity
      } else {
        mergedMap.set(i.material_name, {
          ...i,
          ordered_quantity: ordered,
          received_quantity: received,
          progress: ordered > 0 ? Math.round((received / ordered) * 100) : 0,
          ordered_display: fmtQty(ordered),
          received_display: fmtQty(received),
          overdue: regOverdue && received < ordered,
        })
      }
    }
    const mergedItems = Array.from(mergedMap.values())
    const gOrdered = mergedItems.reduce((s, i) => s + i.ordered_quantity, 0)
    const gReceived = mergedItems.reduce((s, i) => s + i.received_quantity, 0)
    const group: SupplierGroupRow = {
      supplierName: r.supplier_name || '未指定',
      items: mergedItems,
      status: gReceived > 0 ? 'partial' : 'pending',
      progress: gOrdered > 0 ? Math.round((gReceived / gOrdered) * 100) : 0,
      overdue: regOverdue && mergedItems.some((i) => i.received_quantity < i.ordered_quantity),
      registrationDate: r.registration_date || '',
    }

    // 同单合并（一行 = 一个采购订单）
    const key = r.purchase_order_no
    let order = orderMap.get(key)
    if (!order) {
      order = {
        poCreateTime: r.po_create_time || '',
        customerName: r.customer_name || '',
        productName: r.product_name || '',
        skuItems: r.sku_items || [],
        productQuantity: 0,
        groups: [],
      }
      orderMap.set(key, order)
    }
    order.groups.push(group)
    order.productQuantity += r.product_quantity || 0
  }

  return Array.from(orderMap, ([orderNo, o]) => {
    const ordered = o.groups.reduce((s, g) => s + g.items.reduce((x, i) => x + i.ordered_quantity, 0), 0)
    const received = o.groups.reduce((s, g) => s + g.items.reduce((x, i) => x + i.received_quantity, 0), 0)
    const searchText = [
      orderNo,
      o.customerName,
      o.productName,
      ...o.groups.map((g) => g.supplierName),
      ...o.groups.flatMap((g) => g.items.map((i) => i.material_name)),
    ].join(' ').toLowerCase()
    return {
      orderNo,
      poCreateTime: o.poCreateTime,
      customerName: o.customerName,
      productName: o.productName,
      skuItems: o.skuItems,
      productQuantity: o.skuItems.length ? o.skuItems.reduce((s, k) => s + (k.quantity || 0), 0) : (o.productQuantity || null),
      groups: o.groups,
      progress: ordered > 0 ? Math.round((received / ordered) * 100) : 0,
      hasOverdue: o.groups.some((g) => g.overdue),
      searchText,
    }
  })
}

/** 客户端搜索：当前页按订单号/客户/产品/供应商/物料名过滤（大小写不敏感） */
export function filterProgressRows(rows: ProgressOrderRow[], keyword: string): ProgressOrderRow[] {
  const kw = keyword.trim().toLowerCase()
  if (!kw) return rows
  return rows.filter((r) => r.searchText.includes(kw))
}

/** 工具条 KPI 四格（对齐后端 stats 接口真实口径） */
export interface ProgressStats {
  /** 进行中登记（partial） */
  inProgress: number
  /** 待收货登记（pending：一件未到） */
  notStarted: number
  /** 逾期物料数（distribution.overdue，30 天口径） */
  overdueItems: number
  /** 总到货率（overall_progress） */
  overallProgress: number
}

export function useMaterialRegistrations(activeTab: Ref<string>) {
  // --- Toast（页面内轻提示） ---
  const toastMsg = ref('')
  const toastType = ref('info')
  const toastIcon = computed(() => ({ success: 'fa-check-circle', error: 'fa-exclamation-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' }[toastType.value] || 'fa-info-circle'))
  let toastTimer: ReturnType<typeof setTimeout> | null = null
  function toast(msg: string, type = 'info') {
    toastMsg.value = msg; toastType.value = type
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { toastMsg.value = '' }, 3000)
  }

  // --- 来料进度状态 ---
  const pPage = ref(1), pPerPage = ref(20)
  const searchKeyword = ref('')

  const progressQuery = useQuery({
    queryKey: computed(() => ['material', 'progress', pPage.value, pPerPage.value] as const),
    queryFn: () => materialApi.registrations({ page: pPage.value, per_page: pPerPage.value, exclude_completed: true }),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })

  watch(() => progressQuery.error.value, (err) => { if (err) toast('加载失败', 'error') })

  const progressRows = computed<Registration[]>(() => progressQuery.data.value?.registrations || [])
  const progressOrderRows = computed<ProgressOrderRow[]>(() => buildProgressOrderRows(progressRows.value))
  /** 客户端搜索（当前页）过滤后的行；搜索有词且无命中时表格渲染专属空态 */
  const filteredOrderRows = computed<ProgressOrderRow[]>(() => filterProgressRows(progressOrderRows.value, searchKeyword.value))
  const showSearchEmpty = computed(() => !!searchKeyword.value.trim() && progressOrderRows.value.length > 0 && filteredOrderRows.value.length === 0)
  const pPages = computed(() => progressQuery.data.value?.pages ?? progressQuery.data.value?.total_pages ?? 1)
  const pIsLoading = computed(() => progressQuery.isLoading.value)
  const pIsFetching = computed(() => progressQuery.isFetching.value && !progressQuery.isLoading.value)
  const progressCount = computed(() => progressQuery.data.value?.total ?? 0)

  // --- KPI 统计（进度 tab 专属：后端 stats 接口，带缓存） ---
  const overviewQuery = useQuery({
    queryKey: ['material', 'stats-overview'],
    queryFn: () => materialApi.overview(),
    enabled: computed(() => activeTab.value === 'progress'),
    staleTime: 60_000,
  })
  const distributionQuery = useQuery({
    queryKey: ['material', 'stats-distribution'],
    queryFn: () => materialApi.distribution(),
    enabled: computed(() => activeTab.value === 'progress'),
    staleTime: 60_000,
  })
  const stats = computed<ProgressStats>(() => {
    const o = overviewQuery.data.value
    const dist = distributionQuery.data.value?.distribution || []
    return {
      inProgress: o?.partial ?? 0,
      notStarted: o?.pending ?? 0,
      overdueItems: dist.find((d) => d.status === 'overdue')?.count ?? 0,
      overallProgress: Math.round(o?.overall_progress ?? 0),
    }
  })

  // --- 历史查询状态（延迟加载：仅当切换到 history tab 时才发起请求） ---
  const hPage = ref(1), hPerPage = ref(20)

  const historyQuery = useQuery({
    queryKey: computed(() => ['material', 'history', hPage.value, hPerPage.value] as const),
    queryFn: () => materialApi.history({ page: hPage.value, per_page: hPerPage.value }),
    enabled: computed(() => activeTab.value === 'history'),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })

  watch(() => historyQuery.error.value, (err) => { if (err) toast('加载失败', 'error') })

  const hRegistrations = computed<Registration[]>(() => historyQuery.data.value?.registrations || [])
  const hPages = computed(() => historyQuery.data.value?.pages ?? historyQuery.data.value?.total_pages ?? 1)
  const hIsLoading = computed(() => historyQuery.isLoading.value)
  const hIsFetching = computed(() => historyQuery.isFetching.value && !historyQuery.isLoading.value)

  /** 收货后强制刷新来料进度与 KPI（收货会改 overview/distribution，一并失效） */
  function loadProgress(page?: number) {
    if (page) pPage.value = page
    queryClient.invalidateQueries({ queryKey: ['material'] })
  }

  /** 刷新历史查询 */
  function loadHistory(page?: number) {
    if (page) hPage.value = page
    queryClient.invalidateQueries({ queryKey: ['material', 'history'] })
  }

  /** Vue Query 自动加载，保留空函数兼容调用方 */
  function ensureProgressLoaded() { /* no-op: useQuery 自动执行 */ }
  function ensureHistoryLoaded() { /* no-op: useQuery 自动执行 */ }

  /** UiDataTable 分页变化处理（PrimeVue page 为 0 索引） */
  function onProgressPageChange({ page, rows }: { page: number; rows: number }) {
    pPerPage.value = rows
    pPage.value = page + 1
  }
  function onHistoryPageChange({ page, rows }: { page: number; rows: number }) {
    hPerPage.value = rows
    hPage.value = page + 1
  }

  onUnmounted(() => {
    if (toastTimer) clearTimeout(toastTimer)
  })

  return {
    toastMsg, toastType, toastIcon, toast,
    pPage, pPerPage, pPages, pIsLoading, pIsFetching, progressRows, progressCount,
    progressOrderRows, filteredOrderRows, showSearchEmpty, searchKeyword, stats,
    hPage, hPerPage, hPages, hIsLoading, hIsFetching, hRegistrations,
    loadProgress, loadHistory, ensureProgressLoaded, ensureHistoryLoaded,
    onProgressPageChange, onHistoryPageChange,
  }
}
