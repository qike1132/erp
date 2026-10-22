import { describe, it, expect, afterEach, vi } from 'vitest'
import { createRouter, createMemoryHistory, type Router } from 'vue-router'
import { CanceledError } from 'axios'
import { installNavigationGuards } from '@/router/guards'
import { abortPendingRequests, createTrackedController, default as service } from '@/api/request'
import { dashboardApi } from '@/api/dashboard'
import type { NavAccessStore } from '@/router/navAccess'

/**
 * 回归：认证守卫内发起的导航数据请求，不能被同一次导航的「取消旧请求」守卫取消。
 *
 * 生产事故（2026-10-22）：abortPendingRequests 注册在 resolveNavAccess 之后，
 * 超级管理员加载页面时 authStore.init() 发起的 /dashboard/nav-sections 被下一个守卫
 * 立刻 abort（nginx 499），navSections 永远为空 → 侧边栏只剩搜索框。
 */

function createFakeStore() {
  const started: AbortController[] = []
  const store: NavAccessStore = {
    loaded: false,
    isLoggedIn: true,
    user: { is_super: true },
    navSections: [],
    filteredNavSections: [],
    init: async () => {
      // 模拟 authStore.init()：用户信息就绪后发起导航数据 GET（fire-and-forget）
      started.push(createTrackedController())
      store.loaded = true
    },
    loadNavSections: async () => {},
  }
  return { store, started }
}

function createTestRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/other', component: { template: '<div />' } },
    ],
  })
}

afterEach(() => {
  // 清空模块级 _pendingControllers，避免用例间串扰
  abortPendingRequests()
})

describe('路由守卫顺序', () => {
  it('认证守卫内发起的请求不被本次导航取消', async () => {
    const { store, started } = createFakeStore()
    const router = createTestRouter()
    installNavigationGuards(router, () => store)

    await router.push('/')

    expect(started).toHaveLength(1)
    expect(started[0]!.signal.aborted).toBe(false)
  })

  it('路由切换仍会取消上一路由遗留的请求', async () => {
    const { store } = createFakeStore()
    const router = createTestRouter()
    installNavigationGuards(router, () => store)

    await router.push('/')
    const leftover = createTrackedController() // 模拟上一路由组件发出的 GET

    await router.push('/other')

    expect(leftover.signal.aborted).toBe(true)
  })
})

describe('导航数据请求生命周期', () => {
  it('导航数据请求不随路由切换被取消', async () => {
    // 模拟 axios：请求被 abort 时以 CanceledError 拒绝（真实行为）
    let resolveFn!: (value: unknown) => void
    const spy = vi.spyOn(service, 'get').mockImplementation(((_url: string, config?: { signal?: AbortSignal }) => {
      return new Promise((resolve, reject) => {
        resolveFn = resolve as (value: unknown) => void
        config?.signal?.addEventListener('abort', () => reject(new CanceledError()))
      })
    }) as typeof service.get)

    const pending = dashboardApi.navSections()
    abortPendingRequests()
    resolveFn({ section: { name: '测试分组', items: [] } })

    const settled = await Promise.race([
      pending.then(() => 'resolved'),
      new Promise((resolve) => setTimeout(() => resolve('pending'), 100)),
    ])
    spy.mockRestore()

    // 被 abort 的 tracked GET 会被 _silenceCanceled 变成永不 settle 的 Promise，
    // 导航数据将永远填不上（登录后侧边栏空白）。
    expect(settled).toBe('resolved')
  })
})
