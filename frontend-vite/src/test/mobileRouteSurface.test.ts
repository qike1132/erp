/**
 * 移动端路由面收敛（2026-11-23）
 *
 * 需求：移动端只保留「概览 / 登录 / 我的」三个页面，其余移动端页面与路由全部删除；
 * 已删路径（/product、/stock、/shipment 等）必须由通配路由回到 /dashboard，而不是 404。
 *
 * 本文件按 UA 分支实际加载 src/router/index.ts，锁三件事：
 * 1. 移动端路由名只有 MLogin / MDashboard / MProfile；
 * 2. 已下线路径导航后落在 /dashboard；
 * 3. PC 路由不受影响（抽查 /product、/stock、/purchase、/notifications）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const device = vi.hoisted(() => ({ mobile: true }))

vi.mock('@/composables/useDevice', () => ({
  isMobileDevice: () => device.mobile,
}))
// 本文件只验证路由表与重定向，不重复测认证/权限守卫。
vi.mock('@/router/guards', () => ({
  installNavigationGuards: () => {},
}))

async function loadRouter() {
  vi.resetModules()
  const mod = await import('@/router/index')
  return mod.default
}

const REMOVED_MOBILE_PATHS = [
  '/product',
  '/stock',
  '/shipment',
  '/customer-order',
  '/purchase',
  '/material-calculator',
  '/incoming',
  '/production',
  '/batch',
  '/case',
  '/notifications',
]

describe('移动端路由面收敛', () => {
  beforeEach(() => {
    device.mobile = true
  })

  it('移动端只暴露 /login /dashboard /profile', async () => {
    const router = await loadRouter()

    const names = router.getRoutes()
      .map((r) => r.name)
      .filter((n): n is NonNullable<typeof n> => n != null)
      .map(String)
      .sort()
    expect(names).toEqual(['MDashboard', 'MLogin', 'MProfile'])

    // 父路由 '/' 与空路径子路由都会规范化为 '/'，去重后再断言。
    const staticPaths = [...new Set(
      router.getRoutes()
        .map((r) => r.path)
        .filter((p) => !p.includes(':')),
    )].sort()
    expect(staticPaths).toEqual(['/', '/dashboard', '/login', '/profile'])

    // 两个保留页必须显式 navExempt：非超管用户的导航白名单里没有 /dashboard、/profile，
    // 漏掉豁免会被守卫踢回 /login，用户连退出登录的入口都没有。
    expect(router.resolve('/dashboard').meta.navExempt).toBe(true)
    expect(router.resolve('/profile').meta.navExempt).toBe(true)

    // 通配记录的重定向目标必须是字面量 /dashboard（不能被父路由的空路径 redirect 掩盖）
    const wildcard = router.getRoutes().find((r) => r.path === '/:pathMatch(.*)*')
    expect(wildcard, '缺少移动端通配路由').toBeDefined()
    expect(wildcard?.redirect).toBe('/dashboard')
  })

  it('已删路径导航后重定向到 /dashboard', async () => {
    const router = await loadRouter()

    for (const path of REMOVED_MOBILE_PATHS) {
      await router.push(path)
      expect(router.currentRoute.value.path, path).toBe('/dashboard')
    }
  })

  it('PC 路由不受影响', async () => {
    device.mobile = false
    const router = await loadRouter()

    expect(router.resolve('/product').name).toBe('Product')
    expect(router.resolve('/stock').name).toBe('Stock')
    expect(router.resolve('/purchase').name).toBe('Purchase')
    expect(router.resolve('/notifications').name).toBe('Notifications')
  })
})