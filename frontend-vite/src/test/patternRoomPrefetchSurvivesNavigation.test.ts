import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { CanceledError } from 'axios'
import service, { abortPendingRequests } from '@/api/request'
import { usePatternRoomStore } from '@/stores/patternRoom'

/**
 * 回归：登录后的板房预取也不能被随后的 router.push 取消。
 *
 * 与仪表盘那次同源：`useLogin.ts` 里 `prefetchDashboardData()` 与
 * `usePatternRoomStore().prefetch()` 都在 `router.push()` 之前发起，守卫的
 * `abortPendingRequests()` 会取消它们。仪表盘两个接口已改为 service.get；
 * 板房的 grouped-list / pattern-makers 仍走 get()，被取消后：
 *   - `_silenceCanceled` 让 Promise 永不 settle；
 *   - store 的单飞表 `_inflightGrouped` 的 `.finally` 永不执行 → 条目永久残留；
 *   - 用户随后进 /pattern-room 读到的是**永不 settle** 的同一个 Promise，
 *     页面停在「加载中」且刷新无法自愈（快照里也是脏状态）。
 */

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasAnyPermission: () => true, hasPermission: () => true }),
}))

vi.mock('@/composables/useToast', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

/** 模拟 axios：abort 时以 CanceledError 拒绝（真实行为）；未取消则 60ms 后成功 */
function mockAxiosHonoringAbort() {
  return vi.spyOn(service, 'get').mockImplementation(((_url: string, config?: { signal?: AbortSignal }) => {
    return new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(
        () => resolve({ success: true, data: { items: [], total: 0, page: 1, per_page: 20, pages: 0 } }),
        60,
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
  it('板房预取被导航取消后，store 单飞表不得残留永不 settle 的 Promise', async () => {
    setActivePinia(createPinia())
    const store = usePatternRoomStore()
    // 登录：发起预取（不 await），紧接着 router.push 触发守卫取消
    void store.prefetch().catch(() => { /* 预取静默 */ })
    await new Promise((r) => setTimeout(r, 0))
    abortPendingRequests()

    // 取消后：单飞表必须已被清空，否则残留条目会把后来者永久卡住
    const stuck = await Promise.race([
      (store as unknown as { fetchGrouped: (k?: string, s?: string, p?: number) => Promise<unknown> })
        .fetchGrouped(undefined, 'in_progress', 1).then(() => 'settled'),
      new Promise((r) => setTimeout(() => r('stuck'), 400)),
    ])

    expect(stuck).toBe('settled')
  })
})
