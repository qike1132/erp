/**
 * 路由守卫导航白名单回归（S9）
 *
 * 背景：旧守卫把目标路径截断成第一段再比对，并用三个硬编码路径
 * （/dashboard、/notifications、/）无条件放行。后果之一是移动端 tab
 * （/shipment、/incoming、/profile）不在后端导航数据里，非超管用户点「出货」
 * 会被踢回 /dashboard。
 *
 * 期望：完整路径匹配；无权限语义的入口用 meta.navExempt 显式豁免；
 * 导航数据加载失败时 fail-closed。
 */
import { describe, it, expect, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
import {
  buildLoginRedirect,
  DASHBOARD_PATH,
  isNavPathAllowed,
  normalizeRoutePath,
  resolveNavAccess,
  type NavAccessStore,
} from '@/router/navAccess'

const NAV_PATHS = ['/product', '/customer-order', '/outsource', '/stock', '/purchase-plan', '/user']

function makeStore(overrides: Partial<NavAccessStore> = {}): NavAccessStore {
  return {
    loaded: true,
    isLoggedIn: true,
    user: { is_super: false },
    navSections: [{ items: [] }],
    filteredNavSections: [{ items: NAV_PATHS.map((path) => ({ path })) }],
    init: vi.fn(async () => {}),
    loadNavSections: vi.fn(async () => {}),
    ...overrides,
  }
}

function target(path: string, meta: Record<string, unknown> = {}) {
  return { path, fullPath: path, meta }
}

describe('normalizeRoutePath', () => {
  it('去掉查询串、哈希与结尾斜杠', () => {
    expect(normalizeRoutePath('/product/123?tab=1')).toBe('/product/123')
    expect(normalizeRoutePath('/product/#/x')).toBe('/product')
    expect(normalizeRoutePath('/product/')).toBe('/product')
  })

  it('空串与根路径归一为 /', () => {
    expect(normalizeRoutePath('')).toBe('/')
    expect(normalizeRoutePath('/')).toBe('/')
  })
})

describe('isNavPathAllowed', () => {
  it('白名单路径本身放行', () => {
    expect(isNavPathAllowed('/product', NAV_PATHS)).toBe(true)
  })

  it('白名单路径的子路径放行（详情页、子页签）', () => {
    expect(isNavPathAllowed('/outsource/shipments', NAV_PATHS)).toBe(true)
    expect(isNavPathAllowed('/product/123', NAV_PATHS)).toBe(true)
    expect(isNavPathAllowed('/product/?page=2', NAV_PATHS)).toBe(true)
  })

  it('前缀仿冒路径不放行', () => {
    expect(isNavPathAllowed('/products', NAV_PATHS)).toBe(false)
    expect(isNavPathAllowed('/user-admin', NAV_PATHS)).toBe(false)
  })

  it('未授权的一级路径与其子路径都不放行', () => {
    expect(isNavPathAllowed('/permission', NAV_PATHS)).toBe(false)
    expect(isNavPathAllowed('/permission/roles/1', NAV_PATHS)).toBe(false)
    expect(isNavPathAllowed('/ocr-import', NAV_PATHS)).toBe(false)
  })

  it('navExempt 显式豁免（/dashboard、移动端 tab）', () => {
    expect(isNavPathAllowed('/dashboard', NAV_PATHS)).toBe(false)
    expect(isNavPathAllowed('/dashboard', NAV_PATHS, { navExempt: true })).toBe(true)
    expect(isNavPathAllowed('/shipment', NAV_PATHS, { navExempt: true })).toBe(true)
    expect(isNavPathAllowed('/shipment', NAV_PATHS)).toBe(false)
  })

  it('根路径始终放行（由路由表 redirect 处理）', () => {
    expect(isNavPathAllowed('/', NAV_PATHS)).toBe(true)
    expect(isNavPathAllowed('/', [])).toBe(true)
  })

  it('无导航数据时非豁免路径一律不放行', () => {
    expect(isNavPathAllowed('/product', [])).toBe(false)
  })
})

describe('resolveNavAccess', () => {
  it('公开页面（requiresAuth: false）直接放行，不读 store', async () => {
    const store = makeStore({ loaded: false, isLoggedIn: false })
    await expect(resolveNavAccess(target('/login', { requiresAuth: false }), store)).resolves.toBe(true)
    expect(store.init).not.toHaveBeenCalled()
  })

  it('未登录跳登录页并保留回跳地址', async () => {
    const store = makeStore({ isLoggedIn: false })
    await expect(resolveNavAccess(target('/product'), store)).resolves.toBe(buildLoginRedirect('/product'))
  })

  it('init 抛错时跳登录页而不是白屏', async () => {
    const store = makeStore({
      loaded: false,
      init: vi.fn(async () => {
        throw new Error('boom')
      }),
    })
    await expect(resolveNavAccess(target('/product'), store)).resolves.toBe(buildLoginRedirect('/product'))
  })

  it('超级用户不受导航白名单限制', async () => {
    const store = makeStore({ user: { is_super: true }, filteredNavSections: [] })
    await expect(resolveNavAccess(target('/permission'), store)).resolves.toBe(true)
  })

  it('非超管访问未授权路径被重定向到 /dashboard', async () => {
    const store = makeStore()
    await expect(resolveNavAccess(target('/permission'), store)).resolves.toBe(DASHBOARD_PATH)
    await expect(resolveNavAccess(target('/permission/roles/1'), store)).resolves.toBe(DASHBOARD_PATH)
  })

  it('非超管访问授权路径与其子路径放行', async () => {
    const store = makeStore()
    await expect(resolveNavAccess(target('/product'), store)).resolves.toBe(true)
    await expect(resolveNavAccess(target('/outsource/shipments'), store)).resolves.toBe(true)
  })

  it('navExempt 路由放行（移动端 tab 不再被踢回 /dashboard）', async () => {
    const store = makeStore()
    await expect(resolveNavAccess(target('/shipment', { navExempt: true }), store)).resolves.toBe(true)
    await expect(resolveNavAccess(target('/dashboard', { navExempt: true }), store)).resolves.toBe(true)
  })

  it('navSections 为空时先 await 在途请求再判定', async () => {
    const store = makeStore({ navSections: [] })
    await expect(resolveNavAccess(target('/product'), store)).resolves.toBe(true)
    expect(store.loadNavSections).toHaveBeenCalled()
  })

  it('未授权且目标即首页时返回 false，避免守卫自环', async () => {
    const store = makeStore()
    await expect(resolveNavAccess(target('/dashboard'), store)).resolves.toBe(false)
  })

  it('导航数据加载失败时取消导航（fail-closed）', async () => {
    const store = makeStore({
      navSections: [],
      loadNavSections: vi.fn(async () => {
        throw new Error('nav down')
      }),
    })
    await expect(resolveNavAccess(target('/product'), store)).resolves.toBe(false)
  })
})

describe('路由守卫接线（内存路由）', () => {
  it('未授权路径经守卫后落在 /dashboard，授权路径放行', async () => {
    const store = makeStore()
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', redirect: '/dashboard' },
        // 与生产路由表一致：/dashboard 声明 navExempt，避免守卫自环
        { path: '/dashboard', component: { template: '<div />' }, meta: { navExempt: true } },
        { path: '/product', component: { template: '<div />' } },
        { path: '/permission', component: { template: '<div />' } },
      ],
    })
    router.beforeEach((to) => resolveNavAccess(to, store))

    await router.push('/permission')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/dashboard')

    await router.push('/product')
    expect(router.currentRoute.value.path).toBe('/product')
  })
})
