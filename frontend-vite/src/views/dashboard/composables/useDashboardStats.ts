/**
 * useDashboardStats — 仪表盘统计数据加载 Hook（Vue Query SWR 架构）
 *
 * 基于 TanStack Vue Query 实现：
 * - SWR (Stale-While-Revalidate)：缓存过期时立即返回旧数据 + 后台刷新 → 0ms
 * - refetchInterval：每 30s 自动刷新（替代手写 useDashboardAutoRefresh）
 * - 请求去重：并发调用共享同一 Promise
 * - isLoading/isError 状态自动管理
 */
import { useQuery, type QueryClient } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { dashboardApi, stockApi } from '@/api'
import { toast } from '@/composables/useToast'
import { usePerfMark } from '@/composables/usePerfMark'
import { useAuthStore } from '@/stores/auth'
import { devLog } from '@/utils/devLog'
import type { StockStatsData } from '@/types/api'

/**
 * 库存统计响应结构。
 *
 * 直接取后端 OpenAPI 生成的类型（`api.d.ts`），不再手写——此前这里手抄了一份 4 字段形状，
 * 其中 `order_regular_quantity` / `order_custom_quantity` 早在后端「库存聚合移除国家维度与
 * 定制订单统计」时就被删除，前端从未跟上，成了静默的幻影字段。
 */
export type StockStats = StockStatsData

// ===== Query Keys & 常量 =====
const CACHE_TTL = 30_000
const STATS_KEY = ['dashboard', 'stats'] as const
const STOCK_KEY = ['dashboard', 'stock-stats'] as const

// 与后端 GET /stock/stats 的权限依赖保持一致（fastapi_app/api/v1/endpoints/stock.py::
// get_stock_stats → require_any_permission('stockin_manage', 'order_manage')）。
// 无权限用户（如仅报表/贝乐订单账号）不发起该请求：后端会 403，全局 axios
// 拦截器会对 403 弹「权限不足」，且本查询每 30s 自动刷新会反复弹窗。
// 与 patternRoom 版师列表预取的门控先例同策略。
const STOCK_STATS_PERMISSIONS = ['stockin_manage', 'order_manage'] as const

const FALLBACK_STATS: Record<string, number> = {
  order_today: 0, order_yesterday: 0,
  stockin_today: 0, stockin_yesterday: 0,
  stockout_today: 0, stockout_yesterday: 0,
  pending_approvals: 0, low_stock_count: 0,
  pending_purchases: 0, pending_materials: 0,
}

// ===== Query 函数（useQuery 与 prefetchQuery 共享） =====
async function fetchStats(): Promise<Record<string, number>> {
  const resp = await dashboardApi.stats() as { success?: boolean; data?: Record<string, number> } | Record<string, number>

  let raw: Record<string, number> | undefined
  if (resp && typeof resp === 'object') {
    if ('data' in resp && resp.data && typeof resp.data === 'object') {
      raw = resp.data as Record<string, number>
    } else if ('order_today' in resp || 'stockin_today' in resp || 'pending_approvals' in resp) {
      raw = resp as Record<string, number>
    }
  }

  if (!raw) {
    throw new Error('API 返回数据格式异常：data 字段缺失或非对象类型')
  }

  return {
    order_today: Number(raw.order_today) || 0,
    order_yesterday: Number(raw.order_yesterday) || 0,
    stockin_today: Number(raw.stockin_today) || 0,
    stockin_yesterday: Number(raw.stockin_yesterday) || 0,
    stockout_today: Number(raw.stockout_today) || 0,
    stockout_yesterday: Number(raw.stockout_yesterday) || 0,
    pending_approvals: Number(raw.pending_approvals) || 0,
    low_stock_count: Number(raw.low_stock_count) || 0,
    pending_purchases: Number(raw.pending_purchases) || 0,
    pending_materials: Number(raw.pending_materials) || 0,
  }
}

async function fetchStockStats(): Promise<StockStats> {
  return stockApi.stats()
}

// ===== 预取（登录后调用，填充 Vue Query 缓存） =====
/**
 * 预取 Dashboard 数据（登录成功后调用，填充 Vue Query 缓存）
 * 用户到达 Dashboard 时 useQuery 命中缓存 → 首次加载 0ms
 * 失败静默处理，Dashboard 挂载时 useQuery 会正常 fetch
 */
export function prefetchDashboardData(queryClient: QueryClient): Promise<void> {
  const tasks: Promise<unknown>[] = [
    queryClient.prefetchQuery({ queryKey: STATS_KEY, queryFn: fetchStats, staleTime: CACHE_TTL }),
  ]
  // 无库存权限的用户跳过 stock-stats 预取，避免每次登录产生一次 403 弹窗
  if (useAuthStore().hasAnyPermission([...STOCK_STATS_PERMISSIONS])) {
    tasks.push(queryClient.prefetchQuery({ queryKey: STOCK_KEY, queryFn: fetchStockStats, staleTime: CACHE_TTL }))
  }
  return Promise.all(tasks).then(() => undefined).catch(() => {
    // 预取失败静默处理
  })
}

