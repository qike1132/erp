import { ref, reactive, computed, watch, onScopeDispose } from 'vue'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/vue-query'
import { purchaseApi, type CompletedOrderExportRow } from '@/api'
import { showToast } from '@/composables/useToast'
import { getErrorMessage } from '@/types/errors'
import type { PurchaseOrder } from '@/types'
import { escapeHtml } from '@/utils/print'
import { downloadXls } from '@/utils/xls'

/** Vue Query 缓存 key */
export const COMPLETED_ORDERS_QUERY_KEY = 'completed-orders-list'

/** 每页条数（后端 per_page 上限 200，2026-10-31 评审 M-2 已从 500 收紧） */
const PER_PAGE = 20

export interface CompletedOrderFilters {
  product_name: string
}

const FILTER_KEYS = ['product_name'] as const

/** 把筛选条件拼成接口参数（查询与导出共用，避免两处重复） */
function buildParams(filters: CompletedOrderFilters, page?: number): Record<string, string | number> {
  const params: Record<string, string | number> = {}
  if (page != null) {
    params.page = page
    params.per_page = PER_PAGE
  }
  for (const key of FILTER_KEYS) {
    const value = filters[key]
    if (value) params[key] = value
  }
  return params
}

/** 导出列定义：数组顺序即表头顺序，key 对应后端导出行的字段 */
const EXPORT_COLUMNS: readonly { header: string; key: keyof CompletedOrderExportRow }[] = [
  { header: '完成日期', key: 'completed_at' },
  { header: '订单号', key: 'order_no' },
  { header: '客户', key: 'customer_name' },
  { header: '供应商', key: 'supplier_name' },
  { header: '材料名称', key: 'material_name' },
  { header: '材料编码', key: 'material_code' },
  { header: '规格型号', key: 'specification' },
  { header: '数量', key: 'quantity' },
  { header: '单位', key: 'unit' },
  { header: '单价', key: 'unit_price' },
  { header: '金额', key: 'amount' },
]

/**
 * 单元格取值。
 * 数字保留数值形态（Excel 可直接求和/排序），并收敛浮点尾差；空值输出空串。
 */
function toCellText(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(Number(value.toFixed(3))) : ''
  }
  return String(value)
}

/** 把导出明细拼成 downloadXls 所需的 <table> HTML（单元格逐一转义） */
function buildExportTable(rows: CompletedOrderExportRow[]): string {
  const head = EXPORT_COLUMNS.map((col) => '<th>' + escapeHtml(col.header) + '</th>').join('')
  const body = rows
    .map((row) => {
      const cells = EXPORT_COLUMNS.map((col) => '<td>' + escapeHtml(toCellText(row[col.key])) + '</td>').join('')
      return '<tr>' + cells + '</tr>'
    })
    .join('')
  return '<table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>'
}

/**
 * useCompletedOrders — 记录查询数据层
 *
 * 只做三件事：搜索/查询（filters + page → 列表）、导出、重置。
 * 查询为显式提交（点"查询"或回车），不做输入即请求，避免每键一次请求。
 */
export function useCompletedOrders() {
  const queryClient = useQueryClient()
  const page = ref(1)

  /** 已提交的筛选条件（真正参与请求） */
  const filters = reactive<CompletedOrderFilters>({
    product_name: '',
  })

  /** 表单草稿：用户编辑中，点"查询"才写入 filters */
  const draft = reactive<CompletedOrderFilters>({ ...filters })

  /** 草稿与已提交条件是否有差异（用于"查询"按钮的强调态） */
  const isDirty = computed(() => FILTER_KEYS.some((k) => draft[k] !== filters[k]))

  /** 是否处于筛选状态（用于空状态文案与重置按钮可用性） */
  const hasFilter = computed(() => FILTER_KEYS.some((k) => !!filters[k]))

  /**
   * 查询 key：已提交条件 + 页码。
   * 必须用 computed 逐项读取，否则 {...filters} 在 setup 时就固化成快照，
   * 点「查询」改了条件也不会重新请求。
   */
  const queryKey = computed(() => [
    COMPLETED_ORDERS_QUERY_KEY,
    page.value,
    ...FILTER_KEYS.map((key) => filters[key]),
  ])

  const { data, isLoading, isFetching, isError } = useQuery({
    queryKey,
    queryFn: async () => {
      try {
        return await purchaseApi.completed(buildParams(filters, page.value))
      } catch (err) {
        showToast(getErrorMessage(err, '加载已完成订单失败'), 'error')
        throw err
      }
    },
    staleTime: 30_000,
    gcTime: 60_000,
    placeholderData: keepPreviousData,
    retry: false,
  })

  // 加载超时兜底：后端挂住时 20s 强制转错误态，保证加载状态必定结束
  const loadingTimedOut = ref(false)
  let loadingTimer: ReturnType<typeof setTimeout> | null = null
  watch([isLoading, isError], () => {
    if (loadingTimer) {
      clearTimeout(loadingTimer)
      loadingTimer = null
    }
    loadingTimedOut.value = false
    if (isLoading.value && !isError.value) {
      loadingTimer = setTimeout(() => {
        loadingTimedOut.value = true
      }, 20_000)
    }
  }, { immediate: true })
  onScopeDispose(() => {
    if (loadingTimer) clearTimeout(loadingTimer)
  })

  const orders = computed<PurchaseOrder[]>(() => data.value?.orders ?? [])
  const total = computed(() => data.value?.total ?? 0)
  const totalPages = computed(() => data.value?.total_pages ?? data.value?.pages ?? 1)
  const error = computed(() => isError.value || loadingTimedOut.value)

  /** 查询：把草稿提交为生效条件并回到第 1 页（queryKey 变化自动请求） */
  function search() {
    for (const key of FILTER_KEYS) filters[key] = draft[key]
    page.value = 1
    // 条件与页码都未变时 queryKey 不变，Vue Query 因 staleTime(30s) 不会重新请求；
    // 「查询」是显式命令，必须每次都真的发一次请求。
    void queryClient.invalidateQueries({ queryKey: [COMPLETED_ORDERS_QUERY_KEY] })
  }

  /** 重置：清空草稿与生效条件，回到第 1 页 */
  function reset() {
    for (const key of FILTER_KEYS) {
      draft[key] = ''
      filters[key] = ''
    }
    page.value = 1
  }

  /** 刷新：保留当前条件重新请求 */
  function refresh() {
    return queryClient.invalidateQueries({ queryKey: [COMPLETED_ORDERS_QUERY_KEY] })
  }

  async function retry() {
    loadingTimedOut.value = false
    await refresh()
  }

  /** 导出：按当前生效条件拉取明细行，前端拼成 .xls 表格后触发下载 */
  async function exportOrders(): Promise<void> {
    const res = await purchaseApi.exportCompleted(buildParams(filters))
    if (!res.success) throw new Error(res.message || '导出失败')
    const rows = res.rows ?? []
    if (rows.length === 0) throw new Error('没有符合条件的数据可导出')
    downloadXls(buildExportTable(rows), '记录查询汇总.xls')
  }

  return reactive({
    orders,
    loading: isLoading,
    fetching: isFetching,
    error,
    total,
    totalPages,
    page,
    filters,
    draft,
    isDirty,
    hasFilter,
    search,
    reset,
    refresh,
    retry,
    exportOrders,
  })
}
