import { describe, it, expect, vi } from 'vitest'
import { QueryClient } from '@tanstack/vue-query'
import { CanceledError } from 'axios'
import { get } from '@/api/request'
import service from '@/api/request'
import { abortPendingRequests } from '@/api/request'

/**
 * 回归：Vue Query 的 queryFn 不能被路由切换取消。
 *
 * 2026-10-22 修仪表盘登录预取时只改了两个端点（dashboard/stats、stock/stats），
 * 本测试随后证明**根因未除**：任何页面级查询在请求在途时被切走再切回，都会
 * 让该 queryKey 永久停在 fetchStatus='fetching'，页面永远显示「加载中」。
 *
 * 修法：给 get() 增加 routeCancel 选项，让「归缓存/单飞所有」的请求不注册到
 * _pendingControllers（同时保留 GET 去重），并在 useEnhancedList /
 * useVirtualScrollList 这两个列表地基上默认启用，一次覆盖所有下游页面。
 *
 * 场景（纯导航时序，不依赖登录）：
 *   1. 列表查询发起 GET（useQuery → get()）
 *   2. 响应未到，用户切到别的页面 → 守卫 abortPendingRequests()
 *   3. 用户再切回 → 组件重新挂载，useQuery 复用同一 queryKey
 */

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

/** 80ms 后才成功的慢请求；abort 时以 CanceledError 拒绝（真实 axios 行为） */
function mockSlowAxios() {
  return vi.spyOn(service, 'get').mockImplementation(((_url: string, config?: { signal?: AbortSignal }) => {
    return new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => resolve({ success: true, data: { items: [] } }), 80)
      config?.signal?.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(new CanceledError())
      })
    })
  }) as typeof service.get)
}

describe('页面级查询：导航离开再返回', () => {
  it('请求在途时切走再切回，查询不得永久停在 fetching', async () => {
    const spy = mockSlowAxios()
    const qc = new QueryClient()

    // 1) 进入 /product：组件挂载，useQuery 发起查询
    // 列表页的真实调用形态：useEnhancedList / useVirtualScrollList 的 queryFn
    const listQueryFn = () => get('/product/list', undefined, { routeCancel: false })

    void qc.prefetchQuery({ queryKey: ['product', 'list'], queryFn: listQueryFn })
    await new Promise((r) => setTimeout(r, 0))

    // 2) 切到 /customer：守卫取消上一路由未完成的 GET
    abortPendingRequests()
    await new Promise((r) => setTimeout(r, 0))

    // 3) 切回 /product：组件重新挂载，同一 queryKey 再取一次
    const back = await Promise.race([
      qc.fetchQuery({ queryKey: ['product', 'list'], queryFn: listQueryFn })
        .then(() => 'settled'),
      new Promise((r) => setTimeout(() => r('stuck'), 500)),
    ])
    const state = qc.getQueryState(['product', 'list'])
    spy.mockRestore()

    // 关键判据：fetchStatus 必须回到 idle，且取数必须真的 settle
    expect(back).toBe('settled')
    expect(state?.fetchStatus).toBe('idle')
    expect(state?.status).toBe('success')
  })

  it('对照组：默认（参与路由取消）的查询仍会被守卫取消', async () => {
    const spy = mockSlowAxios()
    const qc = new QueryClient()

    void qc.prefetchQuery({ queryKey: ['legacy'], queryFn: () => get('/legacy') })
    await new Promise((r) => setTimeout(r, 0))
    abortPendingRequests()
    await new Promise((r) => setTimeout(r, 0))

    const state = qc.getQueryState(['legacy'])
    spy.mockRestore()

    // 守卫的既有语义必须保留：普通页面请求仍应被取消（这是 abortPendingRequests 的设计意图）
    expect(state?.fetchStatus).toBe('fetching')
  })
})