// ===== 错误处理 =====
function handleStatsError(err: unknown): { msg: string; detail: string } {
  const axiosError = err as { response?: { status?: number; data?: unknown }; message?: string; code?: string }

  let msg = '数据加载失败'
  let detail = ''

  if (axiosError.response) {
    const status = axiosError.response.status ?? 0
    if (status === 401) {
      msg = '登录已过期，正在跳转...'
      detail = '请重新登录后查看数据'
    } else if (status === 403) {
      msg = '权限不足，无法访问仪表盘数据'
    } else if (status >= 500) {
      msg = '服务器内部错误，请稍后重试'
      detail = `HTTP ${status}`
    } else {
      msg = `请求失败 (HTTP ${status})`
    }
    if (axiosError.response.data && typeof axiosError.response.data === 'object') {
      const data = axiosError.response.data as Record<string, unknown>
      if (data.detail) detail = String(data.detail)
      else if (data.message) detail = String(data.message)
    }
  } else if (axiosError.code === 'ECONNABORTED') {
    msg = '请求超时，请检查网络连接'
  } else if (axiosError.code === 'ERR_NETWORK') {
    msg = '网络连接失败，请检查网络状态'
  } else if (axiosError.message) {
    msg = axiosError.message
  }

  if (!axiosError.response || axiosError.response.status !== 401) {
    toast.error(msg, { duration: 4000, closable: true })
  }

  return { msg, detail }
}

// ===== 主 Composable =====
export function useDashboardStats() {
  const perf = usePerfMark('dashboard')
  const authStore = useAuthStore()
  const canViewStockStats = computed(() => authStore.hasAnyPermission([...STOCK_STATS_PERMISSIONS]))

  const statsQuery = useQuery({
    queryKey: STATS_KEY,
    queryFn: fetchStats,
    staleTime: CACHE_TTL,
    refetchInterval: CACHE_TTL,
    retry: 1,
  })

  const stockQuery = useQuery({
    queryKey: STOCK_KEY,
    queryFn: fetchStockStats,
    staleTime: CACHE_TTL,
    refetchInterval: CACHE_TTL,
    retry: 1,
    // 无权限时禁用查询：不发请求、refetchInterval 也不再触发
    enabled: canViewStockStats,
  })

  // ===== 状态 =====
  // isLoading：仅首次加载（无数据）为 true，后台刷新时为 false（SWR）
  const isLoading = computed(() => statsQuery.isLoading.value || stockQuery.isLoading.value)
  // isFetching：任何 fetch（含后台刷新）都为 true
  const isFetching = computed(() => statsQuery.isFetching.value || stockQuery.isFetching.value)

  const errorMessage = ref('')
  const errorDetail = ref('')
  const lastSyncTime = ref('')

  // ===== 数据（含错误降级） =====
  const stats = computed(() => {
    if (statsQuery.data.value) return statsQuery.data.value
    if (statsQuery.isError.value) return FALLBACK_STATS
    return null
  })

  const stockStats = computed<StockStats | null>(() => {
    if (stockQuery.data.value) return stockQuery.data.value
    // 无权限（查询被禁用）与请求失败同样降级：用 dashboard stats 的今日值兜底，
    // 图表照常渲染（与既有 403 降级表现一致，只是不再发起注定 403 的请求）。
    if (stockQuery.isError.value || !canViewStockStats.value) {
      return {
        order_quantity: stats.value?.order_today ?? 0,
        stockin_quantity: stats.value?.stockin_today ?? 0,
      }
    }
    return null
  })

  // ===== Watch：成功 → 更新时间 =====
  watch(() => statsQuery.dataUpdatedAt.value, (ts) => {
    if (ts) {
      lastSyncTime.value = new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
      if (import.meta.env.DEV) {
        devLog('[Dashboard] 数据加载成功:', statsQuery.data.value)
      }
    }
  })

  // ===== Watch：错误 → 设置错误信息 + toast =====
  watch(() => statsQuery.error.value, (err) => {
    if (!err) {
      errorMessage.value = ''
      errorDetail.value = ''
      return
    }
    const { msg, detail } = handleStatsError(err)
    errorMessage.value = msg
    errorDetail.value = detail
    if (import.meta.env.DEV) {

      console.error('[Dashboard] 数据加载失败:', err)
    }
  })

  // ===== 库存统计错误（仅 dev 日志，不 toast） =====
  watch(() => stockQuery.error.value, (err) => {
    if (err && import.meta.env.DEV) {

      console.warn('[Dashboard] 库存统计数据加载失败，使用降级数据:', err)
    }
  })

  // ===== 显式刷新（用于 retryLoad） =====
  async function loadStats() {
    perf.mark('api-start')
    const tasks: Promise<unknown>[] = [statsQuery.refetch()]
    // 重试路径必须与 enabled 同口径门控：v5 的 refetch() 不受 enabled:false 约束
    // （官方文档明示），否则无权限用户点「重试」会对 /stock/stats 发注定 403 的
    // 请求，再次触发全局拦截器的「权限不足」弹窗。
    if (canViewStockStats.value) tasks.push(stockQuery.refetch())
    await Promise.all(tasks)
    perf.markEnd('api-start')
    perf.measure('api-stats', 'api-start')
  }

  return {
    stats,
    stockStats,
    isLoading,
    isFetching,
    errorMessage,
    errorDetail,
    lastSyncTime,
    loadStats,
  }
}
