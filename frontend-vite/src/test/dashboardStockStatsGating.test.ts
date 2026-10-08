import { describe, it, expect, vi, beforeEach } from 'vitest'
import { defineComponent, h, unref } from 'vue'

/**
 * dashboard 库存统计（GET /stock/stats）权限门控测试。
 *
 * 后端该端点要求 stockin_manage | order_manage（登录即可访问的 /dashboard 是
 * navExempt 页面，因此无库存权限的用户——如贝乐/仅报表账号——过去每次登录都会
 * 预取一次 403，且查询每 30s 自动刷新、全局 axios 拦截器对 403 弹「权限不足」，
 * 造成反复弹窗）。期望：
 * 1. 无权限 → stock 查询 enabled=false（不发请求、不再触发 30s 轮询），
 *    stockStats 降级为 dashboard stats 的今日值，图表照常渲染；
 * 2. 登录预取 prefetchDashboardData 同步跳过 stock-stats；
 * 3. 有权限 → 行为与原版一致。
 */

const mocks = vi.hoisted(() => ({
  statsApiMock: vi.fn(),
  stockStatsApiMock: vi.fn(),
  prefetchQueryMock: vi.fn(),
  hasAnyPermissionMock: vi.fn(),
  // useQuery 每次调用的 options 与独立的响应式 state（stats 与 stock 互不干扰）
  queryCalls: [] as Array<{
    options: { queryKey: readonly unknown[]; enabled?: unknown }
    refetch: ReturnType<typeof vi.fn>
    state: {
      data: { value: unknown }
      error: { value: unknown }
      isError: { value: boolean }
      isLoading: { value: boolean }
      isFetching: { value: boolean }
      dataUpdatedAt: { value: number }
    }
  }>,
}))

vi.mock('@/api', () => ({
  dashboardApi: { stats: mocks.statsApiMock },
  stockApi: { stats: mocks.stockStatsApiMock },
}))

vi.mock('@/composables/useToast', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasAnyPermission: mocks.hasAnyPermissionMock,
  }),
}))

vi.mock('@tanstack/vue-query', async () => {
  const { ref } = await import('vue')
  return {
    useQuery: (options: { queryKey: readonly unknown[]; enabled?: unknown }) => {
      const state = {
        data: ref<unknown>(null),
        error: ref<unknown>(null),
        isError: ref(false),
        isLoading: ref(false),
        isFetching: ref(false),
        dataUpdatedAt: ref(0),
      }
      const call = { options, refetch: vi.fn().mockResolvedValue(undefined), state }
      mocks.queryCalls.push(call)
      return { ...state, refetch: call.refetch }
    },
  }
})

import { mount, flushPromises } from '@vue/test-utils'
import {
  useDashboardStats,
  prefetchDashboardData,
} from '@/views/dashboard/composables/useDashboardStats'

type DashboardStatsHandle = ReturnType<typeof useDashboardStats>

let captured: DashboardStatsHandle | null = null

const Harness = defineComponent({
  setup() {
    captured = useDashboardStats()
    return () => h('div')
  },
})

const STATS_KEY_JSON = JSON.stringify(['dashboard', 'stats'])
const STOCK_KEY_JSON = JSON.stringify(['dashboard', 'stock-stats'])

function findCall(keyJson: string) {
  const call = mocks.queryCalls.find((c) => JSON.stringify(c.options.queryKey) === keyJson)
  expect(call, `useQuery 应以 queryKey ${keyJson} 创建`).toBeDefined()
  return call!
}

function mountDashboard(): DashboardStatsHandle {
  captured = null
  mount(Harness)
  return captured!
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.queryCalls.length = 0
})

describe('useDashboardStats 库存统计权限门控', () => {
  it('无库存权限：stock 查询被禁用，stockStats 降级为 dashboard 今日值', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(false)
    const handle = mountDashboard()
    await flushPromises()

    const stockCall = findCall(STOCK_KEY_JSON)
    expect(unref(stockCall.options.enabled)).toBe(false)

    // dashboard stats 到达后，饼图数据用它兜底（保持与原 403 降级一致的渲染表现）
    const statsCall = findCall(STATS_KEY_JSON)
    statsCall.state.data.value = { order_today: 5, stockin_today: 3 }
    await flushPromises()

    expect(handle.stockStats.value).toEqual({ order_quantity: 5, stockin_quantity: 3 })
  })

  it('有库存权限：stock 查询启用，数据未到时 stockStats 为 null（等待真实数据）', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(true)
    const handle = mountDashboard()
    await flushPromises()

    const stockCall = findCall(STOCK_KEY_JSON)
    expect(unref(stockCall.options.enabled)).toBe(true)
    expect(handle.stockStats.value).toBeNull()
  })

  it('有库存权限且 stock 查询失败：仍按原行为降级为 dashboard 今日值', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(true)
    const handle = mountDashboard()
    await flushPromises()

    const statsCall = findCall(STATS_KEY_JSON)
    statsCall.state.data.value = { order_today: 7, stockin_today: 2 }
    const stockCall = findCall(STOCK_KEY_JSON)
    stockCall.state.isError.value = true
    await flushPromises()

    expect(handle.stockStats.value).toEqual({ order_quantity: 7, stockin_quantity: 2 })
  })

  it('loadStats 重试路径：无权限时不 refetch stock 查询（v5 refetch 绕过 enabled，需显式门控）', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(false)
    const handle = mountDashboard()
    await flushPromises()

    await handle.loadStats()

    const statsCall = findCall(STATS_KEY_JSON)
    const stockCall = findCall(STOCK_KEY_JSON)
    expect(statsCall.refetch).toHaveBeenCalledTimes(1)
    expect(stockCall.refetch).not.toHaveBeenCalled()
  })

  it('loadStats 重试路径：有权限时 stats 与 stock 都 refetch', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(true)
    const handle = mountDashboard()
    await flushPromises()

    await handle.loadStats()

    const statsCall = findCall(STATS_KEY_JSON)
    const stockCall = findCall(STOCK_KEY_JSON)
    expect(statsCall.refetch).toHaveBeenCalledTimes(1)
    expect(stockCall.refetch).toHaveBeenCalledTimes(1)
  })
})

describe('prefetchDashboardData 登录预取门控', () => {
  it('无库存权限：只预取 dashboard stats，跳过 stock-stats', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(false)
    const queryClient = { prefetchQuery: mocks.prefetchQueryMock }

    await prefetchDashboardData(queryClient as never)

    expect(mocks.prefetchQueryMock).toHaveBeenCalledTimes(1)
    const firstOptions = mocks.prefetchQueryMock.mock.calls[0]?.[0] as { queryKey: readonly unknown[] } | undefined
    expect(JSON.stringify(firstOptions?.queryKey)).toBe(STATS_KEY_JSON)
  })

  it('有库存权限：stats 与 stock-stats 都预取', async () => {
    mocks.hasAnyPermissionMock.mockReturnValue(true)
    const queryClient = { prefetchQuery: mocks.prefetchQueryMock }

    await prefetchDashboardData(queryClient as never)

    expect(mocks.prefetchQueryMock).toHaveBeenCalledTimes(2)
    const keys = mocks.prefetchQueryMock.mock.calls.map((call) => JSON.stringify(call[0].queryKey))
    expect(keys).toContain(STATS_KEY_JSON)
    expect(keys).toContain(STOCK_KEY_JSON)
  })
})
