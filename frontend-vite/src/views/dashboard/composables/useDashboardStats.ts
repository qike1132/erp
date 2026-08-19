/**
 * useDashboardStats — 仪表盘统计数据加载 Hook
 *
 * 封装仪表盘统计与库存统计的请求、校验、错误处理与降级。
 * 逻辑自 DashboardView.vue 原样搬移（图表渲染时机由调用方在
 * loadStats 返回后接管，保持原有 nextTick 后渲染的时序）。
 *
 * 性能优化：
 * - 两个 API 并行请求（Promise.all），延迟从 d1+d2 降至 max(d1,d2)
 * - 模块级缓存（TTL 30s），短时间内再次进入 Dashboard 零延迟
 * - 有缓存数据时静默刷新，不显示全屏 loading 遮罩
 */
import { ref, shallowRef } from 'vue'
import { dashboardApi, stockApi } from '@/api'
import { toast } from '@/composables/useToast'
import { usePerfMark } from '@/composables/usePerfMark'
import { devLog } from '@/utils/devLog'

/** 库存统计响应结构 */
export interface StockStats {
  order_quantity: number
  order_regular_quantity: number
  order_custom_quantity: number
  stockin_quantity: number
}

// ===== 模块级缓存（TTL 30s） =====
// 跨 composable 实例共享，避免短时间内重复请求
const CACHE_TTL = 30_000
let _statsCache: { data: Record<string, number>; ts: number } | null = null
let _stockStatsCache: { data: StockStats; ts: number } | null = null

/**
 * 预取 Dashboard 数据（登录成功后调用，填充模块级缓存）
 * 与路由跳转并行执行，用户到达 Dashboard 时数据已就绪 → 首次加载 0ms
 * 失败静默处理，Dashboard 挂载时会正常 fetch
 */
export async function prefetchDashboardData(): Promise<void> {
  const now = Date.now()
  if (_statsCache && now - _statsCache.ts < CACHE_TTL && _stockStatsCache && now - _stockStatsCache.ts < CACHE_TTL) {
    return
  }

  try {
    const [statsResp, stockResp] = await Promise.all([
      dashboardApi.stats(),
      stockApi.stats(),
    ])

    const r = statsResp as { data?: Record<string, number> } & Record<string, number>
    let raw: Record<string, number> | undefined
    if (r && typeof r === 'object') {
      if ('data' in r && r.data && typeof r.data === 'object') {
        raw = r.data as Record<string, number>
      } else if ('order_today' in r || 'stockin_today' in r || 'pending_approvals' in r) {
        raw = r as Record<string, number>
      }
    }
    if (raw) {
      _statsCache = {
        data: {
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
        },
        ts: Date.now(),
      }
    }

    if (stockResp) {
      _stockStatsCache = { data: stockResp, ts: Date.now() }
    }
  } catch {
    // 预取失败静默处理，Dashboard 挂载时正常 fetch
  }
}

export function useDashboardStats() {
  const perf = usePerfMark('dashboard')

  // ===== 数据状态 =====
  // shallowRef：API 响应整体替换（不逐属性变更），避免深层响应式开销
  // 初始化时从缓存恢复，避免首次渲染空白
  const stats = shallowRef<Record<string, number> | null>(_statsCache?.data ?? null)
  const stockStats = shallowRef<StockStats | null>(_stockStatsCache?.data ?? null)
  const isLoading = ref(false)
  const errorMessage = ref('')
  const errorDetail = ref('')
  const lastSyncTime = ref('')

  // ===== 数据加载（含错误处理和日志） =====
  async function loadStats(showLoading = true, force = false) {
    // 缓存有效且非强制刷新时直接返回，零延迟
    if (!force) {
      const now = Date.now()
      const statsValid = _statsCache && now - _statsCache.ts < CACHE_TTL
      const stockValid = _stockStatsCache && now - _stockStatsCache.ts < CACHE_TTL
      if (statsValid && stockValid) {
        stats.value = _statsCache!.data
        stockStats.value = _stockStatsCache!.data
        devLog('[Dashboard] 命中缓存，跳过请求')
        return
      }
    }

    // 有缓存数据时静默刷新（不显示 loading），仅首次加载或错误重试时显示骨架屏
    // 使用 _statsCache 而非 stats.value 判断：错误路径会设 stats.value 为全零对象但不清除缓存
    const shouldShowLoading = showLoading && !_statsCache
    if (shouldShowLoading) isLoading.value = true
    errorMessage.value = ''
    errorDetail.value = ''
    perf.mark('api-start')

    // 并行加载：延迟取 max(d1, d2) 而非 d1+d2
    await Promise.all([
      loadDashboardStats(),
      loadStockStats(),
    ])

    if (shouldShowLoading) isLoading.value = false
    perf.markEnd('api-start')
    perf.measure('api-stats', 'api-start')
  }

  async function loadDashboardStats() {
    try {
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

      const validated: Record<string, number> = {
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

      stats.value = validated
      _statsCache = { data: validated, ts: Date.now() }
      lastSyncTime.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })

      devLog('[Dashboard] 数据加载成功:', validated)
    } catch (err: unknown) {
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

      errorMessage.value = msg
      errorDetail.value = detail
      if (!axiosError.response || axiosError.response.status !== 401) {
        toast.error(msg, { duration: 4000, closable: true })
      }

      stats.value = {
        order_today: 0, order_yesterday: 0,
        stockin_today: 0, stockin_yesterday: 0,
        stockout_today: 0, stockout_yesterday: 0,
        pending_approvals: 0, low_stock_count: 0,
        pending_purchases: 0, pending_materials: 0,
      }

      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.error('[Dashboard] 数据加载失败:', err)
      }
    }
  }

  async function loadStockStats() {
    try {
      const resp = await stockApi.stats()
      if (resp) {
        stockStats.value = resp
        _stockStatsCache = { data: resp, ts: Date.now() }
      }
      devLog('[Dashboard] 库存统计数据加载成功:', stockStats.value)
    } catch (err) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[Dashboard] 库存统计数据加载失败，使用降级数据:', err)
      }
      stockStats.value = { order_quantity: stats.value?.order_today ?? 0, order_regular_quantity: 0, order_custom_quantity: 0, stockin_quantity: stats.value?.stockin_today ?? 0 }
    }
  }

  return {
    stats,
    stockStats,
    isLoading,

    errorMessage,
    errorDetail,
    lastSyncTime,
    loadStats,
  }
}
