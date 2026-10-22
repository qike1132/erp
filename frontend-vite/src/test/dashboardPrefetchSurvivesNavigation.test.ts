import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { QueryClient } from '@tanstack/vue-query'
import { CanceledError } from 'axios'
import service, { abortPendingRequests } from '@/api/request'
import { prefetchDashboardData } from '@/views/dashboard/composables/useDashboardStats'

/**
 * 回归：登录预取的仪表盘数据不能被随后的 router.push 取消。
 *
 * 生产现象（2026-10-22）：首次登录后仪表盘统计卡片一直停在加载骨架、图表空白，
 * 在同一页面刷新一次才显示数据。
 *
 * 根因：登录成功后 useLogin 先 prefetchDashboardData() 再 router.push()，
 * 导航守卫 abortPendingRequests() 会取消这两个仍在途的 GET；get() 用
 * _silenceCanceled 把取消变成**永不 settle** 的 Promise，Vue Query 的查询因此
 * 永久停在 fetchStatus='fetching'，组件挂载时不会重新取数，只有整页刷新才恢复。
 */

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasAnyPermission: () => true }),
}))

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

/** 模拟 axios：请求被 abort 时以 CanceledError 拒绝（真实行为）；未取消则 50ms 后成功 */
function mockAxiosHonoringAbort() {
  return vi.spyOn(service, 'get').mockImplementation(((_url: string, config?: { signal?: AbortSignal }) => {
    return new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(
        () => resolve({ success: true, data: { order_today: 5, stockin_today: 3, pending_approvals: 1 } }),
        50,
      )
      config?.signal?.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(new CanceledError())
      })
    })
  }) as typeof service.get)
}

let spy: ReturnType<typeof mockAxiosHonoringAbort> | null = null

beforeEach(() => {
  spy = mockAxiosHonoringAbort()
})

afterEach(() => {
  spy?.mockRestore()
  spy = null
  abortPendingRequests()
})

describe('登录预取与随后的导航', () => {
  it('预取请求不被导航守卫取消，查询不会永久卡在 fetching', async () => {
    const qc = new QueryClient()

    const prefetch = prefetchDashboardData(qc)
    // 让预取请求真正发出（注册到 _pendingControllers）后再模拟 router.push
    await new Promise((r) => setTimeout(r, 0))
    abortPendingRequests()

    const settled = await Promise.race([
      prefetch.then(() => 'settled'),
      new Promise((r) => setTimeout(() => r('stuck'), 300)),
    ])

    const statsState = qc.getQueryState(['dashboard', 'stats'])
    const stockState = qc.getQueryState(['dashboard', 'stock-stats'])

    expect(settled).toBe('settled')
    expect(statsState?.status).toBe('success')
    expect(statsState?.fetchStatus).toBe('idle')
    expect(stockState?.status).toBe('success')
  })
})
