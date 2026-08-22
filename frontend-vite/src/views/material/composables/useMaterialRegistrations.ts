// 来料进度 / 历史查询的数据加载（Vue Query SWR + 服务端分页 + 数据预处理）
// 方案4：迁移到 @tanstack/vue-query，删除手写 SWR/sessionStorage 缓存（由 persistQueryClient 接管）
// 方案1：Vue Query shallowRef + structural sharing 避免全量重渲染
// 方案5：在预处理阶段格式化 parseFloat，消除模板内反复类型转换
import { ref, computed, watch, onUnmounted, type Ref } from 'vue'
import { useQuery, keepPreviousData } from '@tanstack/vue-query'
import { queryClient } from '@/utils/queryClient'
import { materialApi } from '@/api'
import type { Registration, RegItem } from '@/api/material'

// 同一供应商 + 同一物料型号合并后的明细行
export interface MergedItem extends RegItem {
  ordered_quantity: number
  received_quantity: number
  progress: number
  /** 预格式化的采购数量字符串（方案5：消除模板内 parseFloat） */
  ordered_display: string
  /** 预格式化的已到货数量字符串 */
  received_display: string
}

// 按供应商分组的物料行
export interface SupplierGroupRow {
  supplierName: string
  items: MergedItem[]
}

// 来料进度表格渲染行
export interface ProgressOrderRow extends Registration {
  order_no: string
  items: RegItem[]
  groupedItems: SupplierGroupRow[]
}

/** 预处理来料进度行：过滤 filling、按供应商分组、按物料合并、预格式化数量（方案1+5） */
function preprocessProgressRows(rows: Registration[]): ProgressOrderRow[] {
  return rows.map((r) => {
    const items = (r.items || []).filter((i) => i.material_category !== 'filling')
    const groupMap = new Map<string, typeof items>()
    for (const i of items) {
      const key = (i as { supplier_name?: string }).supplier_name || '未指定'
      if (!groupMap.has(key)) groupMap.set(key, [])
      groupMap.get(key)!.push(i)
    }
    const mergedGroupedItems = Array.from(groupMap, ([supplierName, groupItems]) => {
      const mergedMap = new Map<string, MergedItem>()
      for (const i of groupItems) {
        const key = i.material_name
        const ordered = parseFloat(String(i.ordered_quantity || 0))
        const received = parseFloat(String(i.received_quantity || 0))
        const existing = mergedMap.get(key)
        if (existing) {
          existing.ordered_quantity += ordered
          existing.received_quantity += received
          existing.progress = existing.ordered_quantity > 0
            ? Math.round((existing.received_quantity / existing.ordered_quantity) * 100)
            : 0
          existing.ordered_display = existing.ordered_quantity.toFixed(0)
          existing.received_display = existing.received_quantity.toFixed(0)
        } else {
          const progress = ordered > 0 ? Math.round((received / ordered) * 100) : 0
          mergedMap.set(key, {
            ...i,
            ordered_quantity: ordered,
            received_quantity: received,
            progress,
            ordered_display: ordered.toFixed(0),
            received_display: received.toFixed(0),
          })
        }
      }
      return { supplierName, items: Array.from(mergedMap.values()) }
    })
    return { ...r, order_no: r.purchase_order_no, items, groupedItems: mergedGroupedItems }
  })
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

  const progressQuery = useQuery({
    queryKey: computed(() => ['material', 'progress', pPage.value, pPerPage.value] as const),
    queryFn: () => materialApi.registrations({ page: pPage.value, per_page: pPerPage.value, exclude_completed: true }),
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  })

  watch(() => progressQuery.error.value, (err) => { if (err) toast('加载失败', 'error') })

  const progressRows = computed<Registration[]>(() => progressQuery.data.value?.registrations || [])
  const progressOrderRows = computed<ProgressOrderRow[]>(() => preprocessProgressRows(progressRows.value))
  const pPages = computed(() => progressQuery.data.value?.pages ?? progressQuery.data.value?.total_pages ?? 1)
  const pIsLoading = computed(() => progressQuery.isLoading.value)
  const pIsFetching = computed(() => progressQuery.isFetching.value && !progressQuery.isLoading.value)
  const progressCount = computed(() => progressQuery.data.value?.total ?? 0)

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

  /** 收货后强制刷新来料进度（invalidate 触发 refetch，Vue Query 自动去重） */
  function loadProgress(page?: number) {
    if (page) pPage.value = page
    queryClient.invalidateQueries({ queryKey: ['material', 'progress'] })
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
    pPage, pPerPage, pPages, pIsLoading, pIsFetching, progressRows, progressCount, progressOrderRows,
    hPage, hPerPage, hPages, hIsLoading, hIsFetching, hRegistrations,
    loadProgress, loadHistory, ensureProgressLoaded, ensureHistoryLoaded,
    onProgressPageChange, onHistoryPageChange,
  }
}
