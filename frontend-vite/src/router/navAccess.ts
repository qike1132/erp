/**
 * 导航白名单路由判定（S9 优化项）
 *
 * 背景：非超级用户只应访问后端导航数据（permission 表 -> /dashboard/nav-sections）
 * 中可见的入口。历史实现把目标路径截断成第一段再比对
 * （'/' + to.path.split('/').filter(Boolean)[0]），并额外硬编码放行
 * /dashboard、/notifications、/ 三个路径，由此产生两个问题：
 *   1. 子路径判定依赖「第一段」这一隐式约定：后端若返回嵌套导航 url
 *      （如 /outsource/shipments），白名单比对会失效；审计口径也与实际可见入口不一致；
 *   2. 移动端 tab（/shipment、/incoming、/profile）不在后端导航数据里，
 *      反而被重定向回 /dashboard，移动端入口对非超管用户完全失效。
 *
 * 现判据：
 *   - 完整路径匹配：目标路径等于白名单路径，或以「白名单路径 + /」开头；
 *   - 无权限语义的入口（/dashboard、移动端 tab 等）在路由表上用
 *     meta: { navExempt: true } 显式声明，不再散落在守卫里的硬编码 if。
 *
 * 注意：这不是安全边界。后端 34 个 router 中 32 个带 router 级
 * Depends(get_current_user_id)，接口权限由后端强制；本模块只统一前端体验与
 * 审计口径。
 */

declare module 'vue-router' {
  interface RouteMeta {
    /** 是否需要登录（false 表示公开页面，如 /login） */
    requiresAuth?: boolean
    /** 是否隐藏页面头部（既有约定） */
    hideHeader?: boolean
    /** 跳过导航白名单校验（仍需登录）。用于 /dashboard、移动端 tab 等无权限语义的入口。 */
    navExempt?: boolean
  }
}

/** 登录页路径 */
export const LOGIN_PATH = '/login'
/** 首页，同时是未授权路径的回退目标 */
export const DASHBOARD_PATH = '/dashboard'

/** 导航分组（只依赖 items[].path，避免与 store 内部类型耦合） */
export interface NavAccessSection {
  items: readonly { path: string }[]
}

/** 守卫需要读取的 store 能力（结构化类型，便于单测注入替身） */
export interface NavAccessStore {
  loaded: boolean
  isLoggedIn: boolean
  user: { is_super?: boolean | null } | null
  navSections: readonly unknown[]
  filteredNavSections: readonly NavAccessSection[]
  init: () => Promise<unknown>
  loadNavSections: () => Promise<unknown>
}

/** 守卫需要的路由字段 */
export interface NavAccessTarget {
  path: string
  fullPath: string
  meta: { requiresAuth?: unknown; navExempt?: unknown }
}

/** 去掉查询串、哈希与结尾多余斜杠，便于按路径前缀比较 */
export function normalizeRoutePath(path: string): string {
  if (!path) return '/'
  const withoutQuery = path.split('?')[0] ?? ''
  const withoutHash = withoutQuery.split('#')[0] ?? ''
  if (withoutHash.length <= 1) return '/'
  const trimmed = withoutHash.replace(/\/+$/, '')
  return trimmed === '' ? '/' : trimmed
}

/**
 * 判断目标路径是否落在导航白名单内。
 *
 * 采用「等于 或 以 白名单路径 + '/' 开头」的完整路径匹配：
 *   - '/product'      命中白名单 '/product'
 *   - '/product/123'  命中白名单 '/product'（详情页/子页签随父级入口放行）
 *   - '/products'     不命中（避免前缀仿冒）
 *
 * @param path 目标路由完整路径（to.path）
 * @param allowedPaths 后端导航数据展开出的入口路径集合
 * @param options.navExempt 目标路由是否声明 meta.navExempt
 */
export function isNavPathAllowed(
  path: string,
  allowedPaths: readonly string[],
  options: { navExempt?: boolean } = {},
): boolean {
  if (options.navExempt === true) return true

  const target = normalizeRoutePath(path)
  // 根路径由路由表自身的 redirect 处理（'/' -> '/dashboard'），不参与白名单
  if (target === '/') return true

  return allowedPaths.some((raw) => {
    const allowed = normalizeRoutePath(raw)
    if (allowed === '/') return false
    return target === allowed || target.startsWith(allowed + '/')
  })
}

/** 拼登录跳转地址，保留原始目标便于登录后回跳 */
export function buildLoginRedirect(fullPath: string): string {
  return LOGIN_PATH + '?redirect=' + encodeURIComponent(fullPath)
}

/**
 * 路由守卫主体（router/index.ts 的 beforeEach 直接委托到这里，便于单测）。
 *
 * 返回值语义与 vue-router 守卫一致：
 *   true   放行
 *   false  取消导航（fail-closed：导航数据加载失败）
 *   字符串 重定向到该路径
 */
export async function resolveNavAccess(
  to: NavAccessTarget,
  store: NavAccessStore,
): Promise<true | false | string> {
  if (to.meta.requiresAuth === false) {
    return true
  }

  if (!store.loaded) {
    try {
      // init() 内部已并行加载 fetchUser + fetchNavSections，无需重复调用
      await store.init()
    } catch (error) {
      console.error('[Router] 用户初始化失败', error)
      return buildLoginRedirect(to.fullPath)
    }
  }

  if (!store.isLoggedIn) {
    return buildLoginRedirect(to.fullPath)
  }

  // 权限检查：非超级用户只能访问 filteredNavSections 中可见的路径
  // fail-closed：navSections 未加载时阻止导航，避免权限绕过
  if (store.user && !store.user.is_super) {
    if (store.navSections.length === 0) {
      // navSections 尚未加载：await 在途请求（init 已后台触发）而非直接 return false，
      // 否则登录后 router.push 在导航数据返回前即被取消，UI 永久卡在「登录中」。
      try {
        await store.loadNavSections()
      } catch (error) {
        console.error('[Router] 导航数据加载失败，阻止导航:', error)
        return false
      }
    }

    const allowedPaths = store.filteredNavSections.flatMap((section) => section.items.map((item) => item.path))
    if (!isNavPathAllowed(to.path, allowedPaths, { navExempt: to.meta.navExempt === true })) {
      // 首页自身不再重定向：否则守卫会自环，vue-router 会以「无限重定向」中止导航。
      // 正常情况下 /dashboard 已在路由表声明 meta.navExempt，不会走到这里。
      return normalizeRoutePath(to.path) === DASHBOARD_PATH ? false : DASHBOARD_PATH
    }
  }

  return true
}
